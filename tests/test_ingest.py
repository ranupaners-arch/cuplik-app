import json
import wave
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlmodel import Session, select

from api.app.config import get_settings
from api.app.db import get_engine
from api.app.dispatch import dispatch_pending, recover_tasks, task_lock
from api.app.models import Project, Task, Upload, now
from api.app.schemas import Transcript
from worker.pipeline.ingest import ingest_project
from worker.pipeline.media import MediaError, probe_url, ytdlp_error
from worker.pipeline.storage import file_lock, project_dir
from worker.pipeline.transcription import repeated_ngram, segment_words, transcribe
from worker.pipeline.ytdlp import command, status, update_if_due


def make_audio(path, seconds):
    with wave.open(str(path), "wb") as source:
        source.setnchannels(1)
        source.setsampwidth(2)
        source.setframerate(16000)
        source.writeframes(b"\x00\x00" * 16000 * seconds)


def test_chunk_checkpoints_resume_and_reject_corrupt_cache(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WHISPER_CHUNK_SECONDS", "10")
    get_settings.cache_clear()
    audio = tmp_path / "audio.wav"
    make_audio(audio, 23)
    state = {"calls": 0, "fail": True, "prompts": []}

    class Decoder:
        def decode(self, path, language, prompt, progress):
            state["calls"] += 1
            state["prompts"].append(prompt)
            if state["fail"] and state["calls"] == 2:
                raise RuntimeError("uji proses terputus")
            return [
                {
                    "text": "Ilmu nahu dasar",
                    "words": [
                        {"start": 0.1 + i * 0.4, "end": 0.4 + i * 0.4, "word": text}
                        for i, text in enumerate(["Ilmu", "nahu", "dasar."])
                    ],
                }
            ], "id"

    monkeypatch.setattr("worker.pipeline.transcription.Decoder", Decoder)
    directory = tmp_path / "chunks"
    options = {"checkpoint_dir": directory, "glossary": {"nahu": "nahwu"}, "language": "id"}
    with pytest.raises(RuntimeError):
        transcribe(audio, **options)
    first = next(directory.glob("*-00000.json"))
    first_content = first.read_bytes()
    assert len(list(directory.glob("*.json"))) == 1
    state["fail"] = False
    updates = []
    result = transcribe(audio, progress=lambda f, n: updates.append((f, n)), **options)
    assert state["calls"] == 4, "Only the interrupted and remaining chunks should decode again"
    assert first.read_bytes() == first_content
    assert result.sentences[1].start >= 10 and result.sentences[2].start >= 20
    assert any(w.text == "nahwu" for w in result.words)
    assert all("nahwu" in p for p in state["prompts"])
    assert updates[-1][0] == 1
    transcribe(audio, **options)
    assert state["calls"] == 4, "Completed checkpoints should not load/decode a model"
    corrupted = json.loads(first.read_text())
    corrupted["segments"] = []
    first.write_text(json.dumps(corrupted))
    transcribe(audio, **options)
    assert state["calls"] == 5, "Checksum mismatch must regenerate a corrupt chunk"


def test_hallucinated_segments_are_audited_not_burned_into_captions(client, tmp_path, monkeypatch):
    audio = tmp_path / "audio.wav"
    make_audio(audio, 3)

    def segment(text, start=0, no_speech_prob=0):
        return {
            "text": text,
            "start": start,
            "end": start + 1,
            "no_speech_prob": no_speech_prob,
            "words": [{"word": text, "start": start, "end": start + 1}],
        }

    monkeypatch.setattr(
        "worker.pipeline.transcription.Decoder",
        lambda: SimpleNamespace(
            decode=lambda *_: (
                [
                    segment("terima kasih semua terima kasih semua terima kasih semua"),
                    segment("kalimat palsu", 1, 0.99),
                    segment("Langkah yang valid.", 2),
                ],
                "id",
            )
        ),
    )
    result = transcribe(audio)
    assert result.sentences[0].text == "Langkah yang valid."
    report = json.loads((tmp_path / "transcription/report.json").read_text())
    assert {s["reason"] for s in report["dropped_segments"]} == {"no_speech", "repeated_ngram"}
    assert result.warnings
    assert not repeated_ngram("Ini tutorial asli dengan langkah yang berbeda.")


def test_sentence_segmentation_limits_words_and_preserves_ids(client):
    words = [{"start": i * 0.3, "end": i * 0.3 + 0.2, "text": f"kata{i}"} for i in range(53)]
    result = segment_words(words, "id")
    assert [len(s.word_ids) for s in result.sentences] == [25, 25, 3]
    assert [w for s in result.sentences for w in s.word_ids] == [w.id for w in result.words]
    short = segment_words(
        [
            {"start": i * 0.3, "end": i * 0.3 + 0.2, "text": text}
            for i, text in enumerate(
                ["Mari", "belajar", "nahu.", "Oke.", "Mulai", "dengan", "contoh."]
            )
        ],
        "id",
        {"nahu": "nahwu"},
    )
    assert all(len(s.word_ids) >= 3 for s in short.sentences)
    assert "nahwu." in short.sentences[0].text
    with pytest.raises(ValueError):
        Transcript.model_validate(
            {
                "sentences": [{"id": "s1", "start": 0, "end": 1, "text": "x", "word_ids": ["w1"]}],
                "words": [{"id": "w1", "start": 2, "end": 3, "text": "x"}],
            }
        )


def test_glossary_crud_and_shared_ingest_audio_cache(client, project):
    created = client.post("/api/glossary", json={"wrong": "Usaha", "correct": "bisnis"})
    assert created.status_code == 201
    assert (
        client.post("/api/glossary", json={"wrong": "USAHA", "correct": "usaha"}).status_code == 409
    )
    assert (
        client.post("/api/glossary", json={"wrong": "dua kata", "correct": "satu"}).status_code
        == 422
    )
    ingest_project(project["id"])
    path = project_dir(project["id"])
    with wave.open(str(path / "audio.wav")) as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (16000, 1, 2)
    original = client.get(f"/api/projects/{project['id']}/transcript")
    assert original.status_code == 200
    assert "bisnis" in original.json()["sentences"][0]["text"]
    stamps = [
        (path / name).stat().st_mtime_ns for name in ["source.mp4", "audio.wav", "transcript.json"]
    ]
    assert (
        client.put(
            f"/api/glossary/{created.json()['id']}", json={"wrong": "usaha", "correct": "niaga"}
        ).status_code
        == 200
    )
    ingest_project(project["id"])
    assert stamps == [
        (path / name).stat().st_mtime_ns for name in ["source.mp4", "audio.wav", "transcript.json"]
    ]
    assert client.get(f"/api/projects/{project['id']}/transcript").json() == original.json()
    assert client.delete(f"/api/glossary/{created.json()['id']}").status_code == 200
    assert client.get("/api/glossary").json() == []


def test_corrupt_source_and_transcript_recover_from_original_upload(client, project):
    ingest_project(project["id"])
    directory = project_dir(project["id"])
    (directory / "source.mp4").write_bytes(b"incomplete copy")
    (directory / "transcript.json").write_text("{bad")
    (directory / "ingest.json").write_text("null")
    (directory / "audio.json").write_text("[]")
    ingest_project(project["id"])
    assert list(directory.glob("source.corrupt-*.mp4"))
    assert client.get(f"/api/projects/{project['id']}/transcript").status_code == 200


def test_completed_file_can_finalize_after_api_crash(client, video):
    data = video.read_bytes()
    upload = client.post(
        "/api/uploads", json={"filename": "video.mp4", "total_bytes": len(data)}
    ).json()
    assert client.post(f"/api/uploads/{upload['id']}/complete").status_code == 409
    assert client.put(f"/api/uploads/{upload['id']}?offset=0", content=data).status_code == 200
    with Session(get_engine()) as session:
        item = session.get(Upload, upload["id"])
        item.complete = False
        session.add(item)
        session.commit()
    assert not client.get(f"/api/uploads/{upload['id']}").json()["complete"]
    assert client.post(f"/api/uploads/{upload['id']}/complete").json()["complete"]


def test_durable_dispatch_survives_redis_outage_and_does_not_duplicate(client, monkeypatch):
    sent = []

    def offline():
        raise ConnectionError("offline")

    monkeypatch.setattr("api.app.jobs.queue", offline)
    project = client.post("/api/projects", json={"source_kind": "demo"}).json()
    with Session(get_engine()) as session:
        task = session.exec(select(Task).where(Task.subject_id == project["id"])).one()
        assert task.state == "pending"
        identifier, rq_id = task.id, task.rq_job_id
    monkeypatch.setattr(
        "api.app.jobs.queue", lambda: SimpleNamespace(enqueue=lambda *a, **k: sent.append((a, k)))
    )
    assert dispatch_pending() == 1
    assert dispatch_pending() == 0
    assert len(sent) == 1 and sent[0][1]["job_id"] == rq_id
    with Session(get_engine()) as session:
        assert session.get(Task, identifier).state == "enqueued"


def test_recovery_respects_process_lock_and_requeues_dead_attempt(client, monkeypatch):
    project = client.post("/api/projects", json={"source_kind": "demo"}).json()
    with Session(get_engine()) as session:
        task = session.exec(select(Task).where(Task.subject_id == project["id"])).one()
        identifier, old_rq = task.id, task.rq_job_id
        task.state = "running"
        task.updated_at = now() - timedelta(minutes=5)
        session.add(task)
        session.commit()
    monkeypatch.setattr(
        "api.app.dispatch.Job.fetch",
        lambda *_, **__: SimpleNamespace(get_status=lambda **_: "started"),
    )
    with file_lock(task_lock(identifier)):
        assert recover_tasks() == 0
    assert recover_tasks() == 1
    with Session(get_engine()) as session:
        task = session.get(Task, identifier)
        assert task.state == "pending" and task.rq_job_id != old_rq
        assert session.get(Project, project["id"]).job_id == task.rq_job_id


def test_project_retry_and_sse_replay(client, project):
    with Session(get_engine()) as session:
        item = session.get(Project, project["id"])
        item.transcript_status = "failed"
        item.error = "uji"
        session.add(item)
        session.commit()
        for task in session.exec(select(Task).where(Task.subject_id == project["id"])).all():
            task.state = "failed"
            session.add(task)
        session.commit()
    assert client.post(f"/api/projects/{project['id']}/retry").status_code == 202
    assert client.post(f"/api/projects/{project['id']}/retry").status_code == 409
    ingest_project(project["id"])
    response = client.get(f"/api/projects/{project['id']}/events")
    ids = [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
    assert len(ids) >= 4
    replay = client.get(
        f"/api/projects/{project['id']}/events", headers={"Last-Event-ID": str(ids[-2])}
    )
    assert [int(line[4:]) for line in replay.text.splitlines() if line.startswith("id: ")] == [
        ids[-1]
    ]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ERROR: Private video", "privat"),
        ("Sign in to confirm your age", "usia"),
        ("Sign in to confirm you're not a bot", "verifikasi"),
        ("Video unavailable", "tersedia"),
    ],
)
def test_youtube_failures_offer_specific_recovery(text, expected):
    assert expected in ytdlp_error(text)


def test_probe_rejects_unexpected_playlist_and_no_audio(client, monkeypatch):
    monkeypatch.setattr(
        "worker.pipeline.media.run", lambda *_, **__: json.dumps({"_type": "playlist"})
    )
    with pytest.raises(MediaError, match="Playlist"):
        probe_url("https://youtu.be/example")
    monkeypatch.setattr(
        "worker.pipeline.media.run",
        lambda *_, **__: json.dumps({"duration": 10, "formats": [{"acodec": "none"}]}),
    )
    with pytest.raises(MediaError, match="audio"):
        probe_url("https://youtu.be/example")


def test_ytdlp_update_isolated_atomic_and_failure_keeps_working_version(client):
    original = status()["version"]
    remote = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"info": {"version": "2099.1.1"}})
        )
    )

    def install(directory, version):
        package = directory / "yt_dlp"
        package.mkdir()
        (package / "__init__.py").write_text("")
        (package / "__main__.py").write_text(f"print('{version}')")

    result = update_if_due(force=True, client=remote, installer=install)
    assert result["version"] == "2099.1.1" and result["isolated"]
    import importlib.metadata

    assert importlib.metadata.version("yt-dlp") == original
    args, env = command(["--version"])
    assert Path(env["PYTHONPATH"]).name == "2099.1.1"
    failed = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    fallback = update_if_due(force=True, client=failed)
    assert fallback["version"] == "2099.1.1" and fallback["update_error"]
