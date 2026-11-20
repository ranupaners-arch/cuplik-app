"""Bounded, cached checks of the selected script; repairs always return to human review."""

import hashlib
import json
from pathlib import Path

from api.app.schemas import CoherenceCheck, CoherenceReport, OutputSettings
from worker.pipeline.llm import LLMValidationError
from worker.pipeline.selection_cache import call_stage
from worker.pipeline.solver import InfeasibleDuration, solve
from worker.pipeline.storage import atomic_json


def plan_fingerprint(beats, chapters, settings, provenance):
    return hashlib.sha256(
        json.dumps(
            {
                "version": 1,
                "provenance": provenance,
                "settings": settings.model_dump(),
                "beats": [b.model_dump() for b in sorted(beats, key=lambda b: (b.start_s, b.id))],
                "chapters": [
                    c.model_dump(exclude={"kept_s"})
                    for c in sorted(chapters, key=lambda c: c.order)
                ],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def script_windows(beats, chapters):
    ordered = sorted(beats, key=lambda b: (b.start_s, b.id))
    names = {c.id: c.title for c in chapters}
    rows = [
        {
            "id": b.id,
            "chapter": names[b.chapter_id],
            "start_s": b.start_s,
            "end_s": b.end_s,
            "kind": b.kind,
            "text": b.text,
            "visual": b.visual_desc,
            "decision": b.decision,
            "speed": b.speed,
            "locked": b.locked,
            "specs": b.evidence.get("specs", []),
        }
        for b in ordered
    ]
    groups, start, size = [], 0, 0
    for i, row in enumerate(rows):
        cost = len(json.dumps(row, ensure_ascii=False).encode())
        if cost > 16000:
            raise LLMValidationError(
                "Satu beat terlalu panjang untuk pemeriksaan koherensi; perbaiki segmentasi."
            )
        if i > start and (
            i - start >= 40 or size + cost > 16000 or row["start_s"] - rows[start]["start_s"] >= 900
        ):
            groups.append((start, i))
            start, size = i, 0
        size += cost
    if rows:
        groups.append((start, len(rows)))
    for a, b in groups:
        left, right = a, b
        budget = 4000  # Neighboring context must not make a bounded core window unbounded.
        for distance in (1, 2):
            for neighbor in (a - distance, b + distance - 1):
                if 0 <= neighbor < len(rows):
                    cost = len(json.dumps(rows[neighbor], ensure_ascii=False).encode())
                    if cost <= budget and (neighbor == left - 1 or neighbor == right):
                        left, right = min(left, neighbor), max(right, neighbor + 1)
                        budget -= cost
        yield rows[left:right], {r["id"] for r in rows[a:b]}


def validate_check(result, rows, owned):
    by_id = {r["id"]: r for r in rows}
    seen = set()
    for issue in result.issues:
        at = by_id.get(issue.at_id)
        if issue.at_id not in owned or not at or at["decision"] == "drop":
            raise LLMValidationError(
                "Masalah koherensi harus menunjuk beat terpilih dalam jendela sumber."
            )
        key = (issue.at_id, issue.type)
        if key in seen:
            raise LLMValidationError("Masalah koherensi berulang.")
        seen.add(key)
        if issue.fix == "review" and issue.restore_ids:
            raise LLMValidationError("Saran tinjauan tidak boleh menyertakan pemulihan otomatis.")
        if issue.fix == "restore" and (
            not issue.restore_ids or len(set(issue.restore_ids)) != len(issue.restore_ids)
        ):
            raise LLMValidationError("Pemulihan konteks memerlukan ID sumber unik.")
        for identifier in issue.restore_ids:
            source = by_id.get(identifier)
            if (
                not source
                or source["decision"] != "drop"
                or source["end_s"] > at["start_s"] + 0.001
            ):
                raise LLMValidationError(
                    "Konteks hanya dapat dipulihkan dari beat yang dibuang sebelum rujukannya."
                )


def check_coherence(output, beats, chapters, client, directory: Path, progress):
    settings = OutputSettings.model_validate(output.settings)
    changed = False
    restored, final_issues = [], []
    initially_kept = {b.id for b in beats if b.decision != "drop"}
    note = "Naskah lolos pemeriksaan dalam jendela sumber; tetap tinjau konteks video."
    if client.settings.llm_provider == "mock":
        note = "Fixture deterministik selesai; ini hanya pemeriksaan alur, bukan penilaian kualitas koherensi."
    minimum = None
    for turn in range(1, 3):
        progress("coherence", 0.42, f"Memeriksa koherensi naskah, putaran {turn}/2")
        issues = []
        for rows, owned in script_windows(beats, chapters):
            result = call_stage(
                client,
                "coherence_checker",
                {"script": rows, "owned_ids": sorted(owned)},
                CoherenceCheck,
                directory,
                validate=lambda r, rows=rows, owned=owned: validate_check(r, rows, owned),
            )
            issues.extend(result.issues)
        final_issues = issues
        if not issues:
            if changed:
                note = "Konteks dipulihkan dan rencana dihitung ulang. Tinjau seluruh keputusan sebelum render."
            break
        if turn == 2 or any(i.fix == "review" for i in issues):
            note = "Masih ada konteks yang perlu diperiksa manual. Perbaiki pilihan beat atau matikan pemeriksaan untuk keputusan manual."
            break
        wanted = {identifier for i in issues for identifier in i.restore_ids}
        by_id = {b.id: b for b in beats}
        if any(by_id[i].locked for i in wanted):
            note = "Konteks yang dibutuhkan terkunci sebagai dibuang. Keputusan terkunci tidak diubah; tinjau dan buka kunci jika sesuai."
            break
        copies = [b.model_copy(deep=True) for b in beats]
        for b in copies:
            if b.id in wanted:
                b.evidence = {**b.evidence, "coherence_required": True}
        try:
            plan = solve(
                copies,
                chapters,
                settings.target_seconds,
                settings.max_speech_speed,
                settings=settings,
            )
        except InfeasibleDuration as exc:
            minimum = exc.minimum_seconds
            note = f"Konteks tidak muat dalam target. Durasi minimum {minimum:.2f} detik; rencana sebelumnya dipertahankan."
            break
        choices = {p["id"]: p for p in plan["beats"]}
        for b in beats:
            if b.id in wanted:
                b.evidence = {**b.evidence, "coherence_required": True}
            b.decision, b.speed = choices[b.id]["decision"], choices[b.id]["speed"]
        restored.extend(sorted(wanted))
        changed = True
    report = CoherenceReport(
        status="needs_review" if changed or final_issues else "passed",
        provider=client.settings.llm_provider,
        model="deterministic-fixture"
        if client.settings.llm_provider == "mock"
        else client.settings.llm_model_fast,
        rounds=turn,
        plan_fingerprint=plan_fingerprint(beats, chapters, settings, output.provenance),
        issues=final_issues,
        restored_ids=sorted(set(restored)),
        dropped_ids=sorted(initially_kept - {b.id for b in beats if b.decision != "drop"}),
        note=note,
        min_duration_s=minimum,
    )
    atomic_json(directory / "coherence.json", report.model_dump())
    return report


def read_coherence_report(directory, *, output=None, beats=None, chapters=None):
    try:
        report = CoherenceReport.model_validate_json((directory / "coherence.json").read_text())
        if output is not None:
            report.stale = report.plan_fingerprint != plan_fingerprint(
                beats, chapters, OutputSettings.model_validate(output.settings), output.provenance
            )
        return report
    except (OSError, ValueError):
        return None
