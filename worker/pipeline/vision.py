"""Opt-in multimodal evidence and ID-only chapter planning for Ringkas."""

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Literal

import cv2
from pydantic import Field

from api.app.schemas import (
    CondenseVisionSettings,
    FrameDescription,
    StrictModel,
    VisionFrame,
    VisionReport,
)
from worker.pipeline.beats import analyze_motion, build_beats, frame_schedule
from worker.pipeline.llm import LLMImage, LLMValidationError
from worker.pipeline.media import MediaError
from worker.pipeline.selection_cache import call_stage
from worker.pipeline.storage import atomic_json, json_object, output_dir

VALUES = {
    "step": 1,
    "spec": 1,
    "result": 0.9,
    "why": 0.6,
    "manual": 0.4,
    "repeat": 0.2,
    "mistake": 0.1,
    "chatter": 0.1,
    "idle": 0.05,
    "meta": 0,
}


class FrameDescriptions(StrictModel):
    frames: list[FrameDescription] = Field(min_length=1, max_length=16)


class BeatAnnotation(StrictModel):
    id: str
    label: Literal[
        "step", "spec", "result", "why", "manual", "repeat", "mistake", "chatter", "idle", "meta"
    ]
    step_hint: str = Field(max_length=120)
    specs: list[str] = Field(default_factory=list, max_length=16)
    refers_back: bool = False
    uncertain: bool = True


class BeatAnnotations(StrictModel):
    beats: list[BeatAnnotation] = Field(min_length=1, max_length=200)


class BeatChapter(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(max_length=1000)
    start_id: str
    end_id: str
    required_beat_ids: list[str]
    importance: Literal["core", "helpful", "optional"]


class BeatOutline(StrictModel):
    chapters: list[BeatChapter] = Field(min_length=1, max_length=50)


def exact_ids(items, expected):
    actual = [i.id for i in items]
    if len(actual) != len(expected) or set(actual) != set(expected):
        raise LLMValidationError("Respons vision/anotasi harus mencakup setiap ID tepat satu kali.")


def extract_frames(
    source: Path, schedule: list[dict], width: int, directory: Path, provenance, bounds
):
    key = hashlib.sha256(
        json.dumps(
            {"version": 1, "width": width, "schedule": schedule, **provenance}, sort_keys=True
        ).encode()
    ).hexdigest()[:24]
    samples = directory / "vision-samples" / key
    images = directory / "vision-frames"
    samples.mkdir(parents=True, exist_ok=True)
    images.mkdir(exist_ok=True)
    capture = cv2.VideoCapture(str(source))
    result = []
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not capture.isOpened() or not math.isfinite(fps) or fps <= 0:
            raise MediaError("Video tidak dapat dibuka untuk sampling vision.")
        for item in schedule:
            cache = samples / f"{item['id']}.json"
            meta = json_object(cache)
            try:
                digest = meta["image_sha256"]
                if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                    raise ValueError("bad image digest")
                data = (images / f"{digest}.jpg").read_bytes()
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError("changed image")
                if (
                    meta["id"] != item["id"]
                    or meta["beat_id"] != item["beat_id"]
                    or abs(meta["time_s"] - item["time_s"]) > max(0.15, 2 / fps)
                ):
                    raise ValueError("changed sample metadata")
                VisionFrame.model_validate({**meta, "action": "cache", "url": "cache"})
                start, end = bounds[item["beat_id"]]
                if not start <= meta["time_s"] < end:
                    raise ValueError("sample outside beat")
            except (OSError, ValueError, KeyError, TypeError):
                capture.set(cv2.CAP_PROP_POS_MSEC, item["time_s"] * 1000)
                ok, frame = capture.read()
                if not ok:
                    raise MediaError(
                        "Frame vision gagal dibaca; tidak ada gambar rekaan dikirim."
                    ) from None
                actual = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if actual <= 0 and item["time_s"] > 1 / fps:
                    actual = (capture.get(cv2.CAP_PROP_POS_FRAMES) - 1) / fps
                if not math.isfinite(actual) or abs(actual - item["time_s"]) > max(0.15, 2 / fps):
                    raise MediaError(
                        "Timestamp frame vision tidak cocok dengan waktu sumber."
                    ) from None
                start, end = bounds[item["beat_id"]]
                if not start <= actual < end:
                    raise MediaError(
                        "Frame tidak berada dalam rentang beat; periksa timestamp transkrip."
                    ) from None
                h, w = frame.shape[:2]
                factor = min(1, width / w, 1024 / h)
                frame = cv2.resize(frame, (max(1, round(w * factor)), max(1, round(h * factor))))
                ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    raise MediaError("Frame vision gagal dienkode.") from None
                data = encoded.tobytes()
                digest = hashlib.sha256(data).hexdigest()
                temporary = images / f"{digest}.tmp"
                temporary.write_bytes(data)
                temporary.replace(images / f"{digest}.jpg")
                meta = {
                    **item,
                    "time_s": actual,
                    "width": frame.shape[1],
                    "height": frame.shape[0],
                    "image_sha256": digest,
                }
                atomic_json(cache, meta)
            result.append(meta)
    finally:
        capture.release()
    return result


def image_payload(directory, frame):
    data = (directory / "vision-frames" / f"{frame['image_sha256']}.jpg").read_bytes()
    if hashlib.sha256(data).hexdigest() != frame["image_sha256"]:
        raise MediaError("Gambar cache vision berubah; coba ulang untuk memulihkan sampel.")
    return LLMImage(frame["id"], data)


def validate_annotations(result, batch):
    exact_ids(result.beats, [b["id"] for b in batch])
    by_id = {b["id"]: b for b in batch}
    for annotation in result.beats:
        evidence = by_id[annotation.id]
        raw = " ".join([evidence["text"], *(f["screen_text"] for f in evidence["frames"])])
        normalized = " ".join(raw.casefold().split())
        if annotation.label == "spec" and not annotation.specs:
            raise LLMValidationError("Beat spec harus menyertakan nilai verbatim dari sumber.")
        for spec in annotation.specs:
            value = " ".join(spec.casefold().split())
            if (
                not value
                or len(spec) > 200
                or not re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", normalized)
            ):
                raise LLMValidationError(
                    "Angka/setelan anotasi tidak muncul verbatim dalam bukti beat."
                )


def validate_beat_outline(plan, beats):
    positions = {b.id: i for i, b in enumerate(beats)}
    expected, result = 0, []
    for chapter in plan.chapters:
        a, b = positions.get(chapter.start_id), positions.get(chapter.end_id)
        if a is None or b is None or a != expected or b < a:
            raise LLMValidationError(
                "Bab visual harus berurutan dan mencakup semua beat tanpa tumpang tindih."
            )
        members = beats[a : b + 1]
        required = chapter.required_beat_ids
        if len(set(required)) != len(required) or not set(required).issubset(
            {m.id for m in members}
        ):
            raise LLMValidationError("ID beat wajib berada di luar bab atau berulang.")
        result.append((chapter, members))
        expected = b + 1
    if expected != len(beats):
        raise LLMValidationError("Outline visual belum mencakup semua beat.")
    return result


def plan_visual_outline(output, source, transcript, duration, client, progress):
    directory = output_dir(output.id)
    settings = CondenseVisionSettings.model_validate(output.settings.get("condense_vision", {}))
    progress("visual_beats", 0.12, "Memetakan perubahan gambar dan jeda di luar kalimat")
    beats = build_beats(transcript, duration, analyze_motion(source.parent, duration))
    schedule = frame_schedule(beats, settings.max_frames)
    metadata = extract_frames(
        source,
        schedule,
        1024 if settings.screen_tutorial else 512,
        directory,
        output.provenance,
        {b.id: (b.start_s, b.end_s) for b in beats},
    )
    descriptions = {}
    model = client.settings.llm_model_vision or client.settings.llm_model_fast
    batch_size = 8 if settings.screen_tutorial else 16
    for start in range(0, len(metadata), batch_size):
        batch = metadata[start : start + batch_size]
        progress(
            "vision",
            0.16 + 0.12 * start / len(metadata),
            f"Mendeskripsikan frame {start + 1}–{start + len(batch)} dari {len(metadata)}",
        )
        result = call_stage(
            client,
            "frame_describer",
            {"frames": batch, "language": transcript.language},
            FrameDescriptions,
            directory,
            images=[image_payload(directory, f) for f in batch],
            model=model,
            validate=lambda r, batch=batch: exact_ids(r.frames, [f["id"] for f in batch]),
        )
        descriptions.update({f.id: f for f in result.frames})
    frames = [
        VisionFrame(
            **meta,
            **descriptions[meta["id"]].model_dump(exclude={"id"}),
            url=f"/api/outputs/{output.id}/vision/frames/{meta['id']}",
        )
        for meta in metadata
    ]
    per_beat = {b.id: [] for b in beats}
    for frame in frames:
        per_beat[frame.beat_id].append(frame)
    annotated, batches, batch_bytes = {}, [], 0
    for beat in beats:
        row = {
            **beat.model_dump(),
            "frames": [f.model_dump(exclude={"url", "image_sha256"}) for f in per_beat[beat.id]],
        }
        size = len(json.dumps(row, ensure_ascii=False).encode())
        if size > 16000:
            raise LLMValidationError(
                f"Bukti {beat.id} terlalu panjang untuk satu batch anotasi. Periksa segmentasi transkrip."
            )
        if (
            not batches
            or len(batches[-1]) >= 40
            or batch_bytes + size > 16000
            or int(beat.start_s // 900) != int(batches[-1][0]["start_s"] // 900)
        ):
            batches.append([])
            batch_bytes = 0
        batches[-1].append(row)
        batch_bytes += size
    for batch in batches:
        progress("annotate", 0.3, "Mengaitkan instruksi, spesifikasi dan hasil dengan beat sumber")
        result = call_stage(
            client,
            "beat_annotator",
            {"beats": batch, "focus": output.settings.get("focus", "")},
            BeatAnnotations,
            directory,
            validate=lambda r, batch=batch: validate_annotations(r, batch),
        )
        annotated.update({b.id: b for b in result.beats})
    variables = {
        "beats": [
            {
                "id": b.id,
                "kind": b.kind,
                "text": " ".join(b.text.split()[:12]),
                **annotated[b.id].model_dump(exclude={"id"}),
            }
            for b in beats
        ],
        "focus": output.settings.get("focus", ""),
        "language": transcript.language,
    }
    plan = call_stage(
        client,
        "outline_builder",
        variables,
        BeatOutline,
        directory,
        validate=lambda r: validate_beat_outline(r, beats),
    )
    report = VisionReport(
        provider=client.settings.llm_provider,
        vision_model="deterministic-fixture" if client.settings.llm_provider == "mock" else model,
        **output.provenance,
        speech_beats=sum(b.kind == "speech" for b in beats),
        visual_beats=sum(b.kind == "visual" for b in beats),
        frame_count=len(frames),
        frames=frames,
        notes=[
            "Jeda visual berasal dari rentang tanpa kalimat transkrip; belum membuktikan audio tanpa suara.",
            "Aktivitas lokal 2 fps hanya petunjuk gerakan; deskripsi/objek berasal dari provider dan perlu ditinjau.",
            "Sampling dapat melewatkan aksi singkat. Tonton rentang sumber sebelum menyetujui bab.",
            *(
                ["Deskripsi mock adalah fixture, bukan pengenalan gambar nyata."]
                if client.settings.llm_provider == "mock"
                else []
            ),
        ],
    )
    return validate_beat_outline(plan, beats), annotated, per_beat, report


def read_vision_report(directory: Path) -> VisionReport | None:
    try:
        return VisionReport.model_validate_json((directory / "vision.json").read_text())
    except (OSError, ValueError):
        return None
