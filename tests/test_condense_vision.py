import base64
import io
import json

import httpx
import pytest
from PIL import Image

from api.app.config import get_settings
from api.app.schemas import Transcript
from worker.pipeline.beats import (
    MotionReport,
    MotionSample,
    analyze_motion,
    build_beats,
    frame_schedule,
)
from worker.pipeline.llm import LLMClient, LLMImage, LLMValidationError
from worker.pipeline.storage import output_dir, project_dir
from worker.pipeline.vision import (
    BeatAnnotations,
    BeatOutline,
    FrameDescriptions,
    exact_ids,
    validate_annotations,
    validate_beat_outline,
)
from worker.runner import run_output


def motion(duration=50, cuts=None):
    return MotionReport(
        fingerprint="fixture",
        duration_s=duration,
        samples=[MotionSample(time_s=i / 2, activity=0.2) for i in range(int(duration * 2))],
        cuts=cuts or [],
    )


def test_visual_gaps_are_split_at_sampled_cuts_and_twenty_seconds_without_overlap():
    transcript = Transcript(
        sentences=[
            {"id": "s1", "start": 0.5, "end": 2.5, "text": "Pasang alat."},
            {"id": "s2", "start": 30, "end": 32, "text": "Hasilnya selesai."},
        ]
    )
    beats = build_beats(transcript, 50, motion(cuts=[5, 27]))
    assert [(b.start_s, b.end_s) for b in beats if b.kind == "visual"] == [
        (2.5, 5),
        (5, 25),
        (25, 27),
        (27, 30),
        (32, 50),
    ]
    assert all(a.end_s <= b.start_s for a, b in zip(beats, beats[1:], strict=False))
    assert all(b.text == "" and b.sentence_id == "" for b in beats if b.kind == "visual")
    assert all(0 <= b.activity <= 1 for b in beats)
    assert [b.id for b in beats] == [f"b{i + 1}" for i in range(len(beats))]
    schedule = frame_schedule(beats, 100)
    assert all(
        next(b.start_s <= f["time_s"] < b.end_s for b in beats if b.id == f["beat_id"])
        for f in schedule
    )
    with pytest.raises(ValueError, match="belum ada permintaan LLM"):
        frame_schedule(beats, 1)


def test_motion_analysis_uses_real_media_and_reuses_verified_cache(client, project, monkeypatch):
    from worker.pipeline.ingest import ingest_project

    ingest_project(project["id"])
    directory = project_dir(project["id"])
    result = analyze_motion(directory, 12)
    assert len(result.samples) == 24
    assert all(0 <= s.activity <= 1 for s in result.samples)
    monkeypatch.setattr(
        "worker.pipeline.beats.subprocess.Popen",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("cache must avoid decoding")),
    )
    assert analyze_motion(directory, 12) == result


@pytest.mark.parametrize("provider", ["gemini", "anthropic", "ollama"])
def test_multimodal_transport_sends_real_image_bytes_model_and_ids(client, monkeypatch, provider):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("LLM_MODEL_FAST", "text-model")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-never-log")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-never-log")
    get_settings.cache_clear()
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "green").save(buffer, "JPEG")
    jpeg = buffer.getvalue()
    result = {"frames": [{"id": "f1", "action": "Transport fixture", "uncertain": True}]}
    calls = []

    def respond(request):
        calls.append(request)
        body = json.loads(request.content)
        if provider == "gemini":
            assert "vision-model" in str(request.url)
            parts = body["contents"][0]["parts"]
            assert base64.b64decode(parts[-1]["inlineData"]["data"]) == jpeg
            assert "f1" in parts[-2]["text"]
            return httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(result)}]}}]}
            )
        assert body["model"] == "vision-model"
        if provider == "anthropic":
            blocks = body["messages"][0]["content"]
            assert blocks[0]["text"] == "Frame f1:"
            assert base64.b64decode(blocks[1]["source"]["data"]) == jpeg
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "tool_use", "name": "structured_result", "input": result}]
                },
            )
        assert base64.b64decode(body["messages"][1]["images"][0]) == jpeg
        return httpx.Response(200, json={"message": {"content": json.dumps(result)}})

    llm = LLMClient(transport=httpx.MockTransport(respond))
    actual = llm.call_json(
        "frame_describer",
        {"frames": [{"id": "f1"}], "language": "id"},
        FrameDescriptions,
        images=[LLMImage("f1", jpeg)],
        model="vision-model",
    )
    assert actual.frames[0].id == "f1" and len(calls) == 1
    assert llm.usage[0]["images"] == 1 and llm.usage[0]["model"] == "vision-model"
    assert "secret-never-log" not in json.dumps(llm.usage)
    assert base64.b64encode(jpeg).decode() not in json.dumps(llm.usage)


def test_invented_ids_specs_and_incomplete_chapters_fail_validation():
    frame = FrameDescriptions(frames=[{"id": "f99", "action": "unknown"}])
    with pytest.raises(LLMValidationError):
        exact_ids(frame.frames, ["f1"])
    batch = [{"id": "b1", "text": "Atur 1200 mm.", "frames": []}]
    annotation = BeatAnnotations(
        beats=[{"id": "b1", "label": "spec", "step_hint": "atur", "specs": ["120"]}]
    )
    with pytest.raises(LLMValidationError, match="verbatim"):
        validate_annotations(annotation, batch)
    annotation.beats[0].specs = ["1200 mm"]
    validate_annotations(annotation, batch)
    transcript = Transcript(sentences=[{"id": "s1", "start": 0, "end": 4, "text": "Langkah."}])
    beats = build_beats(transcript, 12, motion(12))
    plan = BeatOutline(
        chapters=[
            {
                "title": "Uji",
                "goal": "Uji",
                "start_id": "b1",
                "end_id": "b1",
                "required_beat_ids": ["b1"],
                "importance": "core",
            }
        ]
    )
    with pytest.raises(LLMValidationError, match="semua beat"):
        validate_beat_outline(plan, beats)


def gap_project(client, video, sentences=None):
    data = video.read_bytes()
    upload = client.post(
        "/api/uploads", json={"filename": "visual-gap.mp4", "total_bytes": len(data)}
    ).json()
    assert client.put(f"/api/uploads/{upload['id']}?offset=0", content=data).status_code == 200
    return client.post(
        "/api/projects",
        json={
            "source_kind": "upload",
            "upload_id": upload["id"],
            "transcript": {
                "sentences": sentences
                or [
                    {"id": "s1", "start": 0, "end": 2, "text": "Siapkan alat."},
                    {"id": "s2", "start": 10, "end": 12, "text": "Tunjukkan hasil."},
                ]
            },
        },
    ).json()


def test_visual_outline_review_frames_and_gap_render_preserve_source_audio_and_caption_scope(
    client, video
):
    project = gap_project(client, video)
    output = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={
            "mode": "condense",
            "settings": {
                "target_seconds": 12,
                "condense_vision": {"enabled": True, "screen_tutorial": True, "max_frames": 16},
            },
        },
    ).json()
    run_output(output["id"])
    detail = client.get(f"/api/outputs/{output['id']}").json()
    assert detail["output"]["status"] == "awaiting_review"
    visual = [b for b in detail["beats"] if b["kind"] == "visual"]
    assert visual and all(b["required"] and b["evidence"]["uncertain"] for b in visual)
    assert all(b["text"] == "" for b in visual)
    report = detail["vision_report"]
    assert report["provider"] == "mock" and report["frame_count"] >= 4
    for frame in report["frames"]:
        response = client.get(frame["url"])
        assert response.status_code == 200 and response.content[:2] == b"\xff\xd8"
        assert frame["width"] <= 1024 and frame["height"] <= 1024
    assert client.get(f"/api/outputs/{output['id']}/vision/frames/f999999").status_code == 404
    original_log = (output_dir(output["id"]) / "llm_log.jsonl").read_text()
    chapters = [{"id": c["id"], "required": True} for c in detail["chapters"]]
    assert (
        client.put(
            f"/api/outputs/{output['id']}/outline",
            json={"chapters": chapters, "target_seconds": 12},
        ).status_code
        == 202
    )
    run_output(output["id"], render_only=True)
    fresh = client.get(f"/api/outputs/{output['id']}").json()
    assert fresh["output"]["status"] == "done"
    assert abs(fresh["output"]["actual_duration_s"] - 12) < 0.2
    assert (output_dir(output["id"]) / "llm_log.jsonl").read_text() == original_log
    timeline = json.loads((output_dir(output["id"]) / "condensed.timeline.json").read_text())
    assert any(s["kind"] == "visual" and not s["sentence_id"] for s in timeline["spans"])
    for path in output_dir(output["id"]).glob("part-*.ass"):
        assert "Fixture vision" not in path.read_text()


def test_frame_budget_stops_before_llm_and_nested_defaults_remain_intact(
    client, video, monkeypatch
):
    defaults = client.get("/api/preferences").json()
    defaults["condense"]["condense_vision"] = {
        "enabled": True,
        "screen_tutorial": True,
        "max_frames": 100,
    }
    assert client.put("/api/preferences", json=defaults).status_code == 200
    project = gap_project(
        client,
        video,
        [
            {"id": f"s{i + 1}", "start": i * 0.5, "end": i * 0.5 + 0.2, "text": "Uji."}
            for i in range(17)
        ],
    )
    output = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={"mode": "condense", "settings": {"condense_vision": {"max_frames": 16}}},
    ).json()
    assert output["settings"]["condense_vision"] == {
        "enabled": True,
        "screen_tutorial": True,
        "max_frames": 16,
    }
    monkeypatch.setattr(
        LLMClient,
        "call_json",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("budget must be checked before LLM")
        ),
    )
    with pytest.raises(ValueError, match="melebihi batas"):
        run_output(output["id"])
    detail = client.get(f"/api/outputs/{output['id']}").json()
    assert detail["output"]["status"] == "failed" and detail["chapters"] == []
    assert not (output_dir(output["id"]) / "llm_log.jsonl").exists()


def test_retry_repairs_corrupt_sample_and_reuses_completed_paid_stages(client, video, monkeypatch):
    from worker.pipeline.llm import LLMError

    original = LLMClient.call_json
    calls = []
    failed = False

    def interrupted(self, name, *args, **kwargs):
        nonlocal failed
        calls.append(name)
        if name == "outline_builder" and not failed:
            failed = True
            raise LLMError("Fixture interrupted outline")
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(LLMClient, "call_json", interrupted)
    project = gap_project(client, video)
    output = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={"mode": "condense", "settings": {"condense_vision": {"enabled": True}}},
    ).json()
    with pytest.raises(LLMError, match="interrupted"):
        run_output(output["id"])
    directory = output_dir(output["id"])
    next((directory / "vision-frames").glob("*.jpg")).write_bytes(b"corrupt sample")
    metadata_path = next((directory / "vision-samples").glob("*/*.json"))
    metadata = json.loads(metadata_path.read_text())
    metadata["image_sha256"] = 123
    metadata_path.write_text(json.dumps(metadata))
    assert client.get(f"/api/outputs/{output['id']}").json()["chapters"] == []
    assert client.post(f"/api/outputs/{output['id']}/retry").status_code == 202
    run_output(output["id"])
    assert (
        client.get(f"/api/outputs/{output['id']}").json()["output"]["status"] == "awaiting_review"
    )
    assert calls.count("frame_describer") == 1
    assert calls.count("beat_annotator") == 1
    assert calls.count("outline_builder") == 2


def test_image_bytes_and_vision_model_change_cache_key(client, tmp_path, monkeypatch):
    from worker.pipeline.selection_cache import call_stage

    directory = tmp_path / "cache"
    directory.mkdir()

    def jpeg(color):
        target = io.BytesIO()
        Image.new("RGB", (8, 8), color).save(target, "JPEG")
        return target.getvalue()

    one, two = LLMImage("f1", jpeg("green")), LLMImage("f1", jpeg("red"))
    original, calls = LLMClient.call_json, []

    def counted(self, name, *args, **kwargs):
        calls.append(name)
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(LLMClient, "call_json", counted)
    llm = LLMClient()
    variables = {"frames": [{"id": "f1"}], "language": "id"}
    for image, model in [
        (one, "vision-a"),
        (one, "vision-a"),
        (two, "vision-a"),
        (two, "vision-b"),
    ]:
        call_stage(
            llm,
            "frame_describer",
            variables,
            FrameDescriptions,
            directory,
            images=[image],
            model=model,
        )
    assert len(calls) == 3
    assert all(
        base64.b64encode(one.data).decode() not in path.read_text()
        for path in (directory / "selection-cache").glob("*.json")
    )


def test_verbatim_spec_is_required_even_when_outline_omits_it(client, video, monkeypatch):
    original = LLMClient._mock

    def fixture(name, variables):
        result = original(name, variables)
        if name == "beat_annotator":
            for row, beat in zip(result["beats"], variables["beats"], strict=True):
                if "1200 mm" in beat["text"]:
                    row.update(label="spec", specs=["1200 mm"], uncertain=False)
        if name == "outline_builder":
            for chapter in result["chapters"]:
                chapter["required_beat_ids"] = []
        return result

    monkeypatch.setattr(LLMClient, "_mock", staticmethod(fixture))
    project = gap_project(
        client,
        video,
        [
            {"id": "s1", "start": 0, "end": 2, "text": "Siapkan alat."},
            {"id": "s2", "start": 10, "end": 12, "text": "Atur 1200 mm."},
        ],
    )
    output = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={"mode": "condense", "settings": {"condense_vision": {"enabled": True}}},
    ).json()
    run_output(output["id"])
    detail = client.get(f"/api/outputs/{output['id']}").json()
    spec = next(b for b in detail["beats"] if b["label"] == "spec")
    assert spec["required"] and spec["evidence"]["specs"] == ["1200 mm"]
    assert client.patch(f"/api/beats/{spec['id']}", json={"decision": "drop"}).status_code == 409
