from dataclasses import dataclass

from api.app.models import Beat, Chapter
from api.app.schemas import OutputSettings
from worker.pipeline.condense_policy import speed_limit, validate_speed


@dataclass
class InfeasibleDuration(ValueError):
    minimum_seconds: float
    message: str = "Target terlalu pendek untuk bagian wajib dan keputusan terkunci."

    def __str__(self):
        return f"{self.message} Durasi minimum {self.minimum_seconds:.2f} detik."


def solve(
    beats: list[Beat],
    chapters: list[Chapter],
    target: float,
    max_speed: float,
    *,
    settings: OutputSettings | None = None,
) -> dict:
    settings = settings or OutputSettings(max_speech_speed=max_speed)
    chapter_by_id = {c.id: c for c in chapters}
    caps = {b.id: speed_limit(b, settings) for b in beats}
    lengths = {b.id: b.end_s - b.start_s for b in beats}
    selected, rates, flexible, optional = set(), {}, [], []
    fixed = 0.0
    for beat in beats:
        required = (beat.required and chapter_by_id[beat.chapter_id].required) or (
            settings.coherence_enabled and beat.evidence.get("coherence_required", False)
        )
        if beat.locked:
            if beat.decision == "drop":
                if required:
                    raise InfeasibleDuration(
                        0, "Bagian wajib terkunci sebagai dibuang. Buka kunci atau ubah keputusan."
                    )
                continue
            rate = beat.speed if beat.decision == "speed" else 1.0
            validate_speed(beat, rate, settings)
            rates[beat.id] = rate
            selected.add(beat.id)
            fixed += lengths[beat.id] / rate
        elif required:
            selected.add(beat.id)
            flexible.append(beat)
        else:
            optional.append(beat)
    minimum = fixed + sum(lengths[b.id] / caps[b.id] for b in flexible)
    if minimum > target + 0.001:
        raise InfeasibleDuration(round(minimum, 3))
    required_minimum = minimum
    optional.sort(
        key=lambda b: (
            -(b.importance * (1.25 if chapter_by_id[b.chapter_id].required else 1))
            / (lengths[b.id] / caps[b.id]),
            b.start_s,
            b.id,
        )
    )
    for beat in optional:
        cost = lengths[beat.id] / caps[beat.id]
        if beat.importance > 0 and minimum + cost <= target + 0.001:
            selected.add(beat.id)
            flexible.append(beat)
            minimum += cost
    if not selected:
        raise InfeasibleDuration(
            0, "Tidak ada bagian terpilih. Pilih setidaknya satu bab atau beat."
        )
    rates.update({b.id: 1.0 for b in flexible})

    def duration(candidate):
        return sum(lengths[i] / candidate[i] for i in selected)

    # Compress approved visual work first. Narration stays at 1x when this suffices.
    visual = [b for b in flexible if caps[b.id] > settings.max_speech_speed + 1e-6]
    visual_ids = {b.id for b in visual}
    ordinary = [b for b in flexible if b.id not in visual_ids]
    for group, high_speed in [(visual, True), (ordinary, False)]:
        if not group or duration(rates) <= target + 1e-6:
            continue
        original = rates.copy()
        low, high = 1.0, max(caps[b.id] for b in group)

        def candidate(factor, original=original, high_speed=high_speed, group=group):
            return {
                **original,
                **{
                    b.id: min(caps[b.id], max(2, factor) if high_speed and factor > 1 else factor)
                    for b in group
                },
            }

        if duration(candidate(high)) > target:
            rates = candidate(high)
            continue
        for _ in range(55):
            middle = (low + high) / 2
            if duration(candidate(middle)) > target:
                low = middle
            else:
                high = middle
        rates = candidate(high)
        # A 1x→2x visual jump may leave a gap. Prefer 1x if it already meets ±3%.
        if high_speed and abs(duration(original) - target) <= target * 0.03:
            rates = original
    plan = []
    for beat in beats:
        if beat.id not in selected:
            plan.append({"id": beat.id, "decision": "drop", "speed": 1.0, "audio_mode": "source"})
            continue
        rate = round(rates[beat.id], 8)
        audio = validate_speed(beat, rate, settings)
        plan.append(
            {
                "id": beat.id,
                "decision": beat.decision
                if beat.locked
                else "speed"
                if rate > 1.00000001
                else "keep",
                "speed": rate,
                "audio_mode": audio,
            }
        )
    actual = sum(lengths[p["id"]] / p["speed"] for p in plan if p["decision"] != "drop")
    return {
        "beats": plan,
        "actual_duration_s": round(actual, 3),
        "target_seconds": target,
        "within_tolerance": abs(actual - target) <= target * 0.03 + 1e-6,
        "minimum_seconds": round(required_minimum, 3),
        "muted_timelapse_beats": sum(p["audio_mode"] == "muted" for p in plan),
    }
