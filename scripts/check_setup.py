"""Read-only native setup checks; no servers, model downloads, or media processing."""

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def output(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, cwd=ROOT)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def main() -> int:
    results = []

    def check(label: str, passed: bool, detail: str):
        results.append(passed)
        print(f"{'OK' if passed else 'CEK'}  {label}: {detail}")

    for command in ("uv", "npm", "redis-server"):
        path = shutil.which(command)
        check(command, bool(path), path or "belum ditemukan di PATH")

    package = json.loads((ROOT / "web/package.json").read_text())
    minimum = package["engines"]["node"]
    node = shutil.which("node")
    actual = output([node, "--version"]) if node else ""
    actual_numbers = tuple(map(int, re.findall(r"\d+", actual)))
    minimum_numbers = tuple(map(int, re.findall(r"\d+", minimum)))
    check(
        "Node.js",
        bool(actual_numbers) and actual_numbers >= minimum_numbers,
        f"{actual or 'belum tersedia'}; proyek membutuhkan {minimum}",
    )

    python = ROOT / ".venv/bin/python"
    version = output([str(python), "--version"]) if python.exists() else ""
    supported = version.startswith("Python 3.12.")
    check(
        "Python backend",
        supported,
        version if supported else "butuh .venv Python 3.12; jalankan make install",
    )
    if supported:
        # Read installed distribution metadata, without importing models or native libraries.
        program = """
import importlib.metadata as metadata
import json, re, sys, tomllib
from pathlib import Path
requirements = tomllib.loads(Path(sys.argv[1]).read_text())['project']['dependencies']
missing = []
for requirement in requirements:
    name = re.split(r'[\\[<>=!~; ]', requirement, maxsplit=1)[0]
    try:
        metadata.distribution(name)
    except metadata.PackageNotFoundError:
        missing.append(name)
print(json.dumps({'total': len(requirements), 'missing': missing}))
"""
        raw = output([str(python), "-c", program, str(ROOT / "pyproject.toml")])
        try:
            dependencies = json.loads(raw)
        except ValueError:
            dependencies = {"total": 0, "missing": ["metadata tidak dapat dibaca"]}
        missing = dependencies["missing"]
        check(
            "Dependensi Python",
            not missing,
            "belum tersedia: " + ", ".join(missing) + "; jalankan make install"
            if missing
            else f"{dependencies['total']} paket dasar ditemukan",
        )

    web_ready = all(
        (ROOT / "web/node_modules" / name / "package.json").is_file()
        for name in (*package["dependencies"], "typescript")
    )
    check(
        "Dependensi web",
        web_ready,
        "paket dasar ditemukan" if web_ready else "belum lengkap; jalankan make install",
    )

    ffmpeg = shutil.which("ffmpeg")
    filters = output([ffmpeg, "-hide_banner", "-filters"]) if ffmpeg else ""
    encoders = output([ffmpeg, "-hide_banner", "-encoders"]) if ffmpeg else ""
    ready = bool(
        re.search(r"\bass\s+", filters)
        and re.search(r"\bloudnorm\s+", filters)
        and re.search(r"\blibx264\s+", encoders)
        and re.search(r"\baac\s+", encoders)
    )
    check(
        "FFmpeg",
        ready,
        "ass, loudnorm, libx264, AAC tersedia"
        if ready
        else "butuh FFmpeg dengan filter ass/loudnorm dan encoder libx264/AAC",
    )
    ffprobe = shutil.which("ffprobe")
    probe_ready = bool(output([ffprobe, "-version"])) if ffprobe else False
    check("ffprobe", probe_ready, ffprobe if probe_ready else "belum dapat dijalankan")

    print(
        "\nPemeriksaan hanya mencakup setup dasar lokal; model Whisper opsional dan layanan aktif tidak diperiksa."
    )
    print(
        "Setup dasar siap diperiksa lewat aplikasi."
        if all(results)
        else "Lengkapi bagian CEK, lalu jalankan make doctor kembali."
    )
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
