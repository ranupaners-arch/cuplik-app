"""Per-frame crop tracking, conservative target association and blurred context fallback."""

import math
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
from scenedetect import ContentDetector, FrameTimecode

from worker.pipeline.framing import Face, FramingPlan, even


def tracked_plan(plan: FramingPlan, requested: str) -> FramingPlan:
    samples = plan.observations
    if requested != "source" and plan.content_kind == "speaker" and plan.width > plan.height:
        single = [
            s
            for s in samples
            if len(s["faces"]) == 1 and s["faces"][0]["w"] * s["faces"][0]["h"] >= 0.035
        ]
        if len(single) / max(1, len(samples)) >= 0.85 and all(
            len(s["faces"]) <= 1 for s in samples
        ):
            plan.width = even(plan.height * 9 / 16)
            plan.mode = "subject_portrait"
            plan.crop = (0, 0, even(plan.source_height * 9 / 16), plan.source_height)
            plan.reason = "Pembicara tunggal dilacak per frame; kehilangan target memakai bingkai utuh dengan latar blur."
    return plan


def face_distance(a: Face, b: Face):
    return math.hypot(a.x + a.w / 2 - b.x - b.w / 2, a.y + a.h / 2 - b.y - b.h / 2)


class Tracker:
    def __init__(self, plan: FramingPlan):
        self.plan = plan
        self.detector = None
        if plan.mode != "region_focus" and (
            plan.content_kind == "speaker" or plan.mode == "subject_portrait"
        ):
            model = (
                Path(__file__).resolve().parents[1]
                / "assets/yunet/face_detection_yunet_2026may.onnx"
            )
            self.detector = cv2.FaceDetectorYN.create(str(model), "", (640, 360), 0.85, 0.3, 100)
        self.scene = ContentDetector(threshold=27, min_scene_len=5)
        self.target = None
        self.center = None
        self.last_seen = None
        self.detected_faces = []
        self.frames = 0
        self.detections = 0
        self.focus_lost = False

    def detect(self, image):
        if self.detector is None:
            return []
        self.detector.setInputSize((image.shape[1], image.shape[0]))
        _, data = self.detector.detect(image)
        self.detections += 1
        if data is None:
            return []
        return [
            Face(
                max(0, float(r[0] / image.shape[1])),
                max(0, float(r[1] / image.shape[0])),
                float(r[2] / image.shape[1]),
                float(r[3] / image.shape[0]),
            )
            for r in data
        ]

    def update(self, frame, index: int, time: float, *, reset=False):
        self.frames += 1
        factor = min(1, 640 / frame.shape[1])
        small = cv2.resize(frame, (round(frame.shape[1] * factor), round(frame.shape[0] * factor)))
        scene_cut = bool(self.scene.process_frame(FrameTimecode(index, 30.0), small)) or reset
        if scene_cut:
            self.target, self.center, self.last_seen = None, None, None
            if index > 0 and self.plan.focus.get("requested") == "activity":
                self.focus_lost = True
        if index % 3 == 0 or scene_cut:
            faces = self.detect(small)
            self.detected_faces = faces
            if self.target is None and self.last_seen is None:
                self.target = max(faces, key=lambda f: f.w * f.h, default=None)
            elif self.target is not None and faces:
                matched = min(faces, key=lambda f: face_distance(f, self.target))
                if face_distance(matched, self.target) < max(0.12, self.target.w):
                    self.target = matched
                else:
                    matched = None
                if matched is None:
                    faces = []
            if self.target is not None and faces:
                self.last_seen = time
        width = self.plan.crop[2] if self.plan.crop else self.plan.source_width
        desired = (
            (self.target.x + self.target.w / 2) * self.plan.source_width
            if self.target
            else self.plan.source_width / 2
        )
        if self.center is None:
            self.center = desired
        elif abs(desired - self.center) > 0.08 * width:
            self.center += 0.15 * (desired - self.center)
        lost = self.last_seen is None or time - self.last_seen > 2
        mode = (
            "blur_fit"
            if self.plan.mode == "portrait_fit" or (self.plan.mode == "subject_portrait" and lost)
            else self.plan.mode
        )
        if self.focus_lost:
            mode = "blur_fit" if self.plan.width < self.plan.height else "source"
        return {
            "mode": mode,
            "center": self.center,
            "face": self.target if not lost else None,
            "scene_cut": scene_cut,
        }


def compose(frame, plan: FramingPlan, state: dict, zoom: float, *, captions: bool, hook: bool):
    top = even(plan.height * 0.1) if hook else 0
    bottom = even(plan.height * 0.12) if captions else 0
    available = plan.height - top - bottom
    face, crop, mode = state["face"], None, state["mode"]
    if mode == "region_focus":
        crop, zoom = list(plan.crop), 1
    if mode == "subject_portrait":
        base_width = min(plan.source_width, even(plan.source_height * 9 / 16))
        if face:
            zoom = min(zoom, base_width / max(1, face.w * plan.source_width * 1.24))
        zoom = max(1, zoom)
        width, height = even(base_width / zoom), even(plan.source_height / zoom)
        x = max(0, min(plan.source_width - width, round(state["center"] - width / 2)))
        y = (plan.source_height - height) // 2
        if face:
            left, right = (
                (face.x - 0.12 * face.w) * plan.source_width,
                (face.x + 1.12 * face.w) * plan.source_width,
            )
            upper, lower = (
                (face.y - 0.12 * face.h) * plan.source_height,
                (face.y + 1.12 * face.h) * plan.source_height,
            )
            if right - left > width or lower - upper > height:
                mode = "blur_fit"
            else:
                x = round(max(0, min(plan.source_width - width, min(max(x, right - width), left))))
                y = round(
                    max(0, min(plan.source_height - height, min(max(y, lower - height), upper)))
                )
        if mode == "subject_portrait":
            crop = [x, y, width, height]
    if crop:
        x, y, width, height = crop
        foreground = frame[y : y + height, x : x + width]
    else:
        foreground = frame
    if mode == "blur_fit":
        scale = max(plan.width / frame.shape[1], plan.height / frame.shape[0])
        large = cv2.resize(
            frame, (math.ceil(frame.shape[1] * scale), math.ceil(frame.shape[0] * scale))
        )
        y, x = (large.shape[0] - plan.height) // 2, (large.shape[1] - plan.width) // 2
        background = large[y : y + plan.height, x : x + plan.width]
        small = cv2.resize(background, (max(2, plan.width // 3), max(2, plan.height // 3)))
        blurred = cv2.GaussianBlur(small, (0, 0), 40 / 3)
        canvas = (cv2.resize(blurred, (plan.width, plan.height)) * 0.7).astype(np.uint8)
    else:
        canvas = np.full((plan.height, plan.width, 3), 16, dtype=np.uint8)
    scale = min(plan.width / foreground.shape[1], available / foreground.shape[0])
    width, height = even(foreground.shape[1] * scale), even(foreground.shape[0] * scale)
    x, y = (plan.width - width) // 2, top + (available - height) // 2
    canvas[y : y + height, x : x + width] = cv2.resize(
        foreground, (width, height), interpolation=cv2.INTER_LANCZOS4
    )
    if top:
        canvas[:top] = 16
    if bottom:
        canvas[-bottom:] = 16
    return canvas, {
        "mode": mode,
        "crop": crop,
        "zoom": zoom if crop else 1,
        "scene_cut": state["scene_cut"],
        "face": asdict(face) if face else None,
        "content_box": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "caption_band": bottom,
            "hook_band": top,
        },
    }
