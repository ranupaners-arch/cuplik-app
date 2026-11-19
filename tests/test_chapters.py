import io
import zipfile

import pytest
from sqlmodel import Session

from api.app.db import get_engine
from api.app.models import Chapter, Output
from worker.pipeline.chapters import build_chapter_export, timestamp, write_chapter_export
from worker.pipeline.storage import atomic_json, output_dir


def chapter(identifier, order, title):
    return Chapter(
        id=identifier, output_id="test", order=order, title=title, goal="Tujuan", kept_s=100
    )


def timeline(durations, *, offset=0, drift=0):
    elapsed, spans = offset, []
    for i, duration in enumerate(durations):
        spans.append(
            {
                "chapter_id": f"c{i + 1}",
                "output_start_s": elapsed,
                "output_end_s": elapsed + duration,
            }
        )
        elapsed += duration
    return {"duration_s": elapsed, "duration_drift_s": drift, "spans": spans}


def test_chapters_follow_encoded_parts_instead_of_planned_duration_and_skip_dropped_chapter():
    chapters = [
        chapter("c1", 0, "Langkah pertama\n00:01 sisipan"),
        chapter("dropped", 1, "Dibuang"),
        chapter("c2", 2, "Praktik"),
        chapter("c3", 3, "Hasil"),
    ]
    report = build_chapter_export(timeline([10.2, 10.4, 10.1]), chapters)
    assert report.youtube_valid
    assert [c.chapter_id for c in report.chapters] == ["c1", "c2", "c3"]
    assert report.chapters[1].start_s == pytest.approx(10.2)
    assert report.chapters[2].start_s == pytest.approx(20.6)
    assert report.chapters[0].title == "Langkah pertama 00:01 sisipan"
    assert (
        report.youtube_text == "00:00 Langkah pertama 00:01 sisipan\n00:10 Praktik\n00:20 Hasil\n"
    )
    assert "00:10.200 Praktik" in report.index_text
    assert report.duration_s == pytest.approx(30.7)


@pytest.mark.parametrize(
    "durations,offset,drift,reason",
    [
        ([12, 12], 0, 0, "minimal tiga"),
        ([10, 10, 9.9], 0, 0, "bab terakhir"),
        ([0.4, 10, 10], 0, 0, "duplikasi"),
        ([10, 10, 10], 1, 0, "00:00"),
        ([10, 10, 10], 0, 0.2, "100 ms"),
    ],
)
def test_invalid_publication_format_keeps_review_index(durations, offset, drift, reason):
    chapters = [chapter(f"c{i + 1}", i, f"Bab {i + 1}") for i in range(len(durations))]
    report = build_chapter_export(timeline(durations, offset=offset, drift=drift), chapters)
    assert not report.youtube_valid and report.youtube_text is None
    assert report.index_text
    assert any(reason in message for message in report.reasons)


def test_timestamp_hour_rollover_and_adjacent_beats_share_one_chapter():
    assert timestamp(3661.95) == "01:01:01"
    assert timestamp(3599.9996, milliseconds=True) == "01:00:00.000"
    source = timeline([12, 12, 12, 12])
    source["spans"][1]["chapter_id"] = "c1"
    report = build_chapter_export(
        source, [chapter(f"c{i + 1}", i, f"Bab {i + 1}") for i in range(4)]
    )
    assert report.youtube_valid
    assert len(report.chapters) == 3 and report.chapters[0].end_s == 24


def test_ready_download_and_archive_include_validated_youtube_text(client, project):
    # Contract fixture: timings are synthetic; actual encoding is covered by the workflow test.
    with Session(get_engine()) as session:
        output = Output(
            project_id=project["id"], mode="condense", status="done", actual_duration_s=36
        )
        session.add(output)
        session.commit()
        session.refresh(output)
        identifier = output.id
    directory = output_dir(identifier)
    chapters = [chapter(f"c{i + 1}", i, f"Bab {i + 1}") for i in range(3)]
    atomic_json(directory / "condensed.timeline.json", timeline([12, 12, 12]))
    report = write_chapter_export(directory, chapters)
    response = client.get(f"/api/outputs/{identifier}/chapters.txt?format=youtube")
    assert response.status_code == 200 and response.text == report.youtube_text
    assert response.headers["content-type"].startswith("text/plain")
    assert 'filename="youtube-chapters.txt"' in response.headers["content-disposition"]
    assert client.get(f"/api/outputs/{identifier}/chapters").json()["youtube_valid"]
    (directory / "condensed.mp4").write_bytes(b"synthetic-contract-fixture")
    with zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/outputs/{identifier}/export.zip").content)
    ) as archive:
        assert {
            "condensed.mp4",
            "chapters.txt",
            "chapters.json",
            "youtube-chapters.txt",
            "condensed.timeline.json",
        } <= set(archive.namelist())
        assert "captions.txt" not in archive.namelist()
        assert archive.read("youtube-chapters.txt").decode() == report.youtube_text
    # A later shorter package must not leave a stale publication file behind.
    atomic_json(directory / "condensed.timeline.json", timeline([4, 4, 4]))
    write_chapter_export(directory, chapters)
    assert not (directory / "youtube-chapters.txt").exists()
    assert client.get(f"/api/outputs/{identifier}/chapters.txt?format=youtube").status_code == 409


def test_legacy_outputs_keep_index_without_claiming_verified_timings(client, project):
    with Session(get_engine()) as session:
        output = Output(
            project_id=project["id"], mode="condense", status="done", actual_duration_s=12
        )
        session.add(output)
        session.commit()
        session.refresh(output)
        identifier = output.id
    directory = output_dir(identifier)
    (directory / "chapters.txt").write_text("00:00 Bab lama\n")
    result = client.get(f"/api/outputs/{identifier}/chapters").json()
    assert result["timing_source"] == "legacy_plan" and not result["youtube_valid"]
    assert client.get(f"/api/outputs/{identifier}/chapters.txt").text == "00:00 Bab lama\n"
    assert client.get(f"/api/outputs/{identifier}/chapters.txt?format=youtube").status_code == 409
    assert not (directory / "chapters.json").exists(), (
        "Reading legacy results must not rewrite them"
    )
