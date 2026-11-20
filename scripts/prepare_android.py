"""Fetch the pinned native engine and bundle the Android UI; no SDK or API keys are installed."""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WHISPER_COMMIT = "d1be6fde11ac6e0407606b4e42fe72d34add8037"


def main():
    source = ROOT / "android/third_party/whisper.cpp"
    if not (source / ".git").exists():
        source.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(source)], check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/ggml-org/whisper.cpp.git"],
            cwd=source,
            check=True,
        )
        subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", WHISPER_COMMIT], cwd=source, check=True
        )
        subprocess.run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=source, check=True)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if actual != WHISPER_COMMIT:
        raise SystemExit(
            "Versi whisper.cpp berbeda dari pin proyek; gunakan direktori dependensi yang sesuai."
        )
    subprocess.run(["npm", "run", "build:android-ui", "--prefix", str(ROOT / "web")], check=True)
    shutil.copyfile(source / "LICENSE", ROOT / "android/app/src/main/assets/whisper-LICENSE.txt")
    print("Android siap dibangun dengan SDK 36, NDK 27.0.12077973, CMake 3.22.1 dan JDK 17.")


if __name__ == "__main__":
    main()
