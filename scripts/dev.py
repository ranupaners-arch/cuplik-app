"""Run the four local processes and terminate only processes started by this supervisor."""

import argparse
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def wait_port(port: int, process: subprocess.Popen, timeout: float = 30):
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if process.poll() is not None:
            raise RuntimeError(f"Proses keluar sebelum port {port} siap")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.15)
    raise RuntimeError(f"Port {port} tidak siap")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-port", type=int, default=3000)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--redis-port", type=int, default=6386)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    processes = []
    temporary = tempfile.TemporaryDirectory(prefix="cuplik-e2e-") if args.test else None
    env = os.environ.copy()
    env.update(
        {
            "REDIS_URL": f"redis://127.0.0.1:{args.redis_port}/0",
            "API_INTERNAL_URL": f"http://127.0.0.1:{args.api_port}",
            "WEB_ORIGIN": f"http://localhost:{args.web_port}",
            "PYTHONUNBUFFERED": "1",
            "NEXT_TELEMETRY_DISABLED": "1",
        }
    )
    if temporary:
        env.update(
            {
                "DATA_DIR": temporary.name,
                "LLM_PROVIDER": "mock",
                "RENDER_HEIGHT": "320",
                "YTDLP_AUTO_UPDATE": "false",
                "MAINTENANCE_INTERVAL_SECONDS": "1",
            }
        )
    redis_directory = Path(env.get("DATA_DIR", str(ROOT / "data"))) / "redis"
    redis_directory.mkdir(parents=True, exist_ok=True)

    def start(command, cwd=ROOT):
        process = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
        processes.append(process)
        return process

    def stop(*_):
        for process in reversed(processes):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    # RQ's second SIGTERM performs a cold shutdown and kills its
                    # workhorse process group before the supervisor exits.
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
        if temporary:
            temporary.cleanup()

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    try:
        # Refuse occupied ports rather than connecting to or modifying somebody else's Redis.
        for port in (args.web_port, args.api_port, args.redis_port):
            with socket.socket() as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", port))
        redis = start(
            [
                "redis-server",
                "--bind",
                "127.0.0.1",
                "--port",
                str(args.redis_port),
                "--save",
                "",
                "--appendonly",
                "no" if args.test else "yes",
                "--dir",
                str(redis_directory.resolve()),
            ]
        )
        wait_port(args.redis_port, redis)
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True
        )
        api = start(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "api.app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.api_port),
            ]
        )
        wait_port(args.api_port, api)
        with urlopen(f"http://127.0.0.1:{args.api_port}/api/health", timeout=10) as response:
            if response.status != 200:
                raise RuntimeError("Health API gagal")
        start([sys.executable, "-m", "worker.main"])
        web = start(["npm", "run", "dev", "--", "--port", str(args.web_port)], cwd=ROOT / "web")
        wait_port(args.web_port, web, 60)
        print(
            f"\nCuplik: http://localhost:{args.web_port}\nAPI: http://localhost:{args.api_port}/docs\n",
            flush=True,
        )
        while True:
            for process in processes:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"Proses {process.pid} berhenti dengan kode {process.returncode}"
                    )
            time.sleep(0.5)
    finally:
        stop()


if __name__ == "__main__":
    main()
