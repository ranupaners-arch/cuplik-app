import json
import subprocess

import numpy as np
import pytest
from sqlmodel import Session

from api.app.db import get_engine
from api.app.models import Beat, Chapter
from api.app.schemas import OutputSettings
from worker.pipeline.condense_policy import speed_limit, validate_speed
from worker.pipeline.render import render_condensed
from worker.pipeline.solver import InfeasibleDuration, solve
from worker.pipeline.storage import output_dir
from worker.runner import run_output


def beat(identifier, start, end, **kwargs):
    return Beat(
        id=identifier,
        output_id="o",
        chapter_id="c",
        sentence_id="s" + identifier,
        start_s=start,
        end_s=end,
        text="Narasi.",
        required=True,
        **kwargs,
    )


def chapter():
    return Chapter(
        id="c",
        output_id="o",
        order=1,
        title="Langkah",
        goal="Utuh",
        importance="core",
        required=True,
    )


def settings(**changes):
    return OutputSettings(timelapse_enabled=True, **changes)


def test_solver_prefers_reviewed_visual_speed_and_keeps_narration_natural():
    beats = [
        beat("1", 0, 2),
        beat("2", 2, 10, kind="visual", label="manual", timelapse_approved=True),
        beat("3", 10, 12),
    ]
    plan = solve(beats, [chapter()], 6, 1.15, settings=settings())
    assert plan["within_tolerance"] and plan["actual_duration_s"] == 6
    assert [b["speed"] for b in plan["beats"]] == [1, 4, 1]
    assert [b["audio_mode"] for b in plan["beats"]] == ["source", "muted", "source"]
    assert [b.speed for b in beats] == [1, 1, 1], (
        "Solver must not mutate a failed or previewed plan"
    )


def test_unreviewed_and_protected_visual_cannot_become_timelapse():
    raw = beat("1", 0, 12, kind="visual", label="manual")
    with pytest.raises(InfeasibleDuration):
        solve([raw], [chapter()], 3, 1.15, settings=settings())
    for changes in [
        {"label": "spec"},
        {"label": "step"},
        {"label": "result"},
        {"evidence": {"specs": ["120 mm"]}},
    ]:
        protected = raw.model_copy(update={"timelapse_approved": True, **changes})
        with pytest.raises(ValueError):
            validate_speed(protected, 4, settings())
    result = beat("2", 0, 2, kind="visual", label="result")
    assert speed_limit(result, settings()) == 1
    assert (
        solve(
            [raw.model_copy(update={"timelapse_approved": True})],
            [chapter()],
            3,
            1.15,
            settings=settings(),
        )["beats"][0]["speed"]
        == 4
    )


def test_locked_choices_minimum_and_density_priority_are_respected():
    core = beat("1", 0, 2, locked=True, decision="keep")
    visual = beat(
        "2",
        2,
        10,
        kind="visual",
        label="manual",
        timelapse_approved=True,
        locked=True,
        decision="speed",
        speed=4,
    )
    assert (
        solve([core, visual], [chapter()], 4, 1.15, settings=settings())["actual_duration_s"] == 4
    )
    with pytest.raises(InfeasibleDuration) as exc:
        solve([core, visual], [chapter()], 3, 1.15, settings=settings())
    assert exc.value.minimum_seconds == 4
    optional = [
        beat("3", 10, 14).model_copy(update={"required": False, "importance": 0.1}),
        beat("4", 14, 18).model_copy(update={"required": False, "importance": 0.9}),
    ]
    selected = solve([core, *optional], [chapter()], 6, 1.15)
    assert selected["minimum_seconds"] == 2
    assert next(b for b in selected["beats"] if b["id"] == "4")["decision"] == "keep"
    assert next(b for b in selected["beats"] if b["id"] == "3")["decision"] == "drop"


@pytest.mark.parametrize("rate", [2, 4, 8])
def test_real_timelapse_render_has_silent_audio_badge_and_actual_timeline(
    client, video, tmp_path, rate
):
    b = beat(
        "1",
        0,
        12,
        kind="visual",
        label="manual",
        timelapse_approved=True,
        decision="speed",
        speed=rate,
    )
    directory = tmp_path / f"render-{rate}"
    directory.mkdir()
    path = render_condensed(video, [b], directory, False, lambda *_: None, settings=settings())
    timeline = json.loads((directory / "condensed.timeline.json").read_text())
    assert abs(timeline["duration_s"] - 12 / rate) < 0.05
    assert timeline["spans"][0]["audio_mode"] == "muted" and timeline["spans"][0]["speed"] == rate
    decoded = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            "16000",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    samples = np.frombuffer(decoded.stdout, dtype="<f4")
    assert samples.size > 1000 and np.max(np.abs(samples)) < 1e-6
    assert any(f"CEPAT {rate}x - AUDIO HENING" in p.read_text() for p in directory.glob("*.ass"))


def gap_output(client, video):
    data = video.read_bytes()
    upload = client.post(
        "/api/uploads", json={"filename": "gap.mp4", "total_bytes": len(data)}
    ).json()
    client.put(f"/api/uploads/{upload['id']}?offset=0", content=data)
    project = client.post(
        "/api/projects",
        json={
            "source_kind": "upload",
            "upload_id": upload["id"],
            "transcript": {
                "sentences": [
                    {"id": "s1", "start": 0, "end": 2, "text": "Siapkan alat."},
                    {"id": "s2", "start": 10, "end": 12, "text": "Tinjau hasil."},
                ]
            },
        },
    ).json()
    output = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={"mode": "condense", "settings": {"condense_vision": {"enabled": True}}},
    ).json()
    run_output(output["id"])
    return output["id"], client.get(f"/api/outputs/{output['id']}").json()


def test_api_review_approval_speed_guards_and_render_reuse_llm_plan(client, video):
    identifier, detail = gap_output(client, video)
    visual = next(b for b in detail["beats"] if b["kind"] == "visual")
    narration = next(b for b in detail["beats"] if b["kind"] == "speech")
    url = f"/api/beats/{visual['id']}"
    assert (
        client.patch(
            url, json={"decision": "speed", "speed": 4, "timelapse_approved": True}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            url, json={"decision": "keep", "locked": False, "timelapse_approved": True}
        ).status_code
        == 200
    )
    preview = client.post(
        f"/api/outputs/{identifier}/solve", json={"target_seconds": 6, "timelapse_enabled": True}
    )
    assert preview.status_code == 200 and preview.json()["muted_timelapse_beats"] == 1
    assert (
        client.patch(
            f"/api/beats/{narration['id']}",
            json={"decision": "speed", "speed": 4, "timelapse_approved": True},
        ).status_code
        == 422
    )
    assert client.patch(url, json={"decision": "speed", "speed": 8}).status_code == 422
    assert (
        client.patch(url, json={"decision": "speed", "speed": 4, "locked": True}).status_code == 200
    )
    before = (output_dir(identifier) / "llm_log.jsonl").read_bytes()
    chapters = [{"id": c["id"], "required": True} for c in detail["chapters"]]
    assert (
        client.put(
            f"/api/outputs/{identifier}/outline", json={"chapters": chapters, "target_seconds": 6}
        ).status_code
        == 202
    )
    run_output(identifier, render_only=True)
    fresh = client.get(f"/api/outputs/{identifier}").json()
    assert (
        fresh["output"]["status"] == "done" and abs(fresh["output"]["actual_duration_s"] - 6) < 0.15
    )
    assert (output_dir(identifier) / "llm_log.jsonl").read_bytes() == before
    with Session(get_engine()) as session:
        assert session.get(Beat, visual["id"]).timelapse_approved
