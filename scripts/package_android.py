"""Package a verified APK with version, provenance and checksums (never signing keys)."""

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path


def package(build: Path, output: Path, certificate: Path) -> Path:
    metadata = json.loads((build / "output-metadata.json").read_text())
    elements = metadata.get("elements", [])
    if metadata.get("applicationId") != "app.cuplik" or len(elements) != 1:
        raise ValueError("Expected one universal Cuplik APK.")
    element = elements[0]
    version, code = element["versionName"], element["versionCode"]
    if not isinstance(version, str) or not version.replace(".", "").isdigit() or code < 1:
        raise ValueError("APK version metadata is invalid.")
    filename = element["outputFile"]
    if Path(filename).name != filename or not filename.endswith(".apk"):
        raise ValueError("APK filename is invalid.")
    apk = build / filename
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        if "assets/www/mobile.html" not in names:
            raise ValueError("Bundled Android UI is missing.")
        for abi in ("arm64-v8a", "x86_64"):
            if f"lib/{abi}/libcuplik-whisper.so" not in names:
                raise ValueError(f"Native engine is missing for {abi}.")
        forbidden = (".p12", ".jks", ".keystore", ".f32", ".wav", ".mp4", ".bin")
        if any(name.lower().endswith(forbidden) for name in names):
            raise ValueError("APK includes a private key, model or test media asset.")
    fingerprint = certificate.read_text().strip()
    if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
        raise ValueError("Signing certificate fingerprint is invalid.")
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"cuplik-{version}.apk"
    shutil.copyfile(apk, target)
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (output / f"{target.name}.sha256").write_text(f"{digest}  {target.name}\n")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    (output / "build-info.json").write_text(
        json.dumps(
            {
                "application_id": "app.cuplik",
                "version": version,
                "version_code": code,
                "commit": commit,
                "apk": target.name,
                "sha256": digest,
                "certificate_sha256": fingerprint,
                "abis": ["arm64-v8a", "x86_64"],
            },
            indent=2,
        )
        + "\n"
    )
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    args = parser.parse_args()
    print(package(args.build, args.output, args.certificate))


if __name__ == "__main__":
    main()
