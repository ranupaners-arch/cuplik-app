import io
import zipfile

from api.app.models import Beat
from api.app.schemas import OutputSettings
from worker.pipeline.audio import capture
from worker.pipeline.condense_qc import inspect_condensed, normalize_condensed, unexpected_silence
from worker.pipeline.render import render_condensed
from worker.runner import run_output


def test_normalized_ringkas_has_measured_levels_and_aligned_streams(client, video, tmp_path):
    beat = Beat(
        id="b", output_id="o", chapter_id="c", sentence_id="s", start_s=0, end_s=12, text="Uji."
    )
    path = render_condensed(video, [beat], tmp_path, False, lambda *_: None)
    normalization = normalize_condensed(path, tmp_path)
    qc = inspect_condensed(path, tmp_path, [beat], 12, normalization)
    assert qc["passed"], qc
    assert qc["normalization"]["status"] == "two_pass"
    assert qc["checks"]["stream_alignment"] and abs(qc["loudness"]["input_i"] + 14) <= 1


def test_approved_silent_timelapse_is_not_missing_audio(client, video, tmp_path):
    beat = Beat(
        id="b",
        output_id="o",
        chapter_id="c",
        sentence_id="",
        start_s=0,
        end_s=8,
        text="",
        kind="visual",
        label="manual",
        timelapse_approved=True,
        decision="speed",
        speed=4,
    )
    path = render_condensed(
        video,
        [beat],
        tmp_path,
        False,
        lambda *_: None,
        settings=OutputSettings(timelapse_enabled=True),
    )
    qc = inspect_condensed(path, tmp_path, [beat], 2, normalize_condensed(path, tmp_path))
    assert qc["checks"]["silence"] and qc["checks"]["loudness"]
    assert not qc["loudness_applicable"] and qc["expected_silence"]


def test_unintended_silence_and_black_frames_require_review(client, video, tmp_path):
    beat = Beat(
        id="b", output_id="o", chapter_id="c", sentence_id="s", start_s=0, end_s=12, text="Narasi."
    )
    path = render_condensed(video, [beat], tmp_path, False, lambda *_: None)
    silent = tmp_path / "silent.mp4"
    capture(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(path),
            "-vf",
            "drawbox=color=black:t=fill",
            "-af",
            "volume=0",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(silent),
        ],
        directory=tmp_path,
    )
    qc = inspect_condensed(silent, tmp_path, [beat], 12, {"status": "unmeasurable_silence"})
    assert not qc["passed"]
    assert {"silence", "black_frames", "loudness"} <= set(qc["needs_review"])


def test_partial_approved_silence_does_not_hide_silent_narration():
    actual = [{"start": 0, "end": 12, "duration": 12}]
    remainder = unexpected_silence(actual, [(2, 5), (4, 8)])
    assert [(s["start"], s["end"]) for s in remainder] == [(0, 2), (8, 12)]


def test_qc_api_and_export_are_available_after_render(client, project):
    output = client.post(f"/api/projects/{project['id']}/outputs", json={"mode": "condense"}).json()
    identifier = output["id"]
    assert client.get(f"/api/outputs/{identifier}/qc").status_code == 404
    run_output(identifier)
    detail = client.get(f"/api/outputs/{identifier}").json()
    body = {
        "target_seconds": 12,
        "chapters": [{"id": c["id"], "required": True} for c in detail["chapters"]],
    }
    assert client.put(f"/api/outputs/{identifier}/outline", json=body).status_code == 202
    run_output(identifier, render_only=True)
    response = client.get(f"/api/outputs/{identifier}/qc")
    assert response.status_code == 200 and response.json()["normalization"]["status"] == "two_pass"
    detail = client.get(f"/api/outputs/{identifier}").json()
    assert detail["condense_qc"] == response.json()
    archive = zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/outputs/{identifier}/export.zip").content)
    )
    assert "condensed.qc.json" in archive.namelist()
