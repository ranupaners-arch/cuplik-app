from pathlib import Path

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from api.app.models import Clip
from api.app.schemas import FocusRegion, VisualFocus
from worker.pipeline.focus import apply_focus, propose_activity
from worker.pipeline.framing import choose_framing
from worker.pipeline.reframe import Tracker, compose
from worker.pipeline.render import clip_fingerprint


def clip(**changes):
    return Clip(
        output_id="test",
        rank=1,
        start_s=0,
        end_s=3,
        topic="test",
        titles=["A", "B"],
        hook_options=["C", "D"],
        score=8,
        rubric={},
        reason="Fixture",
        **changes,
    )


def activity_frames(two=False, scene=False):
    frames = []
    for i in range(12):
        frame = np.zeros((180, 320), dtype=np.uint8)
        cv2.rectangle(frame, (95 + i % 4 * 5, 65), (145 + i % 4 * 5, 105), 255, -1)
        if two:
            cv2.rectangle(frame, (230 + i % 4 * 5, 65), (280 + i % 4 * 5, 105), 255, -1)
        if scene and i >= 6:
            frame[:] = 255
        frames.append(frame)
    return frames


def test_local_activity_is_opt_in_and_ambiguous_or_static_images_fall_back():
    region, _ = propose_activity(activity_frames())
    assert region is not None and region.x + region.width <= 1
    assert region.width * region.height <= 0.55
    assert propose_activity(activity_frames(two=True))[0] is None
    assert propose_activity(activity_frames(scene=True))[0] is None
    assert propose_activity([np.zeros((180, 320), dtype=np.uint8)] * 8)[0] is None


def test_manual_focus_keeps_requested_region_instead_of_following_faces():
    plan = choose_framing(320, 180, [], "portrait", 320)
    options = VisualFocus(mode="manual", region=FocusRegion(x=0.25, y=0.25, width=0.5, height=0.5))
    apply_focus(plan, Path("unused"), 0, 3, options)
    tracker = Tracker(plan)
    assert tracker.detector is None
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    frame[44:136, 80:240] = (0, 255, 0)
    state = tracker.update(frame, 0, 0, reset=True)
    _, meta = compose(frame, plan, state, 1.12, captions=True, hook=False)
    assert meta["mode"] == "region_focus" and meta["zoom"] == 1
    assert meta["crop"] == list(plan.crop)
    assert (
        meta["content_box"]["y"] + meta["content_box"]["height"]
        <= plan.height - meta["content_box"]["caption_band"]
    )


def test_activity_crop_abandons_region_after_scene_or_edit_cut():
    plan = choose_framing(320, 180, [], "portrait", 320)
    plan.mode, plan.crop = "region_focus", (80, 44, 160, 92)
    plan.focus = {"requested": "activity", "applied": True}
    tracker = Tracker(plan)
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    assert tracker.update(frame, 0, 0, reset=True)["mode"] == "region_focus"
    assert tracker.update(frame, 30, 1, reset=True)["mode"] == "blur_fit"


def test_failed_analysis_keeps_plan_and_safe_mode_preserves_legacy_fingerprint(monkeypatch):
    plan = choose_framing(320, 180, [], "portrait", 320)
    monkeypatch.setattr(
        "worker.pipeline.focus.activity_region",
        lambda *_: (_ for _ in ()).throw(cv2.error("fixture")),
    )
    apply_focus(plan, Path("unused"), 0, 3, VisualFocus(mode="activity"))
    assert plan.crop is None and not plan.focus["applied"]
    original = clip()
    safe = clip(visual_focus={"mode": "safe"})
    manual = clip(
        visual_focus={
            "mode": "manual",
            "region": {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
        }
    )
    assert clip_fingerprint(original) == clip_fingerprint(safe)
    assert clip_fingerprint(original) != clip_fingerprint(manual)
    with pytest.raises(ValidationError):
        VisualFocus(mode="manual", region=FocusRegion(x=0.9, y=0, width=0.5, height=1))
