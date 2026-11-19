import json

import numpy as np
import pytest

from api.app.models import Clip
from api.app.schemas import RetentionSettings, Transcript
from worker.pipeline.audio import RATE, mixed_audio
from worker.pipeline.captions import caption_plan, timed_tokens, write_ass
from worker.pipeline.framing import Face, choose_framing
from worker.pipeline.media import run
from worker.pipeline.qc import caption_bounds, inspect_clip, intervals
from worker.pipeline.reframe import Tracker, compose
from worker.pipeline.render import clip_fingerprint
from worker.pipeline.retention import build_edl, remap_tokens, zoom_at
from worker.runner import run_output


def transcript():
    return Transcript.model_validate(
        {
            "words": [
                {"id": "w1", "start": 0.2, "end": 0.8, "text": "Ini"},
                {"id": "w2", "start": 0.9, "end": 1.4, "text": "contoh."},
                {"id": "w3", "start": 2, "end": 2.2, "text": "eh"},
                {"id": "w4", "start": 3, "end": 3.6, "text": "Perhatikan"},
                {"id": "w5", "start": 3.7, "end": 4.4, "text": "hasilnya."},
                {"id": "w6", "start": 5.6, "end": 6.3, "text": "Selesai."},
            ],
            "sentences": [
                {
                    "id": "s1",
                    "start": 0.2,
                    "end": 1.4,
                    "text": "Ini contoh.",
                    "word_ids": ["w1", "w2"],
                },
                {"id": "s2", "start": 2, "end": 2.2, "text": "eh", "word_ids": ["w3"]},
                {
                    "id": "s3",
                    "start": 3,
                    "end": 4.4,
                    "text": "Perhatikan hasilnya.",
                    "word_ids": ["w4", "w5"],
                },
                {"id": "s4", "start": 5.6, "end": 6.3, "text": "Selesai.", "word_ids": ["w6"]},
            ],
        }
    )


def clip(**changes):
    return Clip(
        **(
            dict(
                output_id="fixture",
                rank=1,
                start_s=0,
                end_s=7,
                titles=["A", "B"],
                hook_options=["Apa hasilnya?", "Perhatikan hasilnya"],
                topic="uji",
                score=8,
                rubric={},
                reason="uji",
                layout="auto",
            )
            | changes
        )
    )


def test_edit_map_removes_pauses_and_only_standalone_fillers_without_cutting_other_words():
    text, selected = transcript(), clip()
    plan = build_edl(selected, text)
    mapped = remap_tokens(timed_tokens(selected, text), selected, plan)
    assert 3 <= plan.duration < 7
    assert [t.word_id for t in mapped] == ["w1", "w2", "w4", "w5", "w6"]
    assert any(r["kind"] == "filler" for r in plan.removed)
    for span in plan.spans:
        for boundary in (span.src_start, span.src_end):
            assert not any(
                w.start + 1e-6 < boundary < w.end - 1e-6 for w in text.words if w.id != "w3"
            )
    assert all(a.end <= b.start for a, b in zip(mapped, mapped[1:], strict=False))
    assert all(t.end <= plan.duration for t in mapped)
    assert all(0 < s.fade_in <= 0.01 for s in plan.spans[1:])
    by_id = {t.word_id: t for t in mapped}
    assert by_id["w6"].start - by_id["w5"].end == pytest.approx(0.12)


def test_all_retention_options_can_be_disabled_and_count_changes_preserve_caption_text():
    text = transcript()
    options = {name: False for name in RetentionSettings.model_fields}
    selected = clip(retention=options)
    plan = build_edl(selected, text)
    assert plan.duration == 7 and len(plan.spans) == 1 and not plan.removed
    selected = clip(caption_overrides={"s1": "Kalimat dikoreksi dengan jumlah kata berbeda."})
    plan = build_edl(selected, text)
    assert plan.duration == 7 and plan.warnings
    mapped = remap_tokens(timed_tokens(selected, text), selected, plan)
    assert all(
        word in " ".join(t.text for t in mapped)
        for word in selected.caption_overrides["s1"].split()
    )


def test_corrected_filler_is_not_removed_and_short_clips_are_not_overtrimmed():
    text = transcript()
    selected = clip(caption_overrides={"s2": "langkah"})
    plan = build_edl(selected, text)
    tokens = remap_tokens(timed_tokens(selected, text), selected, plan)
    assert "langkah" in [t.text for t in tokens]
    assert text.words[2].text == "eh", "Original transcript must remain stable"
    short = clip(end_s=3)
    assert build_edl(short, text).duration == 3


def test_cold_open_repeats_only_valid_sentence_with_whoosh_and_remaps_captions():
    selected = clip(retention={"cold_open": True}, selection={"cold_open_id": "s3"})
    text = transcript()
    plan = build_edl(selected, text)
    assert [s.kind for s in plan.spans[:2]] == ["cold_open", "transition"]
    assert plan.spans[0].src_start == 3
    mapped = remap_tokens(timed_tokens(selected, text), selected, plan)
    assert mapped[0].word_id == "w4" and mapped[0].start == 0
    assert sum(t.word_id == "w4" for t in mapped) == 2
    assert mapped[0].occurrence != mapped[-2].occurrence
    invalid = build_edl(
        clip(retention={"cold_open": True}, selection={"cold_open_id": "s999"}), text
    )
    assert all(s.kind == "body" for s in invalid.spans) and invalid.warnings


def test_cold_open_never_exceeds_hard_180_second_output_limit():
    text = Transcript(
        sentences=[
            dict(id="s1", start=0, end=2, text="Pembuka."),
            dict(id="s2", start=2, end=179, text="Isi panjang."),
        ]
    )
    plan = build_edl(
        clip(end_s=179, retention={"cold_open": True}, selection={"cold_open_id": "s1"}), text
    )
    assert plan.duration <= 180 and all(s.kind == "body" for s in plan.spans)
    assert any("180" in note for note in plan.warnings)


def test_audio_crossfades_have_same_sample_duration_as_the_time_map(client, video, tmp_path):
    selected, text = (
        clip(retention={"cold_open": True}, selection={"cold_open_id": "s3"}),
        transcript(),
    )
    plan = build_edl(selected, text)
    audio = mixed_audio(video, selected, plan, tmp_path)
    assert audio.shape == (round(plan.duration * RATE), 2)
    assert np.isfinite(audio).all() and np.max(np.abs(audio)) <= 1
    transition = plan.spans[1]
    section = audio[
        round((transition.dst_start + 0.02) * RATE) : round((transition.dst_end - 0.02) * RATE)
    ]
    assert section.std() > 0.001


def test_karaoke_uses_remapped_word_times_and_keywords_stay_highlighted(tmp_path):
    selected, text = clip(keywords=["hasilnya."]), transcript()
    edit = build_edl(selected, text)
    tokens = remap_tokens(timed_tokens(selected, text), selected, edit)
    framing = choose_framing(720, 1280, [])
    captions = caption_plan(selected, text, framing, mapped_tokens=tokens, duration=edit.duration)
    assert captions.karaoke and not caption_bounds(captions, framing, edit.duration)
    path = tmp_path / "karaoke.ass"
    write_ass(path, captions, framing)
    ass = path.read_text()
    assert r"\t(" in ass and r"{\1c&H4DE1FF&}hasilnya." in ass
    assert "eh" not in " ".join(c.text for c in captions.cues)
    assert all(c.end <= edit.duration for c in captions.cues)


def test_estimated_sentence_timing_does_not_pretend_to_have_word_karaoke():
    text = Transcript(
        sentences=[dict(id="s1", start=0, end=5, text="Ini hanya sidecar per kalimat.")]
    )
    selected = clip(end_s=5)
    captions = caption_plan(selected, text, choose_framing(1280, 720, []))
    assert not captions.karaoke and captions.timing == "sentence_estimate"
    assert not caption_plan(
        clip(captions=False), transcript(), choose_framing(1280, 720, [])
    ).karaoke


def test_tracker_keeps_target_until_scene_cut_and_uses_blur_after_two_seconds(monkeypatch):
    framing = choose_framing(640, 360, [], "portrait", 320)
    framing.content_kind, framing.mode, framing.crop = (
        "speaker",
        "subject_portrait",
        (0, 0, 202, 360),
    )
    tracker = Tracker(framing)
    current = [Face(0.3, 0.15, 0.2, 0.4)]
    monkeypatch.setattr(tracker, "detect", lambda _: current)
    frame = np.full((360, 640, 3), 100, dtype=np.uint8)
    first = tracker.update(frame, 0, 0, reset=True)
    initial = first["center"]
    current = [Face(0.31, 0.15, 0.2, 0.4)]
    assert tracker.update(frame, 3, 0.1)["center"] == initial  # 8% dead zone
    current = [Face(0.36, 0.15, 0.2, 0.4)]
    moved = tracker.update(frame, 6, 0.2)["center"]
    assert initial < moved < (0.36 + 0.1) * 640
    current = [Face(0.75, 0.15, 0.2, 0.4)]
    for index in range(9, 75):
        lost = tracker.update(frame, index, index / 30)
    assert lost["mode"] == "blur_fit" and tracker.target.x == 0.36
    white = np.full_like(frame, 255)
    switched = tracker.update(white, 75, 2.5)
    assert switched["scene_cut"] and tracker.target.x == 0.75


def test_blur_fallback_preserves_entire_frame_and_keeps_text_bands_clear():
    source = np.zeros((360, 640, 3), dtype=np.uint8)
    source[:, :320] = [30, 60, 200]
    source[:, 320:] = [200, 60, 30]
    framing = choose_framing(640, 360, [], "portrait", 320)
    canvas, meta = compose(
        source,
        framing,
        {"face": None, "mode": "blur_fit", "center": 320, "scene_cut": False},
        1,
        captions=True,
        hook=False,
    )
    box = meta["content_box"]
    assert meta["crop"] is None and canvas.shape == (320, framing.width, 3)
    assert np.allclose(canvas[box["y"] + 5, box["x"] + 5], [30, 60, 200], atol=2)
    assert np.allclose(canvas[box["y"] + 5, box["x"] + box["width"] - 5], [200, 60, 30], atol=2)
    assert np.all(canvas[-box["caption_band"] :] == 16)


def test_zoom_transitions_and_emphasis_are_bounded_and_can_be_disabled():
    text, selected = transcript(), clip(selection={"emphasis_word_ids": ["w4"]})
    edit = build_edl(selected, text)
    values = [zoom_at(t, selected, text, edit) for t in np.linspace(0, 7, 300)]
    assert min(values) >= 1 and max(values) <= 1.2 + 1e-9 and max(values) > 1.19
    selected.retention = {"zoom": False, "emphasis": False}
    assert zoom_at(3.3, selected, text, build_edl(selected, text)) == 1


def test_qc_reports_black_silence_and_unmeasurable_loudness_instead_of_passing(tmp_path):
    source = tmp_path / "black.mp4"
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=160x90:r=30:d=3",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ]
    )
    framing = choose_framing(160, 90, [])
    selected = clip(end_s=3, captions=False)
    text = Transcript(sentences=[dict(id="s1", start=0, end=3, text="Fixture hening.")])
    captions = caption_plan(selected, text, framing)
    qc = inspect_clip(
        source, 3, framing, captions, {"x": 0, "y": 0, "width": 160, "height": 90}, tmp_path
    )
    assert not qc["passed"]
    assert not qc["checks"]["black_frames"] and not qc["checks"]["silence"]
    assert qc["loudness"]["input_i"] is None
    assert len(qc["black_intervals"]) == 1 and len(qc["silence_intervals"]) == 1
    assert intervals("silence_start: -2.0e-05", "silence", 2)[0]["duration"] == 2


def test_caption_geometry_and_duration_failures_are_explicit():
    selected, text = clip(), transcript()
    framing = choose_framing(720, 1280, [])
    captions = caption_plan(selected, text, framing)
    captions.cues[0].font_size = 300
    captions.cues[0].end = 20
    reasons = {issue["reason"] for issue in caption_bounds(captions, framing, 7)}
    assert reasons == {"outside_caption_safe_band", "invalid_caption_time"}


def test_thumbnail_download_zip_packaging_and_retention_patch_are_end_to_end(client, project):
    import io
    import zipfile

    response = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={"mode": "clips", "settings": {"clip_count": 1, "purpose": "discovery"}},
    )
    output_id = response.json()["id"]
    run_output(output_id)
    detail = client.get(f"/api/outputs/{output_id}").json()
    c = detail["clips"][0]
    assert c["thumbnail_url"] and c["qc"]["normalization"]["status"] == "two_pass"
    assert c["qc"]["tracking"]["frames"] > 0
    assert c["qc"]["thumbnail"]["output_s"] <= c["qc"]["expected_duration_s"] * 0.3 + 1 / 30
    thumbnail = client.get(c["thumbnail_url"])
    assert thumbnail.status_code == 200 and thumbnail.content[:2] == b"\xff\xd8"
    with zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/outputs/{output_id}/export.zip").content)
    ) as archive:
        assert f"{c['id']}.jpg" in archive.namelist()
        caption = archive.read("captions.txt").decode()
        assert c["description"] in caption and c["hashtags"][0] in caption
    client.patch(
        f"/api/clips/{c['id']}", json={"retention": {"shorten_pauses": False}}
    ).raise_for_status()
    patched = client.patch(f"/api/clips/{c['id']}", json={"retention": {"zoom": False}})
    assert patched.status_code == 200 and patched.json()["retention"]["shorten_pauses"] is False
    assert patched.json()["retention"]["zoom"] is False and patched.json()["needs_render"]
    assert client.get(c["thumbnail_url"]).status_code == 409
    assert (
        client.patch(f"/api/clips/{c['id']}", json={"retention": {"invented": True}}).status_code
        == 422
    )
    assert clip_fingerprint(clip(retention={"zoom": True})) != clip_fingerprint(
        clip(retention={"zoom": False})
    )


def test_cold_open_video_pipeline_keeps_a_complete_ordered_frame_map(client, tmp_path, video):
    from worker.pipeline.render import render_clip

    selected = clip(retention={"cold_open": True}, selection={"cold_open_id": "s3"})
    path, qc = render_clip(video, selected, transcript(), tmp_path)
    assert path.is_file() and qc["passed"]
    trace = json.loads((tmp_path / "reframe" / f"{selected.id}.json").read_text())
    assert [f["frame"] for f in trace["frames"]] == list(range(trace["summary"]["frames"]))
    assert [f["output_s"] for f in trace["frames"]] == sorted(
        f["output_s"] for f in trace["frames"]
    )
    assert any(f.get("transition") for f in trace["frames"])
    assert qc["expected_duration_s"] == pytest.approx(build_edl(selected, transcript()).duration)
    assert qc["duration_s"] == pytest.approx(qc["expected_duration_s"], abs=0.1)


def test_qc_failed_clip_remains_available_for_review_through_api(client, tmp_path):
    source = tmp_path / "silent-black.mp4"
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=160x90:r=30:d=3",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ]
    )
    data = source.read_bytes()
    upload = client.post(
        "/api/uploads", json={"filename": "black.mp4", "total_bytes": len(data)}
    ).json()
    client.put(f"/api/uploads/{upload['id']}?offset=0", content=data).raise_for_status()
    project = client.post(
        "/api/projects",
        json={
            "source_kind": "upload",
            "upload_id": upload["id"],
            "transcript": {
                "sentences": [
                    {"id": "s1", "start": 0, "end": 3, "text": "Fixture hening tanpa suara."}
                ]
            },
        },
    ).json()
    output = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={"mode": "clips", "settings": {"clip_count": 1}},
    ).json()
    run_output(output["id"])
    detail = client.get(f"/api/outputs/{output['id']}").json()
    assert detail["output"]["status"] == "done"
    c = detail["clips"][0]
    assert not c["qc"]["passed"] and "black_frames" in c["qc"]["needs_review"]
    assert c["qc"]["normalization"]["status"] == "unmeasurable_silence"
    assert client.get(c["file_url"]).status_code == 200
    assert client.get(c["thumbnail_url"]).status_code == 200
