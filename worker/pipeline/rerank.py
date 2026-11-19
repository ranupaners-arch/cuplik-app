import unicodedata
from collections import Counter
from pathlib import Path

from worker.pipeline.boundaries import iou
from worker.pipeline.contracts import Reranking
from worker.pipeline.llm import LLMValidationError
from worker.pipeline.scoring import Finalist
from worker.pipeline.selection_cache import call_stage


def topic_key(topic: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", topic).casefold().split())


def select_diverse(ranked: list[Finalist], count: int, rejected: list | None = None):
    accepted, topics = [], Counter()
    for item in ranked:
        topic = topic_key(item.packaging.topic)
        reason = ""
        if topics[topic] >= 2:
            reason = "topic_limit"
        elif any(
            iou(
                (item.boundary.start, item.boundary.end), (other.boundary.start, other.boundary.end)
            )
            > 0.3
            for other in accepted
        ):
            reason = "overlap_iou_gt_0.3"
        if reason:
            if rejected is not None:
                rejected.append({"stage": "diversity", "id": item.id, "reason": reason})
            continue
        accepted.append(item)
        topics[topic] += 1
        if len(accepted) >= count:
            break
    return accepted


def rerank(client, candidates: list[Finalist], count: int, directory: Path, audit: dict):
    finalists = sorted(candidates, key=lambda c: (-c.base_score, int(c.id[1:])))[:20]
    if not finalists:
        return []
    variables = {
        "platform": str(audit.get("settings", {}).get("platform", "youtube"))
        + "; tujuan "
        + str(audit.get("settings", {}).get("purpose", "discovery")),
        "finalists": [
            {
                "id": c.id,
                "topic": c.packaging.topic,
                "base_score": c.base_score,
                "duration": round(c.boundary.end - c.boundary.start, 3),
                "text": c.text,
            }
            for c in finalists
        ],
    }
    by_id, ranked, seen = {c.id: c for c in finalists}, [], set()
    try:
        response = call_stage(client, "reranker", variables, Reranking, directory)
        for item in response.ranking:
            if item.id not in by_id or item.id in seen:
                audit["warnings"].append(
                    {"stage": "reranker", "id": item.id, "reason": "unknown_or_duplicate_rank_id"}
                )
                continue
            found = by_id[item.id]
            found.rerank_note = item.note
            ranked.append(found)
            seen.add(item.id)
    except LLMValidationError as exc:
        audit["warnings"].append({"stage": "reranker", "reason": str(exc)})
    for c in finalists:
        if c.id not in seen:
            c.rerank_note = "Tidak diurutkan reranker; memakai urutan skor dasar sebagai fallback."
            ranked.append(c)
    accepted = select_diverse(ranked, count, audit["rejected"])
    baseline = select_diverse(finalists, count)
    audit["base_order"] = [c.id for c in finalists]
    audit["reranked_order"] = [c.id for c in ranked]
    audit["baseline_selected"] = [c.id for c in baseline]
    audit["selected"] = [c.id for c in accepted]
    audit["metrics"] = {
        "finalists": len(finalists),
        "selected": len(accepted),
        "unique_topics": len({topic_key(c.packaging.topic) for c in accepted}),
        "max_per_topic": max(
            Counter(topic_key(c.packaging.topic) for c in accepted).values(), default=0
        ),
        "order_changed": audit["base_order"] != audit["reranked_order"],
        "selection_changed": set(audit["baseline_selected"]) != set(audit["selected"]),
        "mean_rank_displacement": sum(
            abs(i - next(j for j, c in enumerate(ranked) if c.id == item.id))
            for i, item in enumerate(finalists)
        )
        / len(finalists),
        "top5_unique_topics_before": len({topic_key(c.packaging.topic) for c in finalists[:5]}),
        "top5_unique_topics_after": len({topic_key(c.packaging.topic) for c in ranked[:5]}),
        "selected_unique_topics_before": len({topic_key(c.packaging.topic) for c in baseline}),
        "selected_unique_topics_after": len({topic_key(c.packaging.topic) for c in accepted}),
        "mean_score_before": sum(c.base_score for c in baseline) / max(1, len(baseline)),
        "mean_score_after": sum(c.base_score for c in accepted) / max(1, len(accepted)),
    }
    return accepted
