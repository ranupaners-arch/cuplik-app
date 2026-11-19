"""Conservative local visual analysis: preserve context unless a crop is demonstrably safe."""

from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

from api.app.config import get_settings
from worker.pipeline.media import probe_file

VERSION = 1


def even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


@dataclass
class Face:
    x: float
    y: float
    w: float
    h: float


@dataclass
class Observation:
    time: float
    faces: list[Face]
    text_components: int
    edge_density: float


@dataclass
class FramingPlan:
    source_width: int
    source_height: int
    width: int
    height: int
    mode: str
    content_kind: str
    reason: str
    crop: tuple[int, int, int, int] | None = None  # x, y, width, height
    observations: list[dict] = field(default_factory=list)
    analyzer: str = (
        "OpenCV YuNet 2026may neural face detector + text/edge heuristics; local, no cloud LLM"
    )
    focus: dict = field(default_factory=dict)

    def model_dump(self):
        return asdict(self)


def observations(source: Path, start: float, end: float, stream: dict):
    capture = cv2.VideoCapture(str(source))
    model = Path(__file__).resolve().parents[1] / "assets/yunet/face_detection_yunet_2026may.onnx"
    detector = cv2.FaceDetectorYN.create(str(model), "", (320, 320), 0.85, 0.3, 100)
    samples = []
    width, height = int(stream["width"]), int(stream["height"])
    try:
        for time in np.linspace(
            start, max(start, end - 0.05), min(24, max(6, int(end - start) + 1))
        ):
            capture.set(cv2.CAP_PROP_POS_MSEC, float(time) * 1000)
            ok, frame = capture.read()
            if not ok:
                continue
            height, width = frame.shape[:2]
            factor = min(1, 640 / width)
            image = cv2.resize(frame, (round(width * factor), round(height * factor)))
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            detector.setInputSize((image.shape[1], image.shape[0]))
            _, predictions = detector.detect(image)
            faces = []
            if predictions is not None:
                for row in predictions:
                    x, y, w, h = (float(v) for v in row[:4])
                    left, top = max(0, x / image.shape[1]), max(0, y / image.shape[0])
                    right, bottom = (
                        min(1, (x + w) / image.shape[1]),
                        min(1, (y + h) / image.shape[0]),
                    )
                    if right > left and bottom > top:
                        faces.append(Face(left, top, right - left, bottom - top))
            edges = cv2.Canny(gray, 80, 180)
            # Many small connected components are a text/interface hint, not OCR.
            _, binary = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY_INV)
            _, _, stats, _ = cv2.connectedComponentsWithStats(binary)
            count = sum(
                2 <= w <= 32 and 3 <= h <= 18 and 5 <= area <= 400 for _, _, w, h, area in stats[1:]
            )
            samples.append(Observation(float(time), faces, int(count), float(np.mean(edges > 0))))
    finally:
        capture.release()
    # FFmpeg and OpenCV both apply video rotation. Account for non-square source pixels.
    sar = stream.get("sample_aspect_ratio", "1:1")
    try:
        a, b = (float(v) for v in sar.split(":"))
        pixel_ratio = a / b if a and b else 1
    except (ValueError, ZeroDivisionError):
        pixel_ratio = 1
    if (width, height) == (stream.get("height"), stream.get("width")):
        pixel_ratio = 1 / pixel_ratio
    return even(width * pixel_ratio), even(height), samples


def choose_framing(
    width: int,
    height: int,
    samples: list[Observation],
    requested="auto",
    maximum_height: int | None = None,
) -> FramingPlan:
    maximum_height = maximum_height or get_settings().render_height
    source_aspect = width / height
    output_height = even(min(height, maximum_height))
    output_width = even(output_height * source_aspect)
    text_votes = sum(s.text_components >= 32 and s.edge_density >= 0.025 for s in samples)
    dominant = [
        s.faces[0] for s in samples if len(s.faces) == 1 and s.faces[0].w * s.faces[0].h >= 0.035
    ]
    is_screen = source_aspect > 1.2 and bool(samples) and text_votes / len(samples) >= 0.35
    content = "screen_or_slides" if is_screen else "speaker" if dominant else "context"
    mode, crop = "source", None
    reason = "Pertahankan seluruh bingkai: subjek tunggal belum terdeteksi dengan cukup yakin."
    if is_screen:
        reason = "Teks/antarmuka perlu konteks lebar; orientasi sumber dipertahankan agar detail terbaca."
    elif source_aspect <= 0.7:
        reason = "Sumber sudah vertikal; pertahankan seluruh bingkai."
    elif (
        dominant
        and len(dominant) / max(1, len(samples)) >= 0.85
        and all(len(s.faces) <= 1 for s in samples)
    ):
        crop_width = even(height * 9 / 16)
        center = float(np.median([(face.x + face.w / 2) * width for face in dominant]))
        x = even(max(0, min(width - crop_width, center - crop_width / 2)))
        x = min(x, width - crop_width)
        # Every sampled face, with a margin, must fit; multiple speakers/scene changes preserve context.
        safe = crop_width < width and all(
            x <= (face.x - 0.12 * face.w) * width
            and (face.x + 1.12 * face.w) * width <= x + crop_width
            for face in dominant
        )
        if safe:
            mode, crop = "subject_portrait", (x, 0, crop_width, height)
            output_width = even(output_height * 9 / 16)
            reason = "Satu wajah dominan stabil pada sampel; crop vertikal mempertahankan wajah beserta margin."
    if requested == "source":
        mode, crop = "source", None
        output_width = even(output_height * source_aspect)
        reason = "Bingkai utuh dipilih pengguna."
    elif requested == "portrait":
        if mode != "subject_portrait":
            mode, crop = "portrait_fit", None
            reason = "Vertikal dipilih pengguna; seluruh sumber dimuat tanpa crop jika subjek belum aman."
        output_width = even(output_height * 9 / 16)
    elif is_screen:
        mode, crop = "source", None
        output_width = even(output_height * source_aspect)
    return FramingPlan(
        width,
        height,
        output_width,
        output_height,
        mode,
        content,
        reason,
        crop,
        [asdict(s) for s in samples],
    )


def analyze_framing(source: Path, start: float, end: float, requested="auto") -> FramingPlan:
    stream = next(s for s in probe_file(source)["streams"] if s.get("codec_type") == "video")
    width, height, samples = observations(source, start, end, stream)
    return choose_framing(width, height, samples, requested)


def video_filter(plan: FramingPlan, *, captions: bool, hook: bool):
    """Reserve separate text bands so captions never cover source UI or faces."""
    top = even(plan.height * 0.10) if hook else 0
    bottom = even(plan.height * 0.12) if captions else 0
    available = plan.height - top - bottom
    source_width, source_height = (
        (plan.crop[2], plan.crop[3]) if plan.crop else (plan.source_width, plan.source_height)
    )
    scale = min(plan.width / source_width, available / source_height)
    foreground_width, foreground_height = even(source_width * scale), even(source_height * scale)
    x, y = (plan.width - foreground_width) // 2, top + (available - foreground_height) // 2
    filters = [f"scale={plan.source_width}:{plan.source_height}:flags=lanczos", "setsar=1"]
    if plan.crop:
        cx, cy, cw, ch = plan.crop
        filters.append(f"crop={cw}:{ch}:{cx}:{cy}")
    filters.extend(
        [
            f"scale={foreground_width}:{foreground_height}:flags=lanczos",
            f"pad={plan.width}:{plan.height}:{x}:{y}:color=0x101010",
            "setsar=1",
        ]
    )
    return filters, {
        "x": x,
        "y": y,
        "width": foreground_width,
        "height": foreground_height,
        "caption_band": bottom,
        "hook_band": top,
    }
