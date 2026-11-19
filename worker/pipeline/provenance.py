"""Bind reviews and newly accepted output plans to immutable source/transcript contents."""

import hashlib

from api.app.schemas import Transcript
from worker.pipeline.storage import json_object, project_dir


def transcript_fingerprint(transcript: Transcript) -> str:
    return hashlib.sha256(transcript.model_dump_json().encode()).hexdigest()


def project_snapshot(project_id: str):
    directory = project_dir(project_id)
    manifest = json_object(directory / "ingest.json")
    source = manifest.get("source_sha256", "")
    if not isinstance(source, str) or len(source) != 64:
        raise ValueError("Checkpoint sumber belum siap; siapkan sumber terlebih dahulu")
    transcript = Transcript.model_validate_json((directory / "transcript.json").read_text())
    return {
        "source_sha256": source,
        "transcript_sha256": transcript_fingerprint(transcript),
    }, transcript
