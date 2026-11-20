import io
import zipfile
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from api.app.db import get_engine
from api.app.models import Beat, Chapter, Output, Task
from api.app.schemas import CoherenceCheck, OutputSettings
from worker.pipeline.coherence import check_coherence, script_windows, validate_check
from worker.pipeline.llm import LLMClient, LLMError, LLMValidationError
from worker.pipeline.storage import output_dir
from worker.runner import run_output


def plan(target=8, locked=False):
    chapter = Chapter(
        id="c",
        output_id="o",
        order=1,
        title="Langkah",
        goal="Utuh",
        importance="core",
        required=True,
    )
    beats = [
        Beat(
            id=str(i),
            output_id="o",
            chapter_id="c",
            sentence_id=f"s{i}",
            start_s=(i - 1) * 4,
            end_s=i * 4,
            text="Seperti tadi." if i == 3 else "Konteks awal.",
            required=i == 3,
            decision="keep" if i == 3 else "drop",
            locked=locked and i == 1,
        )
        for i in range(1, 4)
    ]
    settings = OutputSettings(coherence_enabled=True, target_seconds=target)
    output = Output(id="o", project_id="p", mode="condense", settings=settings.model_dump())
    return output, beats, [chapter]


def issue(at="3", restore="1", **changes):
    return {
        "at_id": at,
        "type": "dangling_reference",
        "fix": "restore",
        "restore_ids": [restore],
        "note": "Rujukan kehilangan konteks awal.",
        **changes,
    }


class Checker:
    settings = SimpleNamespace(llm_provider="mock", llm_model_fast="")

    def __init__(self, responses):
        self.responses, self.calls = iter(responses), 0

    def call_json(self, name, variables, schema, log_path):
        assert name == "coherence_checker"
        self.calls += 1
        return schema.model_validate({"issues": next(self.responses)})


@pytest.mark.parametrize(
    "bad",
    [
        issue(restore="unknown"),
        issue(at="1"),
        issue(restore="3"),
        issue(at="3", restore_ids=["1", "1"]),
        issue(fix="review"),
    ],
)
def test_invalid_restorations_are_rejected_before_caching(tmp_path, bad):
    output, beats, chapters = plan()
    checker = Checker([[bad]])
    with pytest.raises(LLMValidationError):
        check_coherence(output, beats, chapters, checker, tmp_path, lambda *_: None)
    assert not list((tmp_path / "selection-cache").glob("*.json"))
    assert beats[0].decision == "drop"


def test_forward_context_duplicate_and_foreign_owned_issue_are_rejected():
    _, beats, chapters = plan()
    rows, owned = next(script_windows(beats, chapters))
    rows[0]["end_s"] = 10
    with pytest.raises(LLMValidationError):
        validate_check(CoherenceCheck(issues=[issue()]), rows, owned)
    rows[0]["end_s"] = 4
    with pytest.raises(LLMValidationError):
        validate_check(CoherenceCheck(issues=[issue(), issue()]), rows, owned)
    with pytest.raises(LLMValidationError):
        validate_check(CoherenceCheck(issues=[issue()]), rows, {"1"})


def test_restore_requires_review_then_reuses_validated_check(tmp_path):
    output, beats, chapters = plan()
    checker = Checker([[issue()], []])
    report = check_coherence(output, beats, chapters, checker, tmp_path, lambda *_: None)
    assert report.status == "needs_review" and report.rounds == 2
    assert report.restored_ids == ["1"] and not report.issues
    assert beats[0].decision == "keep" and beats[0].evidence["coherence_required"]
    assert beats[2].decision == "keep" and beats[2].required
    again = check_coherence(output, beats, chapters, checker, tmp_path, lambda *_: None)
    assert again.status == "passed" and checker.calls == 2


def test_missing_check_result_cannot_be_treated_as_passed(tmp_path):
    from pydantic import ValidationError

    output, beats, chapters = plan()

    class EmptyResponse(Checker):
        def call_json(self, name, variables, schema, log_path):
            return schema.model_validate({})

    with pytest.raises(ValidationError):
        check_coherence(output, beats, chapters, EmptyResponse([]), tmp_path, lambda *_: None)
    assert not (tmp_path / "coherence.json").exists()
    assert not list((tmp_path / "selection-cache").glob("*.json"))


@pytest.mark.parametrize("target,locked", [(4, False), (8, True)])
def test_infeasible_or_locked_context_does_not_change_plan(tmp_path, target, locked):
    output, beats, chapters = plan(target, locked)
    before = [b.model_dump() for b in beats]
    report = check_coherence(
        output, beats, chapters, Checker([[issue()]]), tmp_path, lambda *_: None
    )
    assert report.status == "needs_review" and not report.restored_ids
    assert before == [b.model_dump() for b in beats]
    if not locked:
        assert report.min_duration_s > target


def test_two_round_cap_preserves_unresolved_issues(tmp_path):
    output, beats, chapters = plan()
    checker = Checker([[issue()], [issue(restore="2")]])
    report = check_coherence(output, beats, chapters, checker, tmp_path, lambda *_: None)
    assert report.status == "needs_review" and report.rounds == checker.calls == 2
    assert beats[1].decision == "drop" and report.issues[0].restore_ids == ["2"]


def test_windows_cover_each_beat_once_with_bounded_overlap():
    _, beats, chapters = plan()
    many = [
        beats[0].model_copy(update={"id": str(i), "start_s": i * 4, "end_s": i * 4 + 4})
        for i in range(95)
    ]
    windows = list(script_windows(many, chapters))
    owned = [identifier for _, group in windows for identifier in group]
    assert len(owned) == len(set(owned)) == 95
    assert all(len(rows) <= 44 for rows, _ in windows)


def test_large_neighbors_cannot_exceed_window_budget():
    import json

    _, beats, chapters = plan()
    many = [
        beats[0].model_copy(
            update={"id": str(i), "start_s": i * 4, "end_s": i * 4 + 4, "text": "x" * 14000}
        )
        for i in range(4)
    ]
    assert all(
        len(json.dumps(rows, ensure_ascii=False).encode()) < 20500
        for rows, _ in script_windows(many, chapters)
    )


def test_worker_pauses_after_repair_api_marks_stale_and_render_reuses_check(
    client, project, monkeypatch
):
    identifier = client.post(
        f"/api/projects/{project['id']}/outputs", json={"mode": "condense"}
    ).json()["id"]
    assert client.get(f"/api/outputs/{identifier}/coherence").status_code == 404
    run_output(identifier)
    with Session(get_engine()) as session:
        beats = list(
            session.exec(
                select(Beat).where(Beat.output_id == identifier).order_by(Beat.start_s)
            ).all()
        )
        first, last = beats[0].id, beats[-1].id
        for b in beats:
            b.required = b.id == last
            b.importance = 1 if b.id == last else 0
            b.decision = "keep" if b.id == last else "drop"
            session.add(b)
        session.commit()
    original, calls = LLMClient.call_json, []

    def check(self, name, variables, schema, log_path=None, **kwargs):
        if name != "coherence_checker":
            return original(self, name, variables, schema, log_path, **kwargs)
        calls.append(variables)
        rows = {b["id"]: b for b in variables["script"]}
        return schema.model_validate(
            {"issues": [issue(at=last, restore=first)] if rows[first]["decision"] == "drop" else []}
        )

    monkeypatch.setattr(LLMClient, "call_json", check)
    detail = client.get(f"/api/outputs/{identifier}").json()
    body = {
        "target_seconds": 8,
        "coherence_enabled": True,
        "chapter_cards": True,
        "chapters": [{"id": c["id"], "required": True} for c in detail["chapters"]],
    }
    assert client.put(f"/api/outputs/{identifier}/outline", json=body).status_code == 202
    run_output(identifier, render_only=True)
    detail = client.get(f"/api/outputs/{identifier}").json()
    assert detail["output"]["status"] == "awaiting_review"
    assert detail["coherence_report"]["restored_ids"] == [first]
    assert not detail["coherence_report"]["stale"]
    assert not (output_dir(identifier) / "condensed.mp4").exists()
    assert (
        client.patch(f"/api/beats/{first}", json={"decision": "keep", "locked": True}).status_code
        == 200
    )
    assert client.get(f"/api/outputs/{identifier}/coherence").json()["stale"]
    # Restore the exact reviewed plan; re-render uses the cached second check.
    assert (
        client.patch(f"/api/beats/{first}", json={"decision": "keep", "locked": False}).status_code
        == 200
    )
    assert client.put(f"/api/outputs/{identifier}/outline", json=body).status_code == 202
    run_output(identifier, render_only=True)
    detail = client.get(f"/api/outputs/{identifier}").json()
    assert detail["output"]["status"] == "done"
    assert (
        detail["coherence_report"]["status"] == "passed" and not detail["coherence_report"]["stale"]
    )
    assert len(calls) == 2
    archive = zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/outputs/{identifier}/export.zip").content)
    )
    assert "coherence.json" in archive.namelist()


def test_failed_check_fails_output_without_rendering_or_mutating_plan(client, project, monkeypatch):
    identifier = client.post(
        f"/api/projects/{project['id']}/outputs",
        json={"mode": "condense", "settings": {"coherence_enabled": True}},
    ).json()["id"]
    run_output(identifier)
    detail = client.get(f"/api/outputs/{identifier}").json()
    body = {
        "target_seconds": 20,
        "chapters": [{"id": c["id"], "required": True} for c in detail["chapters"]],
    }
    client.put(f"/api/outputs/{identifier}/outline", json=body)
    before = client.get(f"/api/outputs/{identifier}").json()["beats"]
    monkeypatch.setattr(
        LLMClient,
        "call_json",
        lambda *_a, **_kw: (_ for _ in ()).throw(LLMError("provider unavailable")),
    )
    with pytest.raises(LLMError):
        run_output(identifier, render_only=True)
    detail = client.get(f"/api/outputs/{identifier}").json()
    assert detail["output"]["status"] == "failed" and detail["beats"] == before
    assert not (output_dir(identifier) / "condensed.mp4").exists()
    response = client.post(f"/api/outputs/{identifier}/retry")
    assert response.status_code == 202
    with Session(get_engine()) as session:
        task = session.exec(select(Task).where(Task.rq_job_id == response.json()["job_id"])).one()
        assert task.payload["render_only"]


def test_manual_drop_clears_context_requirement(client, project):
    identifier = client.post(
        f"/api/projects/{project['id']}/outputs", json={"mode": "condense"}
    ).json()["id"]
    run_output(identifier)
    with Session(get_engine()) as session:
        beat = session.exec(select(Beat).where(Beat.output_id == identifier)).first()
        beat.required = False
        beat.evidence = {"coherence_required": True, "specs": ["120 mm"]}
        session.add(beat)
        session.commit()
        beat_id = beat.id
    response = client.patch(f"/api/beats/{beat_id}", json={"decision": "drop"})
    assert response.status_code == 200
    assert response.json()["evidence"] == {"specs": ["120 mm"]}
