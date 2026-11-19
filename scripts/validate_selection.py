"""Opt-in real-media Phase 2 smoke: API + Redis/RQ + supplied transcript + mock LLM."""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=ROOT / "data/phase2-validation/report.json")
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    video, transcript_path = args.video.resolve(), args.transcript.resolve()
    # Reserve an ephemeral local port for this harness's Redis only.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    beginning = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="cuplik-selection-") as temporary:
        os.environ.update(
            DATA_DIR=temporary,
            REDIS_URL=f"redis://127.0.0.1:{port}/0",
            LLM_PROVIDER="mock",
            YTDLP_AUTO_UPDATE="false",
            RENDER_HEIGHT="320",
            MAINTENANCE_INTERVAL_SECONDS="1",
        )
        from fastapi.testclient import TestClient

        from api.app.config import get_settings
        from api.app.db import get_engine
        from api.app.main import app
        from api.app.schemas import Transcript
        from worker.pipeline.media import probe_file
        from worker.pipeline.storage import output_dir, project_dir

        get_settings.cache_clear()
        get_engine.cache_clear()
        transcript = Transcript.model_validate_json(transcript_path.read_text())
        processes = []
        with (args.report.parent / "workflow-smoke.log").open("w") as log:

            def start(command):
                process = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    env=os.environ.copy(),
                    start_new_session=True,
                    stdout=log,
                    stderr=log,
                )
                processes.append(process)
                return process

            def wait(predicate, seconds=180):
                started = time.monotonic()
                while time.monotonic() - started < seconds:
                    result = predicate()
                    if result:
                        return result
                    time.sleep(0.1)
                raise RuntimeError("Uji seleksi melewati batas waktu; lihat workflow-smoke.log")

            try:
                redis = start(
                    [
                        "redis-server",
                        "--bind",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--save",
                        "",
                        "--appendonly",
                        "no",
                    ]
                )

                def redis_ready():
                    if redis.poll() is not None:
                        raise RuntimeError("Redis uji tidak dapat dimulai")
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                            return True
                    except OSError:
                        return False

                wait(redis_ready, 15)
                with TestClient(app) as client:
                    start([sys.executable, "-m", "worker.main"])
                    upload = client.post(
                        "/api/uploads",
                        json={"filename": video.name, "total_bytes": video.stat().st_size},
                    )
                    upload.raise_for_status()
                    upload = upload.json()
                    offset = 0
                    with video.open("rb") as handle:
                        while chunk := handle.read(upload["chunk_bytes"]):
                            result = client.put(
                                f"/api/uploads/{upload['id']}?offset={offset}", content=chunk
                            )
                            result.raise_for_status()
                            offset = result.json()["offset"]
                    created = client.post(
                        "/api/projects",
                        json={
                            "source_kind": "upload",
                            "upload_id": upload["id"],
                            "title": "Validasi seleksi video Indonesia",
                            "transcript": transcript.model_dump(),
                        },
                    )
                    created.raise_for_status()
                    project_id = created.json()["id"]
                    created = client.post(
                        f"/api/projects/{project_id}/outputs",
                        json={
                            "mode": "clips",
                            "settings": {
                                "clip_count": 3,
                                "min_clip_seconds": 3,
                                "max_clip_seconds": 30,
                            },
                        },
                    )
                    created.raise_for_status()
                    output_id = created.json()["id"]

                    def completed():
                        response = client.get(f"/api/outputs/{output_id}")
                        response.raise_for_status()
                        detail = response.json()
                        if detail["output"]["status"] == "failed":
                            raise RuntimeError(detail["output"]["error"])
                        return detail if detail["output"]["status"] == "done" else None

                    detail = wait(completed)
                    assert detail["clips"]
                    cuts = []
                    for clip in detail["clips"]:
                        assert clip["selection"]["boundary_precision"] == "word"
                        assert 3 <= clip["end_s"] - clip["start_s"] <= 30
                        cuts.extend(
                            [
                                t
                                for t in (clip["start_s"], clip["end_s"])
                                if any(w.start + 1e-6 < t < w.end - 1e-6 for w in transcript.words)
                            ]
                        )
                        downloaded = client.get(clip["file_url"])
                        downloaded.raise_for_status()
                        path = args.report.parent / f"clip-{clip['rank']}.mp4"
                        path.write_bytes(downloaded.content)
                        assert (
                            abs(probe_file(path)["duration_s"] - (clip["end_s"] - clip["start_s"]))
                            < 0.4
                        )
                    assert not cuts
                    iq = client.get(f"/api/projects/{project_id}/signals")
                    iq.raise_for_status()
                    selection = client.get(f"/api/outputs/{output_id}/selection")
                    selection.raise_for_status()
                    selection = selection.json()
                    assert selection["metrics"]["max_per_topic"] <= 2
                    stream = client.get(f"/api/outputs/{output_id}/events")
                    assert all(
                        f'"stage": "{stage}"' in stream.text
                        for stage in ("signals", "moments", "scoring", "rerank", "render", "done")
                    )
                    stamp = (project_dir(project_id) / "signals.json").stat().st_mtime_ns
                    clip = detail["clips"][0]
                    assert (
                        client.patch(f"/api/clips/{clip['id']}", json={"rating": "up"}).status_code
                        == 200
                    )
                    created = client.post(
                        f"/api/projects/{project_id}/outputs",
                        json={
                            "mode": "clips",
                            "settings": {"clip_count": 1, "max_clip_seconds": 30},
                        },
                    )
                    created.raise_for_status()
                    output_id = created.json()["id"]
                    wait(completed)
                    second = json.loads((output_dir(output_id) / "selection.json").read_text())
                    assert second["liked_examples_used"] == 1
                    assert (project_dir(project_id) / "signals.json").stat().st_mtime_ns == stamp
                    (args.report.parent / "signals.json").write_text(iq.text)
                    (args.report.parent / "selection.json").write_text(
                        json.dumps(selection, ensure_ascii=False, indent=2)
                    )
                    (args.report.parent / "transcript.json").write_text(
                        json.dumps(detail["transcript"], ensure_ascii=False, indent=2)
                    )
                    report = {
                        "status": "passed",
                        "source": str(video),
                        "duration_s": detail["project"]["duration_s"],
                        "transcript_source": str(transcript_path),
                        "words": len(transcript.words),
                        "llm_provider": "mock",
                        "clips": len(detail["clips"]),
                        "cuts_through_words": len(cuts),
                        "selection_metrics": selection["metrics"],
                        "signals_cache_reused": True,
                        "liked_examples_used_on_next_output": second["liked_examples_used"],
                        "sse_stages_verified": True,
                        "quality_evaluation": "not_run: supplied ASR transcript and mock scores, no human golden labels",
                        "elapsed_s": round(time.monotonic() - beginning, 2),
                    }
                    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                    print(json.dumps(report, ensure_ascii=False, indent=2))
            finally:
                for process in reversed(processes):
                    if process.poll() is not None:
                        continue
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=3)
                get_engine().dispose()
                get_engine.cache_clear()
                get_settings.cache_clear()


if __name__ == "__main__":
    main()
