from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.app.config import get_settings
from api.app.db import get_engine


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("RENDER_HEIGHT", "320")
    monkeypatch.setenv("YTDLP_AUTO_UPDATE", "false")
    get_settings.cache_clear()
    get_engine.cache_clear()
    tasks = []

    class Queue:
        def enqueue(self, function, *args, **kwargs):
            tasks.append((function, args))
            return SimpleNamespace(id=kwargs["job_id"])

    monkeypatch.setattr("api.app.jobs.queue", lambda: Queue())
    from rq.exceptions import NoSuchJobError

    def missing_job(*_, **__):
        raise NoSuchJobError

    monkeypatch.setattr("api.app.dispatch.Job.fetch", missing_job)
    from api.app.main import app

    with TestClient(app) as test_client:
        test_client.tasks = tasks
        yield test_client
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def video(tmp_path_factory):
    from worker.pipeline.media import run

    path = tmp_path_factory.mktemp("media") / "source.mp4"
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=24:duration=12",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=12",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ]
    )
    return path


@pytest.fixture
def transcript():
    return {
        "language": "id",
        "sentences": [
            {"id": "s1", "start": 0, "end": 4, "text": "Pisahkan uang pribadi dan uang usaha."},
            {
                "id": "s2",
                "start": 4,
                "end": 8,
                "text": "Catat setiap transaksi pada hari yang sama.",
            },
            {
                "id": "s3",
                "start": 8,
                "end": 12,
                "text": "Tinjau keuntungan usaha setiap akhir pekan.",
            },
        ],
    }


@pytest.fixture
def project(client, video, transcript):
    data = video.read_bytes()
    upload = client.post(
        "/api/uploads", json={"filename": "uji.mp4", "total_bytes": len(data)}
    ).json()
    response = client.put(f"/api/uploads/{upload['id']}?offset=0", content=data)
    assert response.status_code == 200, response.text
    response = client.post(
        "/api/projects",
        json={"source_kind": "upload", "upload_id": upload["id"], "transcript": transcript},
    )
    assert response.status_code == 201, response.text
    return response.json()
