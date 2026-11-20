import json
import zipfile

import pytest

from scripts.package_android import package


def build(tmp_path, extra=None):
    source = tmp_path / "build"
    source.mkdir()
    (source / "output-metadata.json").write_text(
        json.dumps(
            {
                "applicationId": "app.cuplik",
                "elements": [
                    {"versionName": "0.5.0", "versionCode": 5, "outputFile": "app-release.apk"}
                ],
            }
        )
    )
    with zipfile.ZipFile(source / "app-release.apk", "w") as archive:
        for name in [
            "assets/www/mobile.html",
            "lib/arm64-v8a/libcuplik-whisper.so",
            "lib/x86_64/libcuplik-whisper.so",
        ] + (extra or []):
            archive.writestr(name, b"fixture")
    cert = tmp_path / "certificate"
    cert.write_text("a" * 64)
    return source, cert


def test_versioned_artifact_records_commit_and_certificate(tmp_path):
    source, certificate = build(tmp_path)
    output = tmp_path / "output"
    apk = package(source, output, certificate)
    info = json.loads((output / "build-info.json").read_text())
    assert apk.name == "cuplik-0.5.0.apk"
    assert info["version_code"] == 5
    assert len(info["commit"]) == 40
    assert info["certificate_sha256"] == "a" * 64
    assert (output / f"{apk.name}.sha256").read_text().startswith(info["sha256"])


@pytest.mark.parametrize("asset", ["assets/ggml-tiny.bin", "assets/source.mp4", "assets/key.p12"])
def test_model_test_media_and_private_keys_cannot_ship(tmp_path, asset):
    source, certificate = build(tmp_path, [asset])
    with pytest.raises(ValueError, match="private key, model or test media"):
        package(source, tmp_path / "output", certificate)
