import io
import json
import zipfile

import pytest
from sqlmodel import Session, select

from api.app.db import get_engine
from api.app.models import Annotation, Project
from eval.evaluate import Range, coverage_metrics, evaluate
from worker.pipeline.ingest import ingest_project
from worker.pipeline.storage import atomic_json, output_dir, project_dir
from worker.runner import run_output


def payload(client, identifier, mode="clips", **changes):
    view = client.get(f"/api/projects/{identifier}/annotations/{mode}")
    assert view.status_code == 200, view.text
    data = view.json()
    document = {**data["document"], **changes}
    return {
        "expected_revision": data["revision"],
        "source_fingerprint": data["source_fingerprint"],
        "transcript_fingerprint": data["transcript_fingerprint"],
        "document": document,
    }


def reviewed(client, project, mode="clips"):
    ingest_project(project["id"])
    fields = (
        {"ranges": [{"start_s": 0, "end_s": 4, "label": "Momen utuh"}]}
        if mode == "clips"
        else {
            "required_chapters": [{"start_s": 0, "end_s": 4, "label": "Langkah awal"}],
            "required_specs": [{"start_s": 4, "end_s": 6, "label": "Nilai penting"}],
        }
    )
    body = payload(
        client,
        project["id"],
        mode,
        status="reviewed",
        annotator="Peninjau fixture",
        review_confirmed=True,
        **fields,
    )
    response = client.put(f"/api/projects/{project['id']}/annotations/{mode}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_drafts_review_gate_conflict_and_reading_do_not_rewrite_labels(client, project):
    url = f"/api/projects/{project['id']}/annotations/clips"
    assert client.get(url).status_code == 409
    ingest_project(project["id"])
    assert client.get(url).json()["revision"] == 0
    with Session(get_engine()) as session:
        assert list(session.exec(select(Annotation))) == []
    initial = payload(client, project["id"])
    saved = client.put(url, json=initial)
    assert saved.status_code == 200 and saved.json()["revision"] == 1
    stale = {**initial, "document": {**initial["document"], "note": "Edit dari tab lain"}}
    assert client.put(url, json=stale).status_code == 409
    assert client.get(url).json()["document"]["note"] == ""
    assert client.get(url + "/export.zip").status_code == 409
    invalid = payload(
        client, project["id"], status="reviewed", annotator="", review_confirmed=False
    )
    assert client.put(url, json=invalid).status_code == 422
    invalid = payload(client, project["id"], ranges=[{"start_s": 0, "end_s": 20}])
    assert client.put(url, json=invalid).status_code == 422
    assert client.get(url).json()["revision"] == 1


def test_export_is_input_bound_and_original_blind_labels_remain_independent(
    client, project, tmp_path
):
    first = reviewed(client, project)
    url = f"/api/projects/{project['id']}/annotations/clips"
    assert first["independent"]
    response = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={"mode": "clips", "settings": {"clip_count": 1}},
    )
    output_id = response.json()["id"]
    run_output(output_id)
    # Saving identical labels must not downgrade the original independent review.
    noop = client.put(url, json=payload(client, project["id"]))
    assert noop.json()["revision"] == first["revision"] and noop.json()["independent"]
    package = client.get(url + f"/export.zip?output_id={output_id}")
    assert package.status_code == 200
    case = tmp_path / "cases" / "reviewed-case"
    case.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert {
            "expected.json",
            "transcript.json",
            "annotation.json",
            "predictions.json",
            "README.txt",
        } <= set(archive.namelist())
        assert "source.mp4" not in archive.namelist()
        expected = json.loads(archive.read("expected.json"))
        assert expected["independent"] and expected["annotation_status"] == "reviewed"
        assert expected["provenance"]["source_sha256"]
        for name in ["expected.json", "predictions.json", "transcript.json"]:
            (case / name).write_bytes(archive.read(name))
    (case / "source.mp4").write_bytes((project_dir(project["id"]) / "source.mp4").read_bytes())
    result = evaluate(case.parent, require_predictions=True)
    assert result["status"] == "evaluated" and result["quality_status"] == "not_run"
    assert "provider_not_live" in result["cases"][0]["quality_excluded_reasons"]
    changed = client.put(
        url, json=payload(client, project["id"], note="Label diubah setelah prediksi")
    )
    assert not changed.json()["independent"]
    assert changed.json()["revision"] == first["revision"] + 1


def test_stale_annotations_and_output_plan_fail_closed_when_transcript_changes(client, project):
    reviewed(client, project)
    output = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={"mode": "clips", "settings": {"clip_count": 1}},
    ).json()
    run_output(output["id"])
    url = f"/api/projects/{project['id']}/annotations/clips"
    old = payload(client, project["id"], note="Tab lama")
    path = project_dir(project["id"]) / "transcript.json"
    transcript = json.loads(path.read_text())
    transcript["sentences"][0]["text"] += " Koreksi baru."
    atomic_json(path, transcript)
    assert client.get(url).json()["stale"]
    assert client.put(url, json=old).status_code == 409
    assert client.get(url + "/export.zip").status_code == 409
    video = next(output_dir(output["id"]).glob("*.mp4"))
    before = video.read_bytes()
    with pytest.raises(ValueError, match="Sumber atau transkrip berubah"):
        run_output(output["id"])
    assert video.read_bytes() == before


def test_source_stream_expiration_restore_and_caption_track_are_local(client, project):
    ingest_project(project["id"])
    path = f"/api/projects/{project['id']}"
    with Session(get_engine()) as session:
        row = session.get(Project, project["id"])
        row.language = "auto"
        session.add(row)
        session.commit()
    assert client.get(path + "/annotations/clips").json()["language"] == "id"
    assert client.get(path + "/source", headers={"Range": "bytes=0-99"}).status_code == 206
    vtt = client.get(path + "/transcript.vtt")
    assert vtt.status_code == 200 and vtt.text.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:04.000" in vtt.text
    transcript_path = project_dir(project["id"]) / "transcript.json"
    before = transcript_path.read_bytes()
    (project_dir(project["id"]) / "source.mp4").unlink()
    assert client.get(path + "/source").status_code == 410
    assert client.post(path + "/prepare-source").status_code == 202
    ingest_project(project["id"])
    assert transcript_path.read_bytes() == before
    assert client.get(path + "/source").status_code == 200


def test_ringkas_coverage_does_not_double_count_and_human_quality_counts_unique_sources(
    client, project, tmp_path
):
    assert (
        coverage_metrics([Range(start_s=0, end_s=10)], [Range(start_s=0, end_s=5)] * 3, 0.9)[
            "recall"
        ]
        == 0
    )
    reviewed(client, project, "condense")
    url = f"/api/projects/{project['id']}/annotations/condense/export.zip"
    package = client.get(url)
    root = tmp_path / "condense-cases"
    for name in ["a", "b"]:
        case = root / name
        case.mkdir(parents=True)
        with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
            for member in ["expected.json", "transcript.json"]:
                (case / member).write_bytes(archive.read(member))
        expected = json.loads((case / "expected.json").read_text())
        (case / "source.mp4").write_bytes((project_dir(project["id"]) / "source.mp4").read_bytes())
        # Offline metadata fixture tests gating, not a live provider or measured product quality.
        (case / "predictions.json").write_text(
            json.dumps(
                {
                    "mode": "condense",
                    "provider": "ollama",
                    "duration_s": 20,
                    "retained_ranges": [{"start_s": 0, "end_s": 3}, {"start_s": 4, "end_s": 6}],
                    "provenance": expected["provenance"],
                }
            )
        )
    report = evaluate(root, require_predictions=True)
    assert report["status"] == "evaluated"
    assert report["quality_condense_videos"] == 1 and not report["quality_targets_met"]["condense"]
    assert report["quality_chapter_recall"] == 0 and report["quality_spec_recall"] == 1
    assert report["cases"][0]["within_target_tolerance"]


def test_demo_review_is_always_synthetic(client):
    project = client.post("/api/projects", json={"source_kind": "demo"}).json()
    result = reviewed(client, project)
    assert result["dataset_kind"] == "synthetic"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"independent": False}, "assisted_annotation"),
        ({"annotator": ""}, "annotator_missing"),
        ({"source": "./missing.mp4"}, "source_unverified"),
        ({"dataset_kind": "synthetic"}, "dataset_synthetic"),
    ],
)
def test_evaluator_excludes_unqualified_reviews_even_with_provider_metadata(
    tmp_path, video, change, reason
):
    # A synthetic local media fixture checks exclusions, not provider quality.
    case = tmp_path / "cases" / "case"
    case.mkdir(parents=True)
    (case / "source.mp4").write_bytes(video.read_bytes())
    expected = {
        "mode": "clips",
        "source": "./source.mp4",
        "annotator": "Metadata fixture",
        "ranges": [{"start_s": 0, "end_s": 4}],
        **change,
    }
    (case / "expected.json").write_text(json.dumps(expected))
    (case / "predictions.json").write_text(
        json.dumps({"provider": "ollama", "clips": [{"start_s": 0, "end_s": 4}]})
    )
    report = evaluate(case.parent)
    assert report["status"] == "evaluated" and report["quality_status"] == "not_run"
    assert reason in report["cases"][0]["quality_excluded_reasons"]


def test_evaluator_skips_drafts_and_rejects_changed_input_provenance(tmp_path, video):
    from worker.pipeline.ingest import checksum

    case = tmp_path / "cases" / "case"
    case.mkdir(parents=True)
    (case / "source.mp4").write_bytes(video.read_bytes())
    expected = {
        "mode": "clips",
        "source": "./source.mp4",
        "annotator": "Metadata fixture",
        "annotation_status": "draft",
        "ranges": [{"start_s": 0, "end_s": 4}],
        "provenance": {"source_sha256": checksum(video)},
    }
    (case / "expected.json").write_text(json.dumps(expected))
    assert evaluate(case.parent)["quality_status"] == "not_run"
    expected["annotation_status"] = "reviewed"
    (case / "expected.json").write_text(json.dumps(expected))
    (case / "predictions.json").write_text(
        json.dumps({"provider": "mock", "clips": [], "provenance": {"source_sha256": "0" * 64}})
    )
    assert evaluate(case.parent)["status"] == "error"
    expected["provenance"]["source_sha256"] = "1" * 64
    (case / "expected.json").write_text(json.dumps(expected))
    assert "Checksum" in evaluate(case.parent)["errors"][0]
