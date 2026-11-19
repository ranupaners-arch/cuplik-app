"""Opt-in deterministic camera-motion validation over a supplied licensed portrait photo."""

import argparse
import json
import math
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", type=Path, required=True)
    parser.add_argument("--directory", type=Path, default=Path("data/phase3-validation/tracking"))
    args = parser.parse_args()
    os.environ["RENDER_HEIGHT"] = "640"
    from api.app.config import ROOT, get_settings
    from api.app.models import Clip
    from api.app.schemas import Transcript
    from worker.pipeline.media import run
    from worker.pipeline.render import render_clip

    get_settings.cache_clear()
    args.directory.mkdir(parents=True, exist_ok=True)
    directory = args.directory.resolve()
    photo = cv2.imread(str(args.photo))
    if photo is None:
        raise SystemExit("Foto tidak dapat dibaca")
    model = ROOT / "worker/assets/yunet/face_detection_yunet_2026may.onnx"
    detector = cv2.FaceDetectorYN.create(
        str(model), "", (photo.shape[1], photo.shape[0]), 0.85, 0.3, 100
    )
    _, faces = detector.detect(photo)
    if faces is None:
        raise SystemExit("Fixture memerlukan satu wajah yang terdeteksi")
    x, y, w, h = (float(v) for v in max(faces, key=lambda r: r[2] * r[3])[:4])
    left, right = max(0, round(x - 0.7 * w)), min(photo.shape[1], round(x + 1.7 * w))
    top, bottom = max(0, round(y - 0.4 * h)), min(photo.shape[0], round(y + 2 * h))
    patch = photo[top:bottom, left:right]
    patch = cv2.resize(patch, (round(patch.shape[1] * 600 / patch.shape[0]), 600))
    width, height, fps, duration = 1280, 720, 30, 24
    silent = directory / "motion-silent.mp4"
    encoder = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "pipe:0",
            "-c:v",
            "libx264",
            "-threads",
            "4",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(silent),
        ],
        stdin=subprocess.PIPE,
    )
    try:
        for i in range(duration * fps):
            frame = np.full((height, width, 3), 90, dtype=np.uint8)
            if i / fps < 21:
                px = round(
                    (width - patch.shape[1]) / 2
                    + 0.2 * width * math.sin(2 * math.pi * i / fps / 10)
                )
                frame[40:640, px : px + patch.shape[1]] = patch
            encoder.stdin.write(frame.tobytes())
        encoder.stdin.close()
        if encoder.wait(timeout=60):
            raise RuntimeError("Encoder fixture gagal")
    finally:
        if encoder.poll() is None:
            encoder.kill()
            encoder.wait()
    source = directory / "motion-source.mp4"
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(silent),
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=24",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ]
    )
    text = Transcript(
        sentences=[
            dict(
                id="s1",
                start=0,
                end=8,
                text="Uji pelacakan foto bergerak. Bukan rekaman percakapan.",
            ),
            dict(
                id="s2",
                start=8,
                end=21,
                text="Gerakan dibuat secara sintetis untuk menguji crop kamera.",
            ),
            dict(id="s3", start=21, end=24, text="Saat wajah hilang, bingkai utuh dipertahankan."),
        ]
    )
    clip = Clip(
        output_id="tracking-fixture",
        rank=1,
        start_s=0,
        end_s=24,
        topic="fixture",
        titles=["Uji gerakan", "Bagaimana crop mengikuti?"],
        hook_options=["Fixture pelacakan foto", "Uji fallback"],
        score=0,
        rubric={},
        reason="Fixture teknik, bukan penilaian konten",
        layout="auto",
        retention={"zoom": False, "emphasis": False},
    )
    path, qc = render_clip(source, clip, text, directory)
    data = json.loads((directory / "reframe" / f"{clip.id}.json").read_text())
    crops = [f["crop"][0] for f in data["frames"] if f["crop"]]
    assert qc["framing"]["mode"] == "subject_portrait", qc["framing"]
    assert crops and max(crops) - min(crops) > width * 0.2
    assert qc["tracking"]["detections"] >= 200
    assert qc["tracking"]["blur_frames"] > 0
    assert qc["thumbnail"]["face"]
    assert qc["passed"], qc["needs_review"]
    report = {
        "status": "passed",
        "fixture": "synthetic camera motion over a public-domain portrait; tone audio, no human speech",
        "photo": str(args.photo),
        "output": str(path),
        "crop_travel_pixels": max(crops) - min(crops),
        "qc": qc,
    }
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(path),
                "crop_travel_pixels": report["crop_travel_pixels"],
                "tracking": qc["tracking"],
                "qc_passed": qc["passed"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
