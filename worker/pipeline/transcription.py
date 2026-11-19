import hashlib
import json
import math
import platform
import re
import sys
import wave
from pathlib import Path

from api.app.config import get_settings
from api.app.schemas import Sentence, Transcript, Word
from worker.pipeline.storage import atomic_json


def repeated_ngram(text: str) -> bool:
    tokens = re.findall(r"\w+", text.casefold())
    for size in range(3, min(12, len(tokens) // 3) + 1):
        for start in range(len(tokens) - 3 * size + 1):
            a = tokens[start : start + size]
            if (
                a
                == tokens[start + size : start + size * 2]
                == tokens[start + size * 2 : start + size * 3]
            ):
                return True
    return False


def polish_word(text: str, glossary: dict[str, str]) -> str:
    return re.sub(r"[\w'’-]+", lambda m: glossary.get(m.group(0).casefold(), m.group(0)), text)


def segment_words(
    words: list[dict], language: str, glossary: dict[str, str] | None = None, *, warnings=None
) -> Transcript:
    from worker.pipeline.media import MediaError

    glossary = glossary or {}
    normalized = []
    previous = 0.0
    for item in words:
        try:
            start, end = float(item["start"]), float(item["end"])
            text = polish_word(str(item["text"]).strip(), glossary)
            if (
                not math.isfinite(start)
                or not math.isfinite(end)
                or not text
                or end <= max(start, previous, 0)
            ):
                continue
            start = max(0, previous, start)
            normalized.append(Word(id=f"w{len(normalized) + 1}", start=start, end=end, text=text))
            previous = end
        except (KeyError, TypeError, ValueError):
            continue
    if not normalized:
        raise MediaError(
            "Tidak ada percakapan terdeteksi. Unggah transkrip bertimestamp jika diperlukan."
        )
    groups = []
    current = []
    for word in normalized:
        if current and (
            word.start - current[-1].end >= 0.6
            or len(current) >= 25
            or current[-1].text.endswith((".", "?", "!", "؟"))
        ):
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)
    # Merge short fragments without crossing long silence or breaking the 25-word limit.
    merged = []
    i = 0
    while i < len(groups):
        group = groups[i]
        if (
            len(group) < 3
            and merged
            and len(merged[-1]) + len(group) <= 25
            and group[0].start - merged[-1][-1].end < 1.5
        ):
            merged[-1].extend(group)
        elif (
            len(group) < 3
            and i + 1 < len(groups)
            and len(group) + len(groups[i + 1]) <= 25
            and groups[i + 1][0].start - group[-1].end < 1.5
        ):
            groups[i + 1] = group + groups[i + 1]
        else:
            merged.append(group)
        i += 1
    sentences = [
        Sentence(
            id=f"s{i + 1}",
            start=group[0].start,
            end=group[-1].end,
            text=" ".join(w.text for w in group),
            word_ids=[w.id for w in group],
        )
        for i, group in enumerate(merged)
    ]
    return Transcript(
        language=language,
        source="whisper",
        sentences=sentences,
        words=normalized,
        warnings=warnings or [],
    )


def backend_name() -> str:
    value = get_settings().transcription_backend
    if value == "auto":
        return (
            "mlx"
            if sys.platform == "darwin" and platform.machine() in ("arm64", "aarch64")
            else "faster-whisper"
        )
    return value


def _mlx_speech(path: Path) -> bool:
    """WebRTC VAD rejects silence before invoking the MLX decoder."""
    from worker.pipeline.media import MediaError

    try:
        import webrtcvad
    except ImportError as exc:
        raise MediaError("VAD MLX belum dipasang. Jalankan uv sync --extra mlx.") from exc
    detector = webrtcvad.Vad(2)
    with wave.open(str(path)) as source:
        voiced = 0
        while frame := source.readframes(480):  # 30 ms at 16 kHz, 16-bit mono.
            if len(frame) != 960:
                break
            voiced += detector.is_speech(frame, 16000)
            if voiced >= 3:
                return True
    return False


class Decoder:
    def __init__(self):
        from worker.pipeline.media import MediaError

        settings = get_settings()
        self.backend = backend_name()
        if self.backend == "mlx":
            try:
                import mlx_whisper
            except ImportError as exc:
                raise MediaError(
                    "MLX belum dipasang. Jalankan uv sync --extra mlx atau unggah sidecar transkrip."
                ) from exc
            self.model = mlx_whisper
        else:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise MediaError(
                    "Whisper belum dipasang. Jalankan uv sync --extra transcription atau unggah sidecar transkrip."
                ) from exc
            self.model = WhisperModel(
                settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
            )

    def decode(self, path, language, initial_prompt, progress):
        settings = get_settings()
        if self.backend == "mlx":
            if not _mlx_speech(path):
                return [], language or "id"
            model = settings.whisper_model
            repository = model if "/" in model else f"mlx-community/whisper-{model}-mlx"
            result = self.model.transcribe(
                str(path),
                path_or_hf_repo=repository,
                word_timestamps=True,
                condition_on_previous_text=False,
                initial_prompt=initial_prompt,
                language=language,
            )
            return result.get("segments", []), result.get("language") or language or "id"
        result, info = self.model.transcribe(
            str(path),
            language=language,
            initial_prompt=initial_prompt,
            word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        segments = []
        for segment in result:
            segments.append(
                {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "no_speech_prob": segment.no_speech_prob,
                    "words": [
                        {"start": w.start, "end": w.end, "word": w.word}
                        for w in segment.words or []
                    ],
                }
            )
            progress(segment.end)
        return segments, info.language


def transcribe(
    path: Path,
    *,
    checkpoint_dir: Path | None = None,
    glossary=None,
    language="auto",
    title="",
    progress=lambda *_: None,
) -> Transcript:
    """Input must be 16 kHz mono PCM WAV; commit each completed chunk atomically."""
    from worker.pipeline.media import MediaError

    settings = get_settings()
    glossary = glossary or {}
    directory = checkpoint_dir or path.parent / "transcription"
    directory.mkdir(parents=True, exist_ok=True)
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    profile = {
        "audio": digest,
        "backend": backend_name(),
        "model": settings.whisper_model,
        "device": settings.whisper_device,
        "compute": settings.whisper_compute_type,
        "language": language,
        "glossary": glossary,
        "title": title,
        "chunk_seconds": settings.whisper_chunk_seconds,
        "version": 2,
    }
    key = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()[:20]

    def chunk_digest(data):
        return hashlib.sha256(
            json.dumps(
                {"language": data.get("language"), "segments": data["segments"]},
                sort_keys=True,
                allow_nan=False,
            ).encode()
        ).hexdigest()

    initial_prompt = (
        ", ".join([title[:200], *list(dict.fromkeys(glossary.values()))[:40]]).strip(", ") or None
    )
    selected_language = None if language == "auto" else language
    decoder = None
    words, dropped, warnings = [], [], []
    with wave.open(str(path)) as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
            raise MediaError("Audio transkripsi harus WAV PCM 16 kHz mono.")
        total = source.getnframes() / 16000
        samples = settings.whisper_chunk_seconds * 16000
        chunk_count = math.ceil(source.getnframes() / samples)
        for index in range(chunk_count):
            offset = index * settings.whisper_chunk_seconds
            length = min(settings.whisper_chunk_seconds, total - offset)
            cache = directory / f"{key}-{index:05d}.json"
            data = None
            try:
                cached = json.loads(cache.read_text())
                if (
                    isinstance(cached, dict)
                    and cached.get("profile") == key
                    and cached.get("index") == index
                    and isinstance(cached.get("segments"), list)
                    and cached.get("checksum") == chunk_digest(cached)
                ):
                    data = cached
            except (OSError, ValueError):
                pass
            if data is None:
                progress(offset / total, f"Menyiapkan transkripsi bagian {index + 1}/{chunk_count}")
                source.setpos(index * samples)
                chunk_path = directory / f"{key}-{index:05d}.wav"
                with wave.open(str(chunk_path), "wb") as chunk:
                    chunk.setnchannels(1)
                    chunk.setsampwidth(2)
                    chunk.setframerate(16000)
                    chunk.writeframes(source.readframes(samples))
                try:
                    if decoder is None:
                        decoder = Decoder()

                    def report(seconds, offset=offset, length=length):
                        processed = min(total, offset + max(0, min(length, seconds)))
                        progress(
                            processed / total,
                            f"Mentranskrip {processed:.1f}/{total:.1f} detik ({processed / total:.0%})",
                        )

                    segments, detected = decoder.decode(
                        chunk_path, selected_language, initial_prompt, report
                    )
                    data = {
                        "profile": key,
                        "index": index,
                        "language": detected,
                        "segments": segments,
                    }
                    data["checksum"] = chunk_digest(data)
                    atomic_json(cache, data)
                finally:
                    chunk_path.unlink(missing_ok=True)
            if selected_language is None:
                selected_language = data.get("language") or "id"
            for segment in data["segments"]:
                if segment.get("no_speech_prob", 0) > 0.8 or repeated_ngram(
                    segment.get("text", "")
                ):
                    dropped.append(
                        {
                            "start": offset + segment.get("start", 0),
                            "end": offset + segment.get("end", 0),
                            "reason": "no_speech"
                            if segment.get("no_speech_prob", 0) > 0.8
                            else "repeated_ngram",
                        }
                    )
                    continue
                for word in segment.get("words", []):
                    start, end = word.get("start", -1), word.get("end", -1)
                    if (
                        not isinstance(start, (float, int))
                        or not isinstance(end, (float, int))
                        or start < 0
                        or end > length + 0.25
                    ):
                        continue
                    words.append(
                        {
                            "start": offset + start,
                            "end": min(offset + end, offset + length),
                            "text": word.get("word", ""),
                        }
                    )
            progress(
                (offset + length) / total,
                f"Transkripsi {offset + length:.1f}/{total:.1f} detik; {index + 1}/{chunk_count} bagian tersimpan",
            )
    if dropped:
        warnings.append(
            f"{len(dropped)} segmen ditandai hening/pengulangan dan dikeluarkan; periksa transcription/report.json."
        )
    atomic_json(
        directory / "report.json",
        {
            "profile": profile,
            "dropped_segments": dropped,
            "warnings": warnings,
            "chunk_count": chunk_count,
        },
    )
    return segment_words(words, selected_language or "id", glossary, warnings=warnings)
