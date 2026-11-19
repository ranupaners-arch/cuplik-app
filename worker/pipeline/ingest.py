import hashlib
import shutil
import time
import wave

from sqlmodel import Session, select

from api.app.db import get_engine
from api.app.jobs import emit_project
from api.app.models import GlossaryTerm, Project, new_id
from api.app.schemas import Transcript
from worker.pipeline.media import (
    MediaError,
    demo_transcript,
    download,
    extract_audio,
    make_demo,
    probe_file,
    transcribe,
)
from worker.pipeline.storage import atomic_json, file_lock, json_object, project_dir
from worker.pipeline.transcription import polish_word


class ProjectProgress:
    def __init__(self, identifier):
        self.identifier = identifier
        self.last = 0
        self.stage = None

    def __call__(
        self, stage, fraction, note, *, ingest_status=None, transcript_status=None, force=False
    ):
        clock = time.monotonic()
        if not force and stage == self.stage and clock - self.last < 1:
            return
        self.last, self.stage = clock, stage
        with Session(get_engine()) as session:
            project = session.get(Project, self.identifier)
            project.stage, project.progress, project.note, project.error = (
                stage,
                round(fraction, 4),
                note,
                None,
            )
            if ingest_status:
                project.ingest_status = ingest_status
            if transcript_status:
                project.transcript_status = transcript_status
            emit_project(session, project)
            session.commit()


def checksum(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def valid_audio(path):
    try:
        with wave.open(str(path)) as source:
            return source.getnframes() > 0 and (
                source.getframerate(),
                source.getnchannels(),
                source.getsampwidth(),
            ) == (16000, 1, 2)
    except (OSError, EOFError, wave.Error):
        return False


def ingest_project(project_id: str, *, source_locked: bool = False):
    directory = project_dir(project_id)
    if not source_locked:
        with file_lock(directory / ".source.lock"):
            return ingest_project(project_id, source_locked=True)
    (directory / ".source-used").touch()
    progress = ProjectProgress(project_id)
    with file_lock(directory / ".ingest.lock"):
        with Session(get_engine()) as session:
            row = session.get(Project, project_id)
            if row is None:
                raise ValueError("Proyek tidak ditemukan")
            project = row.model_dump()
            glossary = {
                term.wrong.casefold(): term.correct
                for term in session.exec(select(GlossaryTerm).order_by(GlossaryTerm.wrong)).all()
            }
        source, audio = directory / "source.mp4", directory / "audio.wav"
        transcript_path, manifest_path = directory / "transcript.json", directory / "ingest.json"
        manifest = json_object(manifest_path)
        try:
            progress(
                "ingest",
                0.01,
                "Memeriksa sumber video dan checkpoint",
                ingest_status="running",
                # A completed transcript remains readable while an output checks cache.
                # Mark it running only if validation actually requires rebuilding it.
                transcript_status=None if project["transcript_status"] == "done" else "queued",
                force=True,
            )
            # A final filename alone is insufficient evidence of a completed download/copy.
            if source.exists():
                try:
                    probe_file(source)
                    stamp = {"size": source.stat().st_size, "mtime_ns": source.stat().st_mtime_ns}
                    if (
                        manifest.get("source_stat") != stamp
                        and manifest.get("source_sha256")
                        and checksum(source) != manifest["source_sha256"]
                    ):
                        raise MediaError("Cache sumber berubah")
                except (MediaError, ValueError):
                    source.rename(directory / f"source.corrupt-{new_id()[:8]}.mp4")
            metadata = {}
            if not source.exists():
                if project["source_kind"] == "demo":
                    make_demo(source)
                elif project["source_kind"] == "upload":
                    from api.app.config import get_settings

                    uploaded = get_settings().storage / "uploads" / f"{project['source_ref']}.bin"
                    if not uploaded.exists():
                        raise MediaError(
                            "Berkas unggahan sumber hilang; unggah ulang sebagai proyek baru."
                        )
                    temporary = directory / "source.tmp.mp4"
                    shutil.copyfile(uploaded, temporary)
                    probe_file(temporary)
                    temporary.replace(source)
                else:
                    metadata = download(
                        project["source_ref"],
                        source,
                        lambda fraction, note: progress("download", 0.02 + 0.18 * fraction, note),
                    )
            media = probe_file(source)
            stamp = {"size": source.stat().st_size, "mtime_ns": source.stat().st_mtime_ns}
            digest = (
                manifest.get("source_sha256")
                if manifest.get("source_stat") == stamp
                else checksum(source)
            )
            previous_digest = manifest.get("source_sha256")
            manifest.update(
                {
                    "version": 1,
                    "source_sha256": digest,
                    "source_stat": stamp,
                    "duration_s": media["duration_s"],
                    **metadata,
                }
            )
            atomic_json(manifest_path, manifest)
            with Session(get_engine()) as session:
                row = session.get(Project, project_id)
                row.duration_s = media["duration_s"]
                if metadata.get("title") and project["title"] == "Video baru":
                    row.title = metadata["title"]
                session.add(row)
                session.commit()
            progress("audio", 0.2, "Menyiapkan WAV 16 kHz mono", ingest_status="done", force=True)
            audio_manifest = directory / "audio.json"
            audio_valid = json_object(audio_manifest).get(
                "source_sha256"
            ) == digest and valid_audio(audio)
            if not audio_valid:
                extract_audio(source, audio)
                atomic_json(audio_manifest, {"source_sha256": digest})
            cached = None
            if transcript_path.exists() and previous_digest in (None, digest):
                try:
                    cached = Transcript.model_validate_json(transcript_path.read_text())
                    if cached.sentences[-1].end > media["duration_s"] + 0.2:
                        cached = None
                except ValueError:
                    pass
            if cached is None:
                progress(
                    "transcribe",
                    0.3,
                    "Menyiapkan transkripsi",
                    transcript_status="running",
                    force=True,
                )
                if (directory / "sidecar.json").exists():
                    transcript = Transcript.model_validate_json(
                        (directory / "sidecar.json").read_text()
                    )
                    transcript = transcript.model_copy(
                        update={
                            "sentences": [
                                s.model_copy(update={"text": polish_word(s.text, glossary)})
                                for s in transcript.sentences
                            ],
                            "words": [
                                w.model_copy(update={"text": polish_word(w.text, glossary)})
                                for w in transcript.words
                            ],
                            "source": "sidecar",
                        }
                    )
                elif project["source_kind"] == "demo":
                    transcript = demo_transcript()
                else:
                    transcript = transcribe(
                        audio,
                        checkpoint_dir=directory / "transcription",
                        glossary=glossary,
                        language=project["requested_language"],
                        title=metadata.get("title", project["title"]),
                        progress=lambda fraction, note: progress(
                            "transcribe", 0.3 + 0.69 * fraction, note
                        ),
                    )
                if transcript.sentences[-1].end > media["duration_s"] + 0.2:
                    raise MediaError("Timestamp transkrip melebihi durasi video.")
                atomic_json(transcript_path, transcript.model_dump())
                cached = transcript
            with Session(get_engine()) as session:
                row = session.get(Project, project_id)
                row.language = cached.language
                session.add(row)
                session.commit()
            progress(
                "done",
                1,
                "Sumber, audio, dan transkrip siap; checkpoint tersimpan",
                ingest_status="done",
                transcript_status="done",
                force=True,
            )
        except Exception as exc:
            with Session(get_engine()) as session:
                row = session.get(Project, project_id)
                row.error = str(exc)[:1500]
                row.note = "Proses gagal; bagian yang telah selesai tetap tersimpan untuk retry"
                if row.ingest_status != "done":
                    row.ingest_status = "failed"
                row.transcript_status = "failed"
                emit_project(session, row)
                session.commit()
            raise
