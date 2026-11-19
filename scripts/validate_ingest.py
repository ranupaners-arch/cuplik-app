"""Opt-in real ASR + hard-crash recovery smoke test. Never part of offline CI tests."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def available_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--model", default="base")
    parser.add_argument(
        "--report", type=Path, default=ROOT / "data/phase1-validation/workflow-report.json"
    )
    args = parser.parse_args()
    if sys.platform != "linux":
        raise SystemExit(
            "Crash harness ini khusus Linux; memakai /proc untuk menarget workhorse miliknya sendiri."
        )
    video = args.video.resolve()
    if not video.is_file():
        raise SystemExit("Video tidak ditemukan")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    processes = []
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="cuplik-real-asr-") as directory:
        data = Path(directory)
        api_port, redis_port = available_port(), available_port()
        env = {
            **os.environ,
            "DATA_DIR": str(data),
            "REDIS_URL": f"redis://127.0.0.1:{redis_port}/0",
            "LLM_PROVIDER": "mock",
            "YTDLP_AUTO_UPDATE": "false",
            "WHISPER_MODEL": args.model,
            "WHISPER_DEVICE": "cpu",
            "WHISPER_COMPUTE_TYPE": "int8",
            "WHISPER_CHUNK_SECONDS": "10",
            "TRANSCRIPTION_BACKEND": "faster-whisper",
            "MAINTENANCE_INTERVAL_SECONDS": "1",
            "RENDER_HEIGHT": "320",
            "PYTHONUNBUFFERED": "1",
        }
        with (args.report.parent / "workflow-smoke.log").open("w") as log:

            def spawn(command):
                process = subprocess.Popen(
                    command, cwd=ROOT, env=env, start_new_session=True, stdout=log, stderr=log
                )
                processes.append(process)
                return process

            def wait(predicate, seconds=180):
                beginning = time.monotonic()
                while time.monotonic() - beginning < seconds:
                    result = predicate()
                    if result:
                        return result
                    time.sleep(0.05)
                raise RuntimeError("Batas waktu uji terlewati; lihat workflow-smoke.log")

            try:
                spawn(
                    [
                        "redis-server",
                        "--bind",
                        "127.0.0.1",
                        "--port",
                        str(redis_port),
                        "--save",
                        "",
                        "--appendonly",
                        "no",
                    ]
                )
                api = spawn(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "api.app.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(api_port),
                    ]
                )
                with httpx.Client(base_url=f"http://127.0.0.1:{api_port}", timeout=30) as client:

                    def healthy():
                        if api.poll() is not None:
                            raise RuntimeError("API tidak dapat dimulai")
                        try:
                            return client.get("/api/health").json().get("redis")
                        except (httpx.TransportError, ValueError):
                            return False

                    wait(healthy, 30)
                    client.post(
                        "/api/glossary", json={"wrong": "penggurus", "correct": "pengurus"}
                    ).raise_for_status()
                    upload = client.post(
                        "/api/uploads",
                        json={"filename": video.name, "total_bytes": video.stat().st_size},
                    )
                    upload.raise_for_status()
                    upload = upload.json()
                    with video.open("rb") as source:
                        offset = 0
                        while chunk := source.read(upload["chunk_bytes"]):
                            response = client.put(
                                f"/api/uploads/{upload['id']}?offset={offset}", content=chunk
                            )
                            response.raise_for_status()
                            offset += len(chunk)
                    response = client.post(
                        "/api/projects",
                        json={
                            "source_kind": "upload",
                            "upload_id": upload["id"],
                            "language": "id",
                            "title": "Uji tutorial bahasa Indonesia",
                        },
                    )
                    response.raise_for_status()
                    project_id = response.json()["id"]
                    worker = spawn([sys.executable, "-m", "worker.main"])
                    project = data / "projects" / project_id

                    def first_checkpoint():
                        files = list((project / "transcription").glob("*-00000.json"))
                        if files:
                            return files[0]
                        return False

                    first = wait(first_checkpoint)
                    fingerprint = hashlib.sha256(first.read_bytes()).hexdigest()
                    stamps = [
                        (project / name).stat().st_mtime_ns for name in ("source.mp4", "audio.wav")
                    ]
                    children = (
                        Path(f"/proc/{worker.pid}/task/{worker.pid}/children").read_text().split()
                    )
                    horses = [int(pid) for pid in children if os.getpgid(int(pid)) == int(pid)]
                    if len(horses) != 1:
                        raise RuntimeError(
                            "Tidak dapat mengidentifikasi workhorse milik uji secara unik"
                        )
                    os.killpg(horses[0], signal.SIGKILL)
                    os.killpg(worker.pid, signal.SIGKILL)
                    worker.wait(timeout=10)
                    print(
                        "Workhorse dihentikan paksa setelah checkpoint pertama; menjalankan worker baru…",
                        flush=True,
                    )
                    spawn([sys.executable, "-m", "worker.main"])

                    def transcript_done():
                        response = client.get(f"/api/projects/{project_id}")
                        response.raise_for_status()
                        state = response.json()
                        if state["transcript_status"] == "failed":
                            raise RuntimeError(state["error"])
                        return state if state["transcript_status"] == "done" else False

                    finished = wait(transcript_done)
                    transcript = client.get(f"/api/projects/{project_id}/transcript").json()
                    assert len(transcript["words"]) >= 20
                    assert fingerprint == hashlib.sha256(first.read_bytes()).hexdigest()
                    assert stamps == [
                        (project / name).stat().st_mtime_ns for name in ("source.mp4", "audio.wav")
                    ]
                    with sqlite3.connect(data / "cuplik.sqlite3") as db:
                        attempts = db.execute(
                            "SELECT attempts FROM task WHERE subject_id = ?", (project_id,)
                        ).fetchone()[0]
                    assert attempts >= 2
                    events = client.get(f"/api/projects/{project_id}/events")
                    assert events.status_code == 200 and '"stage": "transcribe"' in events.text
                    output = client.post(
                        f"/api/projects/{project_id}/outputs",
                        json={"mode": "clips", "settings": {"clip_count": 1}},
                    )
                    output.raise_for_status()
                    output_id = output.json()["id"]

                    def rendered():
                        response = client.get(f"/api/outputs/{output_id}")
                        response.raise_for_status()
                        detail = response.json()
                        if detail["output"]["status"] == "failed":
                            raise RuntimeError(detail["output"]["error"])
                        return detail if detail["output"]["status"] == "done" else False

                    detail = wait(rendered)
                    mp4 = client.get(detail["clips"][0]["file_url"])
                    assert mp4.status_code == 200 and mp4.content[4:8] == b"ftyp"
                    (args.report.parent / "validated-transcript.json").write_text(
                        json.dumps(transcript, ensure_ascii=False, indent=2) + "\n"
                    )
                    (args.report.parent / "validated-clip.mp4").write_bytes(mp4.content)
                    report = {
                        "status": "passed",
                        "video": str(video),
                        "duration_s": finished["duration_s"],
                        "asr_backend": "faster-whisper",
                        "model": args.model,
                        "pyav": importlib.metadata.version("av"),
                        "language": transcript["language"],
                        "words": len(transcript["words"]),
                        "sentences": len(transcript["sentences"]),
                        "attempts_after_hard_kill": attempts,
                        "first_checkpoint_reused": True,
                        "source_and_audio_reused": True,
                        "sse_replayed": True,
                        "clip_bytes": len(mp4.content),
                        "llm_provider": "mock",
                        "elapsed_s": round(time.monotonic() - started, 2),
                        "preview": [s["text"] for s in transcript["sentences"][:5]],
                    }
                    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
            finally:
                for process in reversed(processes):
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGTERM)
                            try:
                                process.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=5)


if __name__ == "__main__":
    main()
