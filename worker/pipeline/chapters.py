"""Chapter packages use encoded segment timings; publication text is validated separately."""

import math
from pathlib import Path

from api.app.models import Chapter
from api.app.schemas import ChapterExport, ChapterMarker
from worker.pipeline.storage import atomic_json


def timestamp(seconds: float, *, milliseconds=False) -> str:
    ticks = round(seconds * 1000) if milliseconds else math.floor(seconds + 1e-6) * 1000
    whole = ticks // 1000
    prefix = (
        f"{whole // 3600:02d}:{whole // 60 % 60:02d}:{whole % 60:02d}"
        if whole >= 3600
        else f"{whole // 60:02d}:{whole % 60:02d}"
    )
    return f"{prefix}.{ticks % 1000:03d}" if milliseconds else prefix


def build_chapter_export(timeline: dict, chapters: list[Chapter]) -> ChapterExport:
    by_id = {c.id: c for c in chapters}
    markers = []
    for span in timeline["spans"]:
        chapter = by_id[span["chapter_id"]]
        start, end = span["output_start_s"], span["output_end_s"]
        if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end:
            raise ValueError("Garis waktu bab tidak valid")
        if markers and markers[-1].chapter_id == chapter.id:
            markers[-1].end_s = end
        else:
            markers.append(
                ChapterMarker(
                    chapter_id=chapter.id,
                    title=" ".join(chapter.title.split()) or f"Bab {len(markers) + 1}",
                    start_s=start,
                    end_s=end,
                    timestamp=timestamp(start),
                )
            )
    duration = timeline["duration_s"]
    reasons = []
    if len(markers) < 3:
        reasons.append("YouTube membutuhkan minimal tiga bab.")
    if not markers or abs(markers[0].start_s) > 1e-6:
        reasons.append("Bab pertama harus dimulai pada 00:00.")
    starts = [math.floor(m.start_s + 1e-6) for m in markers]
    if any(b <= a for a, b in zip(starts, starts[1:], strict=False)):
        reasons.append("Timestamp dalam detik harus berurutan tanpa duplikasi.")
    if any(m.end_s - m.start_s < 10 - 1e-6 for m in markers) or (
        markers and duration - starts[-1] < 10 - 1e-6
    ):
        reasons.append("Setiap bab, termasuk bab terakhir, harus berdurasi minimal 10 detik.")
    if abs(timeline.get("duration_drift_s", 0)) > 0.1:
        reasons.append(
            "Selisih durasi segmen dan file akhir melebihi 100 ms; waktu bab perlu ditinjau."
        )
    youtube_text = (
        "\n".join(f"{m.timestamp} {m.title}" for m in markers) + "\n" if not reasons else None
    )
    return ChapterExport(
        timing_source="encoded_parts",
        duration_s=duration,
        chapters=markers,
        youtube_valid=not reasons,
        reasons=reasons,
        youtube_text=youtube_text,
        index_text="\n".join(
            f"{timestamp(m.start_s, milliseconds=True)} {m.title}" for m in markers
        )
        + "\n",
    )


def write_chapter_export(directory: Path, chapters: list[Chapter]) -> ChapterExport:
    import json

    timeline = json.loads((directory / "condensed.timeline.json").read_text())
    report = build_chapter_export(timeline, chapters)
    (directory / "chapters.txt").write_text(report.index_text, encoding="utf-8")
    youtube = directory / "youtube-chapters.txt"
    if report.youtube_valid:
        youtube.write_text(report.youtube_text, encoding="utf-8")
    else:
        youtube.unlink(missing_ok=True)
    atomic_json(directory / "chapters.json", report.model_dump())
    return report


def read_chapter_export(directory: Path, duration: float) -> ChapterExport:
    path = directory / "chapters.json"
    if path.exists():
        return ChapterExport.model_validate_json(path.read_text())
    index = directory / "chapters.txt"
    return ChapterExport(
        timing_source="legacy_plan",
        duration_s=duration,
        index_text=index.read_text() if index.exists() else "",
        reasons=[
            "Indeks bab lama masih memakai durasi rencana dan belum diverifikasi terhadap segmen hasil render."
        ],
    )
