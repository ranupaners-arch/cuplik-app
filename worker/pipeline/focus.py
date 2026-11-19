"""Opt-in spatial focus: explicit human rectangles or conservative local activity proposals."""

import math

import cv2
import numpy as np

from api.app.schemas import FocusRegion, VisualFocus
from worker.pipeline.framing import even


def propose_activity(frames: list[np.ndarray]):
    if len(frames) < 6:
        return None, "Sampel gambar belum cukup untuk memilih area aktivitas."
    masks = []
    for previous, current in zip(frames, frames[1:], strict=False):
        changed = cv2.absdiff(previous, current) > 20
        if np.mean(changed) > 0.45:
            return None, "Perubahan adegan terlalu besar; bingkai utuh dipertahankan."
        masks.append(changed)
    votes = np.sum(masks, axis=0)
    persistent = (votes >= max(2, math.ceil(len(masks) * 0.12))).astype(np.uint8)
    if np.mean(persistent) < 0.0005:
        return None, "Aktivitas visual belum cukup jelas; bingkai utuh dipertahankan."
    h, w = persistent.shape
    kernel = np.ones((max(3, round(h * 0.025)), max(3, round(w * 0.025))), np.uint8)
    grouped = cv2.dilate(persistent, kernel)
    _, _, stats, _ = cv2.connectedComponentsWithStats(grouped)
    components = sorted(stats[1:], key=lambda s: s[4], reverse=True)
    if not components:
        return None, "Area aktivitas belum ditemukan."
    # A moving object often produces disconnected leading/trailing edges. Keep
    # nearby edges together, but reject activity spread across separate regions.
    significant = [s for s in components if s[4] >= components[0][4] * 0.3]
    x, y = min(s[0] for s in significant), min(s[1] for s in significant)
    width = max(s[0] + s[2] for s in significant) - x
    height = max(s[1] + s[3] for s in significant) - y
    if len(significant) > 1 and (width / w > 0.45 or height / h > 0.6):
        return None, "Ada beberapa area aktivitas yang bersaing; bingkai utuh dipertahankan."
    center_x, center_y = (x + width / 2) / w, (y + height / 2) / h
    width, height = max(width / w + 0.18, 0.3), max(height / h + 0.18, 0.3)
    if width * height > 0.55 or width > 0.9 or height > 0.9:
        return None, "Aktivitas tersebar terlalu luas untuk crop yang aman."
    return FocusRegion(
        x=max(0, min(1 - width, center_x - width / 2)),
        y=max(0, min(1 - height, center_y - height / 2)),
        width=width,
        height=height,
    ), "Satu area aktivitas lokal konsisten pada sampel. Periksa apakah konteks tugas tetap utuh."


def activity_region(source, start, end):
    capture = cv2.VideoCapture(str(source))
    frames = []
    try:
        for time in np.linspace(
            start, max(start, end - 0.05), min(24, max(6, math.ceil((end - start) * 2)))
        ):
            capture.set(cv2.CAP_PROP_POS_MSEC, float(time) * 1000)
            ok, frame = capture.read()
            if not ok:
                continue
            factor = min(1, 640 / max(frame.shape[:2]))
            image = cv2.resize(
                frame,
                (max(2, round(frame.shape[1] * factor)), max(2, round(frame.shape[0] * factor))),
            )
            frames.append(cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (5, 5), 0))
    finally:
        capture.release()
    region, reason = propose_activity(frames)
    return region, reason, len(frames)


def apply_focus(plan, source, start, end, options: VisualFocus):
    if options.mode == "safe":
        return plan
    region, samples = options.region, 0
    reason = "Area fokus dipilih pengguna. Tinjau seluruh rentang klip setelah crop."
    if options.mode == "activity":
        try:
            region, reason, samples = activity_region(source, start, end)
        except (cv2.error, OSError, ValueError):
            region, reason = None, "Analisis aktivitas gagal; pembingkaian aman dipakai kembali."
    plan.focus = {
        "requested": options.mode,
        "applied": region is not None,
        "reason": reason,
        "samples": samples,
        "method": "human_rectangle" if options.mode == "manual" else "local_frame_difference_v1",
        "semantic_object_detection": False,
    }
    if region is None:
        return plan
    left = max(0, int(region.x * plan.source_width) // 2 * 2)
    top = max(0, int(region.y * plan.source_height) // 2 * 2)
    right = min(plan.source_width, even((region.x + region.width) * plan.source_width))
    bottom = min(plan.source_height, even((region.y + region.height) * plan.source_height))
    plan.mode, plan.crop = "region_focus", (left, top, max(2, right - left), max(2, bottom - top))
    plan.focus["region"] = region.model_dump()
    plan.reason = reason
    return plan
