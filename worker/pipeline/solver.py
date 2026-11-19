from dataclasses import dataclass

from api.app.models import Beat, Chapter


@dataclass
class InfeasibleDuration(ValueError):
    minimum_seconds: float
    message: str = "Target terlalu pendek untuk bagian wajib dan keputusan terkunci."

    def __str__(self):
        return f"{self.message} Durasi minimum {self.minimum_seconds:.2f} detik."


def solve(beats: list[Beat], chapters: list[Chapter], target: float, max_speed: float) -> dict:
    chapter_by_id = {chapter.id: chapter for chapter in chapters}
    selected = set()
    flexible = []
    fixed_duration = 0.0
    optional = []
    for beat in beats:
        required = beat.required and chapter_by_id[beat.chapter_id].required
        duration = beat.end_s - beat.start_s
        if beat.locked:
            if beat.decision == "drop":
                if required:
                    raise InfeasibleDuration(
                        0, "Bagian wajib terkunci sebagai dibuang. Buka kunci atau ubah keputusan."
                    )
                continue
            selected.add(beat.id)
            fixed_duration += duration / (beat.speed if beat.decision == "speed" else 1)
        elif required:
            selected.add(beat.id)
            flexible.append(beat)
        else:
            optional.append(beat)
    minimum = fixed_duration + sum((b.end_s - b.start_s) / max_speed for b in flexible)
    if minimum > target + 0.001:
        raise InfeasibleDuration(round(minimum, 3))
    # Prefer supporting sentences of required chapters, then source order.
    optional.sort(key=lambda b: (not chapter_by_id[b.chapter_id].required, b.start_s))
    for beat in optional:
        cost = (beat.end_s - beat.start_s) / max_speed
        if minimum + cost <= target + 0.001:
            flexible.append(beat)
            selected.add(beat.id)
            minimum += cost
    if not selected:
        raise InfeasibleDuration(
            0, "Tidak ada bagian terpilih. Pilih setidaknya satu bab atau beat."
        )
    speed = max(
        1.0, sum(b.end_s - b.start_s for b in flexible) / max(target - fixed_duration, 0.001)
    )
    speed = min(max_speed, speed)
    plan = []
    for beat in beats:
        if beat.locked:
            decision, rate = beat.decision, beat.speed if beat.decision == "speed" else 1.0
        elif beat.id in selected:
            decision, rate = ("speed" if speed > 1.0001 else "keep"), speed
        else:
            decision, rate = "drop", 1.0
        plan.append({"id": beat.id, "decision": decision, "speed": rate})
    by_id = {b.id: b for b in beats}
    duration = sum(
        (by_id[p["id"]].end_s - by_id[p["id"]].start_s) / p["speed"]
        for p in plan
        if p["decision"] != "drop"
    )
    return {
        "beats": plan,
        "actual_duration_s": round(duration, 3),
        "target_seconds": target,
        "within_tolerance": abs(duration - target) <= target * 0.03,
        "minimum_seconds": round(minimum, 3),
    }
