"""One policy shared by review, solver and renderer; a transcript gap is not proof of silence."""

import math

from api.app.schemas import OutputSettings


def reviewable(beat) -> bool:
    return (
        beat.kind == "visual"
        and beat.label in {"manual", "idle", "repeat"}
        and not beat.evidence.get("specs")
    )


def speed_limit(beat, settings: OutputSettings) -> float:
    if not settings.timelapse_enabled:
        return settings.max_speech_speed
    duration = beat.end_s - beat.start_s
    if beat.kind == "visual" and (beat.label == "spec" or beat.evidence.get("specs")):
        return 1.0
    if beat.label == "result":
        return max(1.0, min(settings.max_speech_speed, duration / 2))
    if (
        settings.timelapse_enabled
        and beat.timelapse_approved
        and reviewable(beat)
        and duration >= 2.4
    ):
        return min(settings.max_visual_speed, duration / 1.2)
    return settings.max_speech_speed


def validate_speed(beat, rate: float, settings: OutputSettings) -> str:
    if not math.isfinite(rate) or rate < 1 or rate > speed_limit(beat, settings) + 1e-6:
        raise ValueError("Kecepatan melampaui batas narasi atau timelapse yang telah ditinjau.")
    if rate > settings.max_speech_speed + 1e-6:
        if rate < 2 - 1e-6:
            raise ValueError("Timelapse memakai kecepatan minimal 2x.")
        return "muted"
    return "source"
