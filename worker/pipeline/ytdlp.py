"""Daily, isolated yt-dlp updates; never mutate the application's locked environment."""

import importlib.metadata
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from api.app.config import get_settings
from worker.pipeline.storage import atomic_json, file_lock, json_object

logger = logging.getLogger(__name__)


def tool_directory():
    path = get_settings().storage / "tools" / "yt-dlp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def status() -> dict:
    directory = tool_directory()
    try:
        data = json_object(directory / "active.json")
        version = data["version"]
        if (
            not re.fullmatch(r"\d{4}\.\d{1,2}\.\d{1,2}(?:\.\d+)?", version)
            or not (directory / version / "yt_dlp").is_dir()
        ):
            raise ValueError("Invalid active yt-dlp installation")
    except (OSError, ValueError, KeyError):
        data = {"version": importlib.metadata.version("yt-dlp"), "isolated": False}
    check = json_object(directory / "check.json")
    data.update({key: check[key] for key in ("last_checked", "update_error") if key in check})
    return data


def command(args: list[str]) -> tuple[list[str], dict]:
    info = status()
    env = os.environ.copy()
    if info.get("isolated"):
        env["PYTHONPATH"] = str(tool_directory() / info["version"])
    return [sys.executable, "-m", "yt_dlp", *args], env


def update_if_due(*, force=False, client=None, installer=None) -> dict:
    settings = get_settings()
    if not force and not settings.ytdlp_auto_update:
        return status()
    directory = tool_directory()
    with file_lock(directory / ".update.lock"):
        current = status()
        zone = ZoneInfo(settings.ytdlp_update_timezone)
        clock = datetime.now(UTC)
        # Check at worker startup, then after 03:00 local time on each new day.
        last = current.get("last_checked")
        local = clock.astimezone(zone)
        if last and not force:
            previous = datetime.fromisoformat(last).astimezone(zone)
            due_day = (local - timedelta(hours=3)).date()
            if previous.date() >= due_day:
                return current
        check = {"last_checked": clock.isoformat(), "update_error": None}
        try:
            if client is None:
                with httpx.Client(timeout=20, follow_redirects=True) as remote:
                    response = remote.get("https://pypi.org/pypi/yt-dlp/json")
            else:
                response = client.get("https://pypi.org/pypi/yt-dlp/json")
            response.raise_for_status()
            version = response.json()["info"]["version"]
            if not re.fullmatch(r"\d{4}\.\d{1,2}\.\d{1,2}(?:\.\d+)?", version):
                raise ValueError("Versi stable yt-dlp tidak dikenali")
            if version != current["version"]:
                target = directory / version
                if not target.exists():
                    with tempfile.TemporaryDirectory(prefix="staging-", dir=directory) as temporary:
                        staging = Path(temporary)
                        if installer is not None:
                            installer(staging, version)
                        else:
                            uv = shutil.which("uv")
                            if not uv:
                                raise RuntimeError("uv diperlukan untuk pembaruan terisolasi")
                            env = {**os.environ, "UV_CACHE_DIR": str(directory / "uv-cache")}
                            subprocess.run(
                                [
                                    uv,
                                    "pip",
                                    "install",
                                    "--python",
                                    sys.executable,
                                    "--target",
                                    str(staging),
                                    "--index-url",
                                    "https://pypi.org/simple",
                                    "--only-binary=:all:",
                                    f"yt-dlp[default]=={version}",
                                ],
                                env=env,
                                check=True,
                                capture_output=True,
                                timeout=180,
                            )
                        env = {**os.environ, "PYTHONPATH": str(staging)}
                        checked = subprocess.run(
                            [sys.executable, "-m", "yt_dlp", "--version"],
                            env=env,
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=15,
                        )
                        if checked.stdout.strip() != version:
                            raise ValueError("Versi yt-dlp hasil instalasi tidak cocok")
                        staging.rename(target)
                atomic_json(directory / "active.json", {"version": version, "isolated": True})
        except Exception:
            logger.warning("yt-dlp update unavailable; keeping the previous working installation")
            check["update_error"] = (
                "Pembaruan gagal; versi sebelumnya tetap digunakan. Coba make update-ytdlp."
            )
        atomic_json(directory / "check.json", check)
    return status()


if __name__ == "__main__":
    print(json.dumps(update_if_due(force=True), indent=2))
