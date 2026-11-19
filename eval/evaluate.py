"""Evaluate human ranges for Klip/Ringkas; separate synthetic, assisted and unverified data."""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from api.app.config import ROOT
from api.app.schemas import OutputSettings, StrictModel, Transcript
from worker.pipeline.boundaries import iou
from worker.pipeline.rerank import topic_key


class Range(StrictModel):
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    topic: str = ""

    @model_validator(mode="after")
    def ordered(self):
        if self.end_s <= self.start_s:
            raise ValueError("Rentang evaluasi terbalik atau kosong")
        return self


class Expected(StrictModel):
    mode: str
    source: str
    dataset_kind: str = "human"
    ranges: list[Range] = Field(min_length=1)
    transcript: str | None = None
    settings: OutputSettings = Field(default_factory=OutputSettings)
    annotator: str = ""
    note: str = ""
    annotation_status: Literal["draft", "reviewed"] = "reviewed"
    independent: bool = True
    provenance: dict = Field(default_factory=dict)


class CondenseExpected(StrictModel):
    mode: Literal["condense"]
    source: str
    dataset_kind: Literal["human", "synthetic"] = "human"
    transcript: str | None = None
    settings: OutputSettings = Field(default_factory=OutputSettings)
    required_chapters: list[Range] = Field(min_length=1)
    required_specs: list[Range] = Field(default_factory=list)
    annotator: str = ""
    note: str = ""
    annotation_status: Literal["draft", "reviewed"] = "reviewed"
    independent: bool = True
    provenance: dict = Field(default_factory=dict)


class CondensePrediction(StrictModel):
    mode: Literal["condense"] = "condense"
    provider: str = "unspecified"
    duration_s: float = Field(gt=0)
    retained_ranges: list[Range]
    provenance: dict = Field(default_factory=dict)


def coverage_metrics(expected: list[Range], retained: list[Range], threshold: float):
    covered = []
    for gold in expected:
        intervals = sorted(
            (max(gold.start_s, p.start_s), min(gold.end_s, p.end_s))
            for p in retained
            if p.start_s < gold.end_s and p.end_s > gold.start_s
        )
        merged = []
        for start, end in intervals:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        fraction = sum(b - a for a, b in merged) / (gold.end_s - gold.start_s)
        covered.append(
            {
                "range": gold.model_dump(),
                "coverage": min(1, fraction),
                "matched": fraction >= threshold - 1e-6,
            }
        )
    matched = sum(c["matched"] for c in covered)
    return {
        "expected": len(expected),
        "matched": matched,
        "recall": matched / len(expected) if expected else None,
        "threshold": threshold,
        "ranges": covered,
    }


def verify_inputs(expected, case: Path):
    from worker.pipeline.ingest import checksum
    from worker.pipeline.provenance import transcript_fingerprint

    path = resolve_path(expected.source, case)
    source_id, verified = str(path.resolve()), False
    if path.is_file():
        source_id = checksum(path)
        if (
            expected.provenance.get("source_sha256")
            and source_id != expected.provenance["source_sha256"]
        ):
            raise ValueError("Checksum sumber tidak cocok dengan anotasi")
        verified = True
    transcript = None
    if expected.transcript:
        transcript = Transcript.model_validate_json(
            resolve_path(expected.transcript, case).read_text()
        )
        claimed = expected.provenance.get("transcript_sha256")
        if claimed and claimed != transcript_fingerprint(transcript):
            raise ValueError("Transkrip berubah setelah anotasi")
    return source_id, verified, transcript


def range_metrics(expected: list[Range], predictions: list[Range], threshold=0.5):
    # Maximum bipartite matching: one broad/duplicate clip cannot cover several labels.
    edges = {
        index: sorted(
            [
                j
                for j, prediction in enumerate(predictions)
                if iou((gold.start_s, gold.end_s), (prediction.start_s, prediction.end_s))
                >= threshold
            ],
            key=lambda j: iou(
                (gold.start_s, gold.end_s), (predictions[j].start_s, predictions[j].end_s)
            ),
            reverse=True,
        )
        for index, gold in enumerate(expected)
    }
    assigned = {}

    def assign(index, seen):
        for candidate in edges[index]:
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate not in assigned or assign(assigned[candidate], seen):
                assigned[candidate] = index
                return True
        return False

    for index in edges:
        assign(index, set())
    topics = Counter(topic_key(p.topic) for p in predictions if p.topic.strip())
    matched = len(assigned)
    return {
        "expected": len(expected),
        "predicted": len(predictions),
        "matched": matched,
        "recall_iou_0_5": matched / len(expected) if expected else None,
        "precision_iou_0_5": matched / len(predictions) if predictions else 0,
        "unique_topics": len(topics),
        "max_per_topic": max(topics.values(), default=0),
        "topic_limit_passed": max(topics.values(), default=0) <= 2,
        "pairs": [
            {
                "expected_index": index,
                "prediction_index": candidate,
                "iou": iou(
                    (expected[index].start_s, expected[index].end_s),
                    (predictions[candidate].start_s, predictions[candidate].end_s),
                ),
            }
            for candidate, index in sorted(assigned.items())
        ],
    }


def audit_predictions(data: dict):
    if "candidates" not in data:
        return data
    candidates = {c["id"]: c for c in data["candidates"]}

    def ranges(ids):
        return [
            {
                "start_s": candidates[i]["boundary"]["start"],
                "end_s": candidates[i]["boundary"]["end"],
                "topic": candidates[i]["packaging"]["topic"],
            }
            for i in ids
        ]

    return {
        "clips": ranges(data.get("selected", [])),
        "baseline_clips": ranges(data.get("baseline_selected", [])),
        "provider": data.get("provider"),
        "selection_metrics": data.get("metrics", {}),
        "provenance": data.get("provenance", {}),
    }


def run_case(expected: Expected, case: Path, work_root: Path):
    """Run selection against a supplied transcript, without rendering or paid-call defaults."""
    import hashlib

    from worker.pipeline.ingest import checksum
    from worker.pipeline.llm import LLMClient
    from worker.pipeline.media import extract_audio, probe_file
    from worker.pipeline.selection import select_clips
    from worker.pipeline.signals import build_signals
    from worker.pipeline.storage import file_lock

    source = resolve_path(expected.source, case)
    if not expected.transcript:
        raise ValueError(
            f"{case.name}: --run memerlukan transcript yang sudah ditinjau; ASR tidak dijalankan evaluator"
        )
    transcript = Transcript.model_validate_json(resolve_path(expected.transcript, case).read_text())
    digest = hashlib.sha256((checksum(source) + transcript.model_dump_json()).encode()).hexdigest()[
        :20
    ]
    directory = work_root / f"{case.name}-{digest}"
    directory.mkdir(parents=True, exist_ok=True)
    with file_lock(directory / ".eval.lock"):
        linked = directory / "source.mp4"
        if not linked.exists():
            linked.symlink_to(source.resolve())
        audio = directory / "audio.wav"
        if not audio.exists():
            extract_audio(source, audio)
        duration = probe_file(source)["duration_s"]
        signals = build_signals(directory, transcript, duration)
        select_clips(LLMClient(), transcript, signals, expected.settings, case.name, [], directory)
        result = json.loads((directory / "selection.json").read_text())
        from worker.pipeline.provenance import transcript_fingerprint

        result["provenance"] = {
            "source_sha256": checksum(source),
            "transcript_sha256": transcript_fingerprint(transcript),
        }
        return result


def resolve_path(value: str, case: Path):
    path = Path(value)
    if path.is_absolute():
        return path
    # ./ is explicitly case-relative; other paths are repository-relative.
    return case / path if value.startswith("./") else ROOT / path


def evaluate(
    root: Path,
    *,
    predictions_root: Path | None = None,
    require_predictions=False,
    run=False,
    work_root: Path | None = None,
):
    cases, errors = [], []
    for path in sorted(root.glob("*/expected.json")):
        try:
            raw = json.loads(path.read_text())
            if raw.get("annotation_status") == "draft":
                cases.append(
                    {"case": path.parent.name, "status": "not_run", "reason": "Anotasi masih draft"}
                )
                continue
            expected = (
                CondenseExpected.model_validate(raw)
                if raw.get("mode") == "condense"
                else Expected.model_validate(raw)
            )
            if expected.mode not in {"clips", "condense"} or expected.dataset_kind not in {
                "human",
                "synthetic",
            }:
                raise ValueError("mode atau dataset_kind tidak dikenal")
            source_id, verified, transcript = verify_inputs(expected, path.parent)
            result = {
                "case": path.parent.name,
                "mode": expected.mode,
                "dataset_kind": expected.dataset_kind,
                "annotator": expected.annotator,
                "independent": expected.independent,
                "source_verified": verified,
                "source_id": source_id,
            }
            prediction_path = (
                predictions_root / path.parent.name if predictions_root else path.parent
            ) / "predictions.json"
            if run:
                if expected.mode == "condense":
                    raise ValueError(
                        "Ringkas dinilai dari predictions.json hasil paket evaluasi; --run saat ini khusus Klip"
                    )
                predicted = run_case(expected, path.parent, work_root or ROOT / "data/eval")
            elif prediction_path.exists():
                predicted = json.loads(prediction_path.read_text())
            else:
                result.update(status="not_run", reason="predictions.json belum tersedia")
                cases.append(result)
                if require_predictions:
                    errors.append(f"{path.parent.name}: prediksi tidak tersedia")
                continue
            predicted = audit_predictions(predicted) if expected.mode == "clips" else predicted
            for key in ("source_sha256", "transcript_sha256"):
                gold = expected.provenance.get(key)
                claimed = predicted.get("provenance", {}).get(key)
                if gold and gold != claimed:
                    raise ValueError("Jejak sumber/transkrip prediksi tidak cocok dengan anotasi")
            if expected.mode == "clips":
                after = [Range.model_validate(r) for r in predicted["clips"]]
                result.update(after_rerank=range_metrics(expected.ranges, after))
                if "baseline_clips" in predicted:
                    before = [Range.model_validate(r) for r in predicted["baseline_clips"]]
                    result["before_rerank"] = range_metrics(expected.ranges, before)
                    result["recall_delta"] = (
                        result["after_rerank"]["recall_iou_0_5"]
                        - result["before_rerank"]["recall_iou_0_5"]
                    )
            else:
                prediction = CondensePrediction.model_validate(predicted)
                after = prediction.retained_ranges
                result.update(
                    chapter_recall=coverage_metrics(expected.required_chapters, after, 0.9),
                    spec_recall=coverage_metrics(expected.required_specs, after, 0.99),
                    duration_deviation_percent=(
                        prediction.duration_s - expected.settings.target_seconds
                    )
                    / expected.settings.target_seconds
                    * 100,
                    within_target_tolerance=abs(
                        prediction.duration_s - expected.settings.target_seconds
                    )
                    <= expected.settings.target_seconds * 0.03,
                )
            duration = expected.provenance.get("duration_s")
            labels = (
                expected.ranges
                if expected.mode == "clips"
                else [*expected.required_chapters, *expected.required_specs]
            )
            if duration and any(r.end_s > duration + 0.001 for r in [*labels, *after]):
                raise ValueError("Rentang anotasi/prediksi melebihi durasi sumber")
            result.update(status="evaluated", provider=predicted.get("provider") or "unspecified")
            excluded = []
            if expected.dataset_kind != "human":
                excluded.append("dataset_synthetic")
            if not expected.annotator.strip():
                excluded.append("annotator_missing")
            if not expected.independent:
                excluded.append("assisted_annotation")
            if not verified:
                excluded.append("source_unverified")
            if result["provider"] not in {"gemini", "anthropic", "ollama"}:
                excluded.append("provider_not_live")
            result["quality_excluded_reasons"] = excluded
            if transcript:
                result["word_boundary_check"] = {
                    "status": "checked" if transcript.words else "unavailable_sentence_only",
                    "cuts_through_words": sum(
                        any(w.start + 1e-6 < boundary < w.end - 1e-6 for w in transcript.words)
                        for clip in after
                        for boundary in (clip.start_s, clip.end_s)
                    ),
                }
            cases.append(result)
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            errors.append(f"{path}: {exc}")
    evaluated = [c for c in cases if c.get("status") == "evaluated"]
    quality = [c for c in evaluated if not c["quality_excluded_reasons"]]
    clip_quality = [c for c in quality if c["mode"] == "clips"]
    condense_quality = [c for c in quality if c["mode"] == "condense"]
    matched = sum(c["after_rerank"]["matched"] for c in clip_quality)
    total = sum(c["after_rerank"]["expected"] for c in clip_quality)
    chapter_total = sum(c["chapter_recall"]["expected"] for c in condense_quality)
    spec_total = sum(c["spec_recall"]["expected"] for c in condense_quality)
    clips_count = len({c["source_id"] for c in clip_quality})
    condense_count = len({c["source_id"] for c in condense_quality})
    return {
        "phase": 5,
        "status": "error" if errors else "evaluated" if evaluated else "not_run",
        "quality_status": "measured" if quality else "not_run",
        "quality_videos": clips_count,
        "quality_condense_videos": condense_count,
        "quality_targets_met": {"clips": clips_count >= 10, "condense": condense_count >= 5},
        "quality_recall_iou_0_5": matched / total if total else None,
        "quality_chapter_recall": sum(c["chapter_recall"]["matched"] for c in condense_quality)
        / chapter_total
        if chapter_total
        else None,
        "quality_spec_recall": sum(c["spec_recall"]["matched"] for c in condense_quality)
        / spec_total
        if spec_total
        else None,
        "note": "Target: 10 sumber Klip dan 5 sumber Ringkas unik, ditinjau manusia secara independen dengan provider nyata. Draft, assisted, sumber tidak terverifikasi, mock dan fixture sintetis tidak masuk agregat kualitas.",
        "cases": cases,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).parent / "golden")
    parser.add_argument("--predictions-root", type=Path)
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run the configured provider; default .env.example is mock",
    )
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--require-predictions", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(
        args.root,
        predictions_root=args.predictions_root,
        require_predictions=args.require_predictions,
        run=args.run,
        work_root=args.work_root,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
