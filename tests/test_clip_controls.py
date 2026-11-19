import hashlib
import os
import time
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from api.app.config import get_settings
from api.app.db import get_engine
from api.app.models import Clip, Task
from api.app.schemas import Transcript
from worker.pipeline.captions import timed_tokens
from worker.pipeline.cleanup import cleanup_sources
from worker.pipeline.delivery import inspect_delivery
from worker.pipeline.ingest import ingest_project
from worker.pipeline.retention import build_edl
from worker.pipeline.selection import liked_examples
from worker.pipeline.storage import file_lock, output_dir, project_dir
from worker.runner import run_output


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_short_format_uses_final_file_duration_instead_of_edit_tolerance():
    clip = SimpleNamespace(platform="youtube_shorts", purpose="tutorial", layout="auto")
    framing = SimpleNamespace(width=1080, height=1920, content_kind="speaker")
    assert inspect_delivery(clip, framing, 180)["format_valid"]
    assert not inspect_delivery(clip, framing, 180.05)["format_valid"]


@pytest.fixture
def word_project(client, video):
    entries = [
        (0.2, 0.6, "Pisahkan"),
        (0.8, 1.2, "uang"),
        (2.5, 3.2, "usaha."),
        (4.2, 4.6, "Catat"),
        (4.8, 5.2, "setiap"),
        (7.0, 7.8, "transaksi."),
        (8.2, 8.7, "Tinjau"),
        (10.6, 11.3, "hasil."),
    ]
    words = [
        {"id": f"w{i + 1}", "start": a, "end": b, "text": text}
        for i, (a, b, text) in enumerate(entries)
    ]
    sentences = []
    for i, selected in enumerate([words[:3], words[3:6], words[6:]]):
        sentences.append(
            {
                "id": f"s{i + 1}",
                "start": selected[0]["start"],
                "end": selected[-1]["end"],
                "text": " ".join(w["text"] for w in selected),
                "word_ids": [w["id"] for w in selected],
            }
        )
    data = video.read_bytes()
    upload = client.post(
        "/api/uploads", json={"filename": "words.mp4", "total_bytes": len(data)}
    ).json()
    client.put(f"/api/uploads/{upload['id']}?offset=0", content=data).raise_for_status()
    response = client.post(
        "/api/projects",
        json={
            "source_kind": "upload",
            "upload_id": upload["id"],
            "transcript": {"language": "id", "sentences": sentences, "words": words},
        },
    )
    response.raise_for_status()
    return response.json()


def test_preferences_persist_per_mode_merge_explicit_fields_and_do_not_change_old_outputs(
    client, project
):
    defaults = client.get("/api/preferences").json()
    assert defaults["clips"]["purpose"] == "tutorial"
    assert not defaults["clips"]["retention"]["shorten_pauses"]
    before = client.post(f"/api/projects/{project['id']}/outputs", json={"mode": "clips"}).json()
    defaults["caption_preset"] = "karaoke"
    defaults["clips"].update(clip_count=4, max_clip_seconds=90, platform="youtube_shorts")
    defaults["condense"].update(target_seconds=25, max_speech_speed=1.08, captions=False)
    assert client.put("/api/preferences", json=defaults).status_code == 200
    assert client.get("/api/preferences").json()["clips"]["retention"]["karaoke"]
    output = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={"mode": "clips", "settings": {"min_clip_seconds": 70, "retention": {"emoji": True}}},
    )
    assert output.status_code == 201, output.text
    saved = output.json()["settings"]
    assert saved["clip_count"] == 4 and saved["max_clip_seconds"] == 90
    assert saved["retention"]["emoji"] and saved["retention"]["karaoke"]
    assert not saved["retention"]["shorten_pauses"]
    condensed = client.post(
        f"/api/projects/{project['id']}/outputs", json={"mode": "condense"}
    ).json()
    assert condensed["settings"]["target_seconds"] == 25
    assert not condensed["settings"]["captions"]
    old = client.get(f"/api/outputs/{before['id']}").json()["output"]
    assert old["settings"] == before["settings"]
    defaults["clips"]["min_clip_seconds"] = 100
    assert client.put("/api/preferences", json=defaults).status_code == 422
    assert client.get("/api/preferences").json()["clips"]["min_clip_seconds"] == 3
    assert (
        client.post(
            f"/api/projects/{project['id']}/outputs",
            json={"mode": "clips", "settings": {"layout": "source"}},
        ).status_code
        == 422
    )


def test_word_edit_trim_single_clip_rerender_and_rating_keep_source_clock_and_cache(
    client, word_project, monkeypatch
):
    project = word_project
    response = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={"mode": "clips", "settings": {"clip_count": 2, "max_clip_seconds": 4}},
    )
    response.raise_for_status()
    identifier = response.json()["id"]
    run_output(identifier)
    detail = client.get(f"/api/outputs/{identifier}").json()
    first = next(c for c in detail["clips"] if c["start_s"] < 1)
    other = next(c for c in detail["clips"] if c["id"] != first["id"])
    assert not first["retention"]["shorten_pauses"]
    directory = output_dir(identifier)
    other_video = directory / f"{other['id']}.mp4"
    other_stamp = (digest(other_video), other_video.stat().st_mtime_ns)
    source, transcript_path = (
        project_dir(project["id"]) / "source.mp4",
        project_dir(project["id"]) / "transcript.json",
    )
    originals = (
        source.stat().st_mtime_ns,
        digest(transcript_path),
        digest(directory / "llm_log.jsonl"),
    )
    changed = client.patch(
        f"/api/clips/{first['id']}",
        json={
            "start_s": 0.34,
            "end_s": 3.1,
            "caption_overrides": {"w2": "modal"},
            "platform": "youtube_shorts",
            "retention": {"karaoke": True},
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["start_s"] == 0.2 and changed.json()["end_s"] == 3.2
    assert changed.json()["needs_render"]
    assert client.get(first["file_url"]).status_code == 409
    with Session(get_engine()) as session:
        clip = session.get(Clip, first["id"])
        transcript = Transcript.model_validate_json(transcript_path.read_text())
        tokens = timed_tokens(clip, transcript)
        token = next(t for t in tokens if t.word_id == "w2")
        assert token.text == "modal" and not token.estimated
        assert token.start == pytest.approx(0.6) and token.end == pytest.approx(1.0)
        assert build_edl(clip, transcript).removed == []

    def unexpected(*args, **kwargs):
        raise AssertionError("Cached render must not invoke LLM/transcription/download")

    monkeypatch.setattr("worker.pipeline.llm.LLMClient.call_json", unexpected)
    monkeypatch.setattr("worker.pipeline.ingest.transcribe", unexpected)
    monkeypatch.setattr("worker.pipeline.ingest.download", unexpected)
    assert client.post(f"/api/clips/{first['id']}/render").status_code == 202
    run_output(identifier, clip_id=first["id"])
    fresh = next(
        c
        for c in client.get(f"/api/outputs/{identifier}").json()["clips"]
        if c["id"] == first["id"]
    )
    assert not fresh["needs_render"] and fresh["qc"]["karaoke_enabled"]
    assert fresh["qc"]["width"] < fresh["qc"]["height"]
    assert fresh["qc"]["width"] * 16 == fresh["qc"]["height"] * 9
    assert fresh["qc"]["checks"]["platform_format"]
    assert fresh["qc"]["duration_s"] == pytest.approx(3, abs=0.1)
    assert other_stamp == (digest(other_video), other_video.stat().st_mtime_ns)
    assert originals == (
        source.stat().st_mtime_ns,
        digest(transcript_path),
        digest(directory / "llm_log.jsonl"),
    )
    rated = client.patch(
        f"/api/clips/{first['id']}",
        json={"rating": "up", "rating_note": "Langkah utuh dan caption terbaca"},
    ).json()
    assert not rated["needs_render"]
    with Session(get_engine()) as session:
        examples = liked_examples(session, "tutorial")
        assert examples[0]["note"] == "Langkah utuh dan caption terbaca"
        assert liked_examples(session, "discovery") == []
    assert client.patch(f"/api/clips/{first['id']}", json={"rating": "down"}).status_code == 200
    with Session(get_engine()) as session:
        assert liked_examples(session) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"start_s": 5, "end_s": 3},
        {"start_s": 1, "end_s": 20},
        {"caption_overrides": {"w999": "asing"}},
        {"caption_overrides": {"w2": "dua kata"}},
        {"caption_overrides": {"w2": ""}},
        {"platform": "youtube_shorts", "layout": "source"},
    ],
)
def test_invalid_edits_are_atomic(client, word_project, changes):
    response = client.post(
        f"/api/projects/{word_project['id']}/outputs",
        json={"mode": "clips", "settings": {"clip_count": 1}},
    )
    run_output(response.json()["id"])
    url = f"/api/outputs/{response.json()['id']}"
    before = client.get(url).json()["clips"][0]
    assert client.patch(f"/api/clips/{before['id']}", json=changes).status_code == 422
    assert client.get(url).json()["clips"][0] == before


def test_cleanup_respects_source_lease_original_upload_and_restores_without_transcription(
    client, project, monkeypatch
):
    ingest_project(project["id"])
    directory = project_dir(project["id"])
    source = directory / "source.mp4"
    transcript = directory / "transcript.json"
    original_text = transcript.read_bytes()
    old = time.time() - 16 * 86400
    for path in [source, directory / ".source-used"]:
        os.utime(path, (old, old))
    # Outstanding jobs protect cached files even before their source lease is acquired.
    assert cleanup_sources() == []

    with Session(get_engine()) as session:
        for task in session.exec(select(Task)):
            task.state = "done"
            session.add(task)
        session.commit()
    with file_lock(directory / ".source.lock"):
        assert cleanup_sources() == []
    original = get_settings().storage / "uploads" / f"{project['source_ref']}.bin"
    parked = original.with_suffix(".parked")
    original.rename(parked)
    try:
        assert cleanup_sources() == []
    finally:
        parked.rename(original)
    assert cleanup_sources() == [project["id"]]
    assert original.exists()
    assert not source.exists() and transcript.read_bytes() == original_text
    assert (directory / "audio.wav").exists()

    def unexpected(*args, **kwargs):
        raise AssertionError("Retained transcript must be reused")

    monkeypatch.setattr("worker.pipeline.ingest.transcribe", unexpected)
    ingest_project(project["id"])
    assert source.exists() and transcript.read_bytes() == original_text
    assert cleanup_sources() == []


def test_trim_legacy_sentence_edits_maps_words_or_rejects_ambiguous_timing(client, word_project):
    response = client.post(
        f"/api/projects/{word_project['id']}/outputs",
        json={"mode": "clips", "settings": {"clip_count": 2, "max_clip_seconds": 4}},
    )
    identifier = response.json()["id"]
    run_output(identifier)
    clip = next(
        c for c in client.get(f"/api/outputs/{identifier}").json()["clips"] if c["start_s"] < 1
    )
    url = f"/api/clips/{clip['id']}"
    client.patch(url, json={"caption_overrides": {"s1": "Pisahkan dana usaha."}}).raise_for_status()
    trimmed = client.patch(url, json={"start_s": 0.9, "end_s": 3.1})
    assert trimmed.status_code == 200, trimmed.text
    assert trimmed.json()["caption_overrides"] == {"w2": "dana", "w3": "usaha."}
    client.patch(
        url, json={"caption_overrides": {"s1": "Jumlah kata sudah berbeda"}}
    ).raise_for_status()
    before = next(
        c for c in client.get(f"/api/outputs/{identifier}").json()["clips"] if c["id"] == clip["id"]
    )
    rejected = client.patch(url, json={"start_s": 2.5, "end_s": 7.8})
    assert rejected.status_code == 422
    assert "Pulihkan kata asli" in rejected.json()["detail"]
    assert (
        next(
            c
            for c in client.get(f"/api/outputs/{identifier}").json()["clips"]
            if c["id"] == clip["id"]
        )
        == before
    )
