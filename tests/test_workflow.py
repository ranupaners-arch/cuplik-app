import json
import zipfile

import pytest

from api.app.config import get_settings
from worker.pipeline.media import probe_file
from worker.pipeline.storage import project_dir
from worker.runner import run_output


def make_output(client, project, mode="clips", **settings):
    response = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={"mode": mode, "settings": {"clip_count": 1, **settings}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_clips_render_download_edit_and_retry_from_cache(client, project, monkeypatch):
    output_id = make_output(client, project)
    original = __import__("worker.runner", fromlist=["render_clip"]).render_clip
    monkeypatch.setattr(
        "worker.runner.render_clip",
        lambda *_: (_ for _ in ()).throw(RuntimeError("uji render gagal")),
    )
    with pytest.raises(RuntimeError, match="uji render gagal"):
        run_output(output_id)
    detail = client.get(f"/api/outputs/{output_id}").json()
    assert detail["output"]["status"] == "failed"
    source = project_dir(project["id"]) / "source.mp4"
    transcript = source.parent / "transcript.json"
    mtimes = (source.stat().st_mtime_ns, transcript.stat().st_mtime_ns)
    log = get_settings().storage / "outputs" / output_id / "llm_log.jsonl"
    original_log = log.read_text()
    monkeypatch.setattr("worker.runner.render_clip", original)
    assert client.post(f"/api/outputs/{output_id}/retry").status_code == 202
    run_output(output_id)
    detail = client.get(f"/api/outputs/{output_id}").json()
    assert detail["output"]["status"] == "done"
    assert mtimes == (source.stat().st_mtime_ns, transcript.stat().st_mtime_ns)
    assert original_log == log.read_text(), "Retry must reuse the accepted clip plan"
    clip = detail["clips"][0]
    downloaded = client.get(clip["file_url"])
    assert downloaded.status_code == 200 and downloaded.content[4:8] == b"ftyp"
    assert client.get(clip["file_url"], headers={"Range": "bytes=0-99"}).status_code == 206
    archive = client.get(f"/api/outputs/{output_id}/export.zip")
    import io

    with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
        assert {"metadata.json", "captions.txt", f"{clip['id']}.mp4"} <= set(zipped.namelist())
    assert (
        client.patch(
            f"/api/clips/{clip['id']}", json={"caption_overrides": {"s999": "rekaan"}}
        ).status_code
        == 422
    )
    updated = client.patch(
        f"/api/clips/{clip['id']}",
        json={"hook_choice": 1, "caption_overrides": {"s1": "Caption diperbaiki"}},
    )
    assert updated.status_code == 200 and updated.json()["needs_render"]
    assert client.get(clip["file_url"]).status_code == 409
    assert client.post(f"/api/clips/{clip['id']}/render").status_code == 202
    assert client.patch(f"/api/clips/{clip['id']}", json={"hook_choice": 0}).status_code == 409
    run_output(output_id, clip_id=clip["id"])
    refreshed = client.get(f"/api/outputs/{output_id}").json()["clips"][0]
    assert not refreshed["needs_render"]
    assert refreshed["render_fingerprint"] != clip["render_fingerprint"]
    assert client.patch(f"/api/clips/{clip['id']}", json={"rating": "up"}).json()["rating"] == "up"


def test_condense_review_infeasible_target_locked_beats_and_render(client, project):
    output_id = make_output(client, project, "condense", target_seconds=8)
    run_output(output_id)
    detail = client.get(f"/api/outputs/{output_id}").json()
    assert detail["output"]["status"] == "awaiting_review"
    assert client.get(f"/api/outputs/{output_id}/chapters").status_code == 409
    assert not (get_settings().storage / "outputs" / output_id / "condensed.mp4").exists()
    chapters = [{"id": c["id"], "required": True} for c in detail["chapters"]]
    response = client.put(
        f"/api/outputs/{output_id}/outline", json={"chapters": chapters, "target_seconds": 3}
    )
    assert response.status_code == 409 and response.json()["detail"]["min_duration_s"] > 3
    assert client.get(f"/api/outputs/{output_id}").json()["output"]["status"] == "awaiting_review"
    required = next(b for b in detail["beats"] if b["required"])
    optional = next(b for b in detail["beats"] if not b["required"])
    assert (
        client.patch(f"/api/beats/{required['id']}", json={"decision": "drop"}).status_code == 409
    )
    assert (
        client.patch(f"/api/beats/{optional['id']}", json={"decision": "drop"}).status_code == 200
    )
    preview = client.post(f"/api/outputs/{output_id}/solve", json={"target_seconds": 8})
    assert preview.status_code == 200 and preview.json()["within_tolerance"]
    assert (
        next(b for b in preview.json()["beats"] if b["id"] == optional["id"])["decision"] == "drop"
    )
    accepted = client.put(
        f"/api/outputs/{output_id}/outline", json={"chapters": chapters, "target_seconds": 8}
    )
    assert accepted.status_code == 202, accepted.text
    assert (
        client.put(
            f"/api/outputs/{output_id}/outline", json={"chapters": chapters, "target_seconds": 8}
        ).status_code
        == 409
    )
    run_output(output_id, render_only=True)
    assert client.get(f"/api/outputs/{output_id}").json()["output"]["status"] == "done"
    assert client.get(f"/api/outputs/{output_id}/file").status_code == 200
    actual = probe_file(get_settings().storage / "outputs" / output_id / "condensed.mp4")[
        "duration_s"
    ]
    assert abs(actual - 8) < 0.4
    detail = client.get(f"/api/outputs/{output_id}").json()
    package = detail["chapter_export"]
    assert package["timing_source"] == "encoded_parts"
    assert package["duration_s"] == actual
    assert not package["youtube_valid"]
    assert client.get(f"/api/outputs/{output_id}/chapters.txt").status_code == 200
    assert client.get(f"/api/outputs/{output_id}/chapters.txt?format=youtube").status_code == 409
    import io

    with zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/outputs/{output_id}/export.zip").content)
    ) as archive:
        assert {"condensed.mp4", "chapters.txt", "chapters.json", "condensed.timeline.json"} <= set(
            archive.namelist()
        )
        assert "youtube-chapters.txt" not in archive.namelist()
        timeline = json.loads(archive.read("condensed.timeline.json"))
        assert timeline["spans"][0]["output_start_s"] == 0
        assert timeline["spans"][-1]["output_end_s"] == actual


def test_sse_replay_after_terminal_and_reconnect_cursor(client, project):
    output_id = make_output(client, project, "condense")
    run_output(output_id)
    stream = client.get(f"/api/outputs/{output_id}/events")
    assert stream.status_code == 200
    ids = [int(line[4:]) for line in stream.text.splitlines() if line.startswith("id: ")]
    assert len(ids) >= 3 and ids == sorted(set(ids))
    assert "awaiting_review" in stream.text
    replay = client.get(f"/api/outputs/{output_id}/events", headers={"Last-Event-ID": str(ids[-2])})
    assert [int(line[4:]) for line in replay.text.splitlines() if line.startswith("id: ")] == [
        ids[-1]
    ]
    assert (
        client.get(f"/api/outputs/{output_id}/events", headers={"Last-Event-ID": "bad"}).status_code
        == 400
    )


def test_upload_resumes_and_rejects_wrong_offsets_and_invalid_media(client, video):
    data = video.read_bytes()
    upload = client.post(
        "/api/uploads", json={"filename": "../source.mp4", "total_bytes": len(data)}
    ).json()
    path = f"/api/uploads/{upload['id']}"
    half = len(data) // 2
    assert client.put(path + "?offset=0", content=data[:half]).json()["offset"] == half
    assert client.get(path).json()["offset"] == half
    assert client.put(path + "?offset=0", content=data[half:]).status_code == 409
    assert (
        client.post(
            "/api/projects", json={"source_kind": "upload", "upload_id": upload["id"]}
        ).status_code
        == 409
    )
    assert client.put(path + f"?offset={half}", content=data[half:]).json()["complete"]
    invalid = client.post("/api/uploads", json={"filename": "bad.mp4", "total_bytes": 4}).json()
    assert client.put(f"/api/uploads/{invalid['id']}?offset=0", content=b"nope").status_code == 422
    assert client.get(f"/api/uploads/{invalid['id']}").json()["offset"] == 0


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "https://youtube.com.evil.test/watch?v=x",
        "https://www.youtube.com/playlist?list=x",
        "https://www.youtube.com/watch?v=x&list=y",
        "file:///etc/passwd",
        "https://youtube.com:abc/watch?v=x",
    ],
)
def test_reject_unexpected_source_urls(client, url):
    assert client.post("/api/probe", json={"url": url}).status_code == 422


def test_sample_llm_reports_mock_and_config_never_exposes_keys(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-test-key")
    get_settings.cache_clear()
    config = client.get("/api/config")
    assert "secret-test-key" not in config.text
    result = client.post("/api/llm/sample", json={"focus": "pencatatan"})
    assert result.status_code == 200
    assert result.json()["provider"] == "mock" and len(result.json()["result"]["candidates"]) == 3


def test_queue_failure_is_durable_and_retryable(client, project, monkeypatch):
    def unavailable():
        raise ConnectionError("test")

    monkeypatch.setattr("api.app.jobs.queue", unavailable)
    response = client.post(f"/api/projects/{project['id']}/outputs", json={"mode": "clips"})
    assert response.status_code == 201
    history = client.get(f"/api/projects/{project['id']}").json()
    assert history["outputs"][0]["status"] == "queued"
    from sqlmodel import Session, select

    from api.app.db import get_engine
    from api.app.models import Task

    with Session(get_engine()) as session:
        task = session.exec(select(Task).where(Task.subject_id == response.json()["id"])).one()
        assert task.state == "pending"


def test_transcript_rejects_overlap_duplicate_ids_and_nonfinite_values(client, transcript):
    bad = json.loads(json.dumps(transcript))
    bad["sentences"][1]["start"] = 1
    assert (
        client.post(
            "/api/projects",
            json={"source_kind": "url", "url": "https://youtu.be/example", "transcript": bad},
        ).status_code
        == 422
    )
    bad = json.loads(json.dumps(transcript))
    bad["sentences"][1]["id"] = "s1"
    assert (
        client.post(
            "/api/projects",
            json={"source_kind": "url", "url": "https://youtu.be/example", "transcript": bad},
        ).status_code
        == 422
    )
