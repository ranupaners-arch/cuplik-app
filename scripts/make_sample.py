from api.app.config import ROOT
from worker.pipeline.media import run

path = ROOT / "examples/sample.mp4"
run(
    [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x180:rate=24:duration=12",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=12",
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
print(f"Video uji sintetis: {path}\nSidecar: {ROOT / 'examples/transcript.json'}")
