import hashlib
import json

import pytest
from PIL import ImageFont

from api.app.config import ROOT
from api.app.models import Clip
from api.app.schemas import Transcript
from worker.pipeline.captions import caption_plan, font_spec, timed_tokens, write_ass
from worker.pipeline.framing import Face, Observation, analyze_framing, choose_framing, video_filter
from worker.pipeline.render import clip_fingerprint, render_clip
from worker.runner import run_output


def clip(**changes):
    data = dict(
        output_id="test",
        rank=1,
        start_s=0,
        end_s=6,
        topic="uji",
        titles=["A", "B"],
        hook_options=["Kenapa langkah ini sering salah?", "Ini hasilnya"],
        score=8,
        rubric={},
        reason="Uji",
        layout="auto",
    )
    return Clip(**(data | changes))


def transcript():
    texts = "Pisahkan uang pribadi dan uang usaha lalu catat setiap transaksi hari ini.".split()
    words = [
        dict(id=f"w{i + 1}", start=i * 0.4, end=i * 0.4 + 0.3, text=text)
        for i, text in enumerate(texts)
    ]
    return Transcript(
        words=words,
        sentences=[
            dict(
                id="s1",
                start=0,
                end=words[-1]["end"],
                text=" ".join(texts),
                word_ids=[w["id"] for w in words],
            )
        ],
    )


def observed(faces, *, text=0, edges=0.01, count=8):
    return [Observation(float(i), faces, text, edges) for i in range(count)]


def test_automatic_layout_preserves_screen_context_and_uses_portrait_for_stable_subject():
    speaker = Face(0.4, 0.2, 0.2, 0.3)
    source = choose_framing(
        1920, 1080, observed([speaker], text=90, edges=0.1), maximum_height=1280
    )
    assert source.content_kind == "screen_or_slides" and source.mode == "source"
    assert (source.width, source.height) == (1920, 1080) and source.crop is None
    talking = choose_framing(1920, 1080, observed([speaker]), maximum_height=1280)
    assert talking.mode == "subject_portrait" and talking.width < talking.height
    x, _, width, _ = talking.crop
    assert x <= speaker.x * 1920 and x + width >= (speaker.x + speaker.w) * 1920
    # Source with small webcam inset must not crop away the screen.
    pip = choose_framing(1920, 1080, observed([Face(0.85, 0.8, 0.08, 0.1)], text=100, edges=0.1))
    assert pip.mode == "source"


def test_uncertain_multiple_or_moving_subjects_preserve_complete_source():
    one = Face(0.4, 0.2, 0.2, 0.3)
    samples = observed([one], count=20)
    samples[-1].faces = [one, Face(0.7, 0.2, 0.2, 0.3)]
    assert choose_framing(1920, 1080, samples).mode == "source"
    moving = observed([Face(0.1, 0.2, 0.2, 0.3)], count=4) + observed(
        [Face(0.7, 0.2, 0.2, 0.3)], count=4
    )
    assert choose_framing(1920, 1080, moving).mode == "source"
    assert choose_framing(1920, 1080, []).mode == "source"
    assert choose_framing(1080, 1920, observed([one])).crop is None


def test_portrait_override_keeps_entire_screen_and_caption_outside_source():
    plan = choose_framing(1920, 1080, observed([], text=100, edges=0.1), "portrait", 1280)
    assert plan.mode == "portrait_fit" and plan.height == 1080
    assert plan.width / plan.height == pytest.approx(9 / 16, abs=0.001)
    filters, box = video_filter(plan, captions=True, hook=False)
    assert not any(f.startswith("crop=") for f in filters)
    assert box["y"] + box["height"] <= plan.height - box["caption_band"]
    assert box["width"] / box["height"] == pytest.approx(16 / 9, abs=0.01)
    assert all(value % 2 == 0 for value in (plan.width, plan.height, box["width"], box["height"]))


def test_compact_captions_keep_all_words_and_exact_word_timing_without_duplicate_headline(tmp_path):
    text = transcript()
    selected = clip(
        end_s=text.sentences[-1].end,
        hook_options=["Pisahkan uang pribadi dan uang usaha", "Apa hasilnya?"],
    )
    framing = choose_framing(1920, 1080, observed([Face(0.4, 0.2, 0.2, 0.3)]), maximum_height=1280)
    plan = caption_plan(selected, text, framing)
    assert all(c.word_count <= 3 and len(c.text.splitlines()) <= 2 for c in plan.cues)
    assert " ".join(c.text.replace("\n", " ") for c in plan.cues) == text.sentences[0].text
    assert plan.cues[0].start == 0 and plan.cues[0].end == text.words[2].end
    assert plan.timing == "word" and not plan.hook_lines
    assert plan.font_size / framing.height < 0.03
    path = tmp_path / "caption.ass"
    write_ass(path, plan, framing)
    assert "\\pos(" in path.read_text() and "WrapStyle: 2" in path.read_text()


def test_text_width_long_words_and_sentence_sidecar_estimates_are_bounded(tmp_path):
    text = Transcript(
        sentences=[
            dict(
                id="s1",
                start=0,
                end=8,
                text="Ini adalah penjelasan panjang dengan kata WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW agar caption tetap di dalam layar.",
            )
        ]
    )
    selected = clip(end_s=8)
    framing = choose_framing(720, 1280, [], maximum_height=1280)
    plan = caption_plan(selected, text, framing)
    assert plan.timing == "sentence_estimate" and plan.cues
    path = tmp_path / "bounded.ass"
    write_ass(path, plan, framing)
    assert "\\fscx" in path.read_text()
    for c in plan.cues:
        assert len(c.text.splitlines()) <= 2
        font = ImageFont.truetype(font_spec()[0], c.font_size)
        measured = max(font.getlength(line) for line in c.text.splitlines())
        scale = min(1, plan.max_width / max(measured, 1))
        assert measured * scale <= plan.max_width + 1e-6
    assert all(a.end <= b.start for a, b in zip(plan.cues, plan.cues[1:], strict=False))


def test_caption_edits_reestimate_only_when_word_count_changes_and_escape_ass(tmp_path):
    text = transcript()
    selected = clip(
        end_s=text.sentences[-1].end, caption_overrides={"s1": r"{\pos(0,0)} tulisan diperbaiki"}
    )
    tokens = timed_tokens(selected, text)
    assert all(t.estimated for t in tokens) and tokens[-1].end <= selected.end_s
    framing = choose_framing(1920, 1080, [])
    plan = caption_plan(selected, text, framing)
    path = tmp_path / "safe.ass"
    write_ass(path, plan, framing)
    assert r"{\pos(0,0)}" not in path.read_text()
    assert "｛＼pos(0,0)｝" in path.read_text()
    selected.caption_overrides = {"s1": " ".join("benar" for _ in text.words)}
    assert not any(t.estimated for t in timed_tokens(selected, text))


def test_bundled_neural_model_integrity_and_actual_inference(client, video):
    folder = ROOT / "worker/assets/yunet"
    manifest = json.loads((folder / "manifest.json").read_text())
    model = folder / manifest["model"]
    assert len(model.read_bytes()) == manifest["bytes"]
    assert hashlib.sha256(model.read_bytes()).hexdigest() == manifest["sha256"]
    assert "MIT License" in (folder / "LICENSE").read_text()
    plan = analyze_framing(video, 0, 4)
    assert plan.observations and "YuNet" in plan.analyzer
    assert plan.mode == "source"


def test_real_mp4_dimensions_caption_bands_and_cache_input_invalidation(client, tmp_path, video):
    selected = clip(end_s=4)
    text = Transcript(
        sentences=[
            dict(
                id="s1",
                start=0,
                end=4,
                text="Seluruh bingkai dipertahankan dan caption berganti mengikuti ucapan.",
            )
        ]
    )
    path, qc = render_clip(video, selected, text, tmp_path)
    assert qc["passed"] and qc["width"] > qc["height"]
    assert qc["caption_max_words"] <= 5 and qc["hook_shown"] is False
    box = qc["content_box"]
    assert box["y"] + box["height"] <= qc["height"] - box["caption_band"]
    stamp = path.stat().st_mtime_ns
    assert render_clip(video, selected, text, tmp_path)[0].stat().st_mtime_ns == stamp
    text.sentences[0].text = "Teks sumber berubah dan caption harus ikut diperbarui."
    render_clip(video, selected, text, tmp_path)
    assert path.stat().st_mtime_ns != stamp


def test_layout_patch_and_legacy_render_upgrade_without_new_llm_calls(client, project):
    from sqlmodel import Session

    from api.app.config import get_settings
    from api.app.db import get_engine

    response = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={"mode": "clips", "settings": {"clip_count": 1}},
    )
    output_id = response.json()["id"]
    run_output(output_id)
    before = client.get(f"/api/outputs/{output_id}").json()["clips"][0]
    assert before["layout"] == "auto"
    key = before["render_fingerprint"]
    log = get_settings().storage / "outputs" / output_id / "llm_log.jsonl"
    usage = log.read_text()
    # Simulate a persisted version-1 renderer result being opened after this update.
    with Session(get_engine()) as session:
        row = session.get(Clip, before["id"])
        row.render_fingerprint = "legacy-renderer-v1"
        session.commit()
    manifest_path = log.parent / f"{before['id']}.render.json"
    legacy_manifest = json.loads(manifest_path.read_text())
    legacy_manifest["fingerprint"] = "legacy-renderer-v1"
    manifest_path.write_text(json.dumps(legacy_manifest))
    stale = client.get(f"/api/outputs/{output_id}").json()["clips"][0]
    assert stale["needs_render"]
    assert client.get(stale["file_url"]).status_code == 409
    assert client.post(f"/api/clips/{before['id']}/render").status_code == 202
    run_output(output_id, clip_id=before["id"])
    assert not client.get(f"/api/outputs/{output_id}").json()["clips"][0]["needs_render"]
    assert log.read_text() == usage
    changed = client.patch(f"/api/clips/{before['id']}", json={"layout": "portrait"})
    assert changed.status_code == 200 and changed.json()["needs_render"]
    assert (
        client.patch(f"/api/clips/{before['id']}", json={"layout": "invented"}).status_code == 422
    )
    assert client.post(f"/api/clips/{before['id']}/render").status_code == 202
    run_output(output_id, clip_id=before["id"])
    after = client.get(f"/api/outputs/{output_id}").json()["clips"][0]
    assert after["render_fingerprint"] != key and not after["needs_render"]
    assert after["qc"]["width"] < after["qc"]["height"]
    assert log.read_text() == usage
    assert clip_fingerprint(clip(layout="portrait")) != clip_fingerprint(clip(layout="source"))
