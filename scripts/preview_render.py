"""Render a reviewable replacement from an existing selection; no LLM/ASR calls."""

import argparse
import json
import os
import shutil
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--directory", type=Path, default=Path("data/phase3-validation"))
    parser.add_argument("--layout", choices=["auto", "source", "portrait"], default="auto")
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--cold-open", action="store_true")
    parser.add_argument("--purpose", choices=["tutorial", "discovery"], default="tutorial")
    parser.add_argument(
        "--platform",
        choices=["youtube", "youtube_shorts", "tiktok", "instagram"],
        default="youtube",
    )
    parser.add_argument("--caption-preset", choices=["compact", "karaoke"], default="compact")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--focus-mode", choices=["safe", "activity", "manual"], default="safe")
    parser.add_argument(
        "--focus-region", type=float, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT")
    )
    args = parser.parse_args()
    os.environ["RENDER_HEIGHT"] = str(args.height)
    from api.app.config import get_settings
    from api.app.models import Clip
    from api.app.schemas import (
        FocusRegion,
        OutputSettings,
        Transcript,
        VisualFocus,
        retention_profile,
    )
    from worker.pipeline.render import render_clip

    get_settings.cache_clear()
    region = (
        FocusRegion(**dict(zip(("x", "y", "width", "height"), args.focus_region, strict=True)))
        if args.focus_region
        else None
    )
    focus = VisualFocus(mode=args.focus_mode, region=region)
    OutputSettings(
        purpose=args.purpose, platform=args.platform, layout=args.layout, visual_focus=focus
    )
    started = time.monotonic()
    transcript = Transcript.model_validate_json(args.transcript.read_text())
    selection = json.loads(args.selection.read_text())
    candidates = {c["id"]: c for c in selection["candidates"]}
    args.directory.mkdir(parents=True, exist_ok=True)
    result = []
    for rank, identifier in enumerate(selection["selected"][: max(1, args.limit)], 1):
        candidate = candidates[identifier]
        c, boundary = candidate["packaging"], candidate["boundary"]
        clip = Clip(
            output_id="preview",
            rank=rank,
            start_s=boundary["start"],
            end_s=boundary["end"],
            topic=c["topic"],
            titles=c["titles"],
            hook_options=c["hook_texts"],
            score=candidate["base_score"],
            rubric=c["scores"],
            reason=c["reason"],
            selection={
                "boundary_precision": boundary["precision"],
                "cold_open_id": candidate["moment"].get("cold_open_id"),
                "emphasis_word_ids": c.get("emphasis_word_ids", []),
            },
            keywords=c.get("keywords", []),
            emoji=c.get("emoji", []),
            purpose=args.purpose,
            platform=args.platform,
            retention={
                **retention_profile(args.purpose, args.caption_preset).model_dump(),
                "cold_open": args.cold_open,
            },
            layout=args.layout,
            visual_focus=focus.model_dump(),
        )
        path, qc = render_clip(args.source.resolve(), clip, transcript, args.directory.resolve())
        destination = args.directory / f"clip-{rank}.mp4"
        shutil.copy2(path, destination)
        for kind in ("framing", "captions", "edl"):
            shutil.copy2(
                path.with_suffix(f".{kind}.json"), destination.with_suffix(f".{kind}.json")
            )
        shutil.copy2(path.with_suffix(".jpg"), destination.with_suffix(".jpg"))
        shutil.copy2(
            path.parent / "reframe" / f"{clip.id}.json", destination.with_suffix(".reframe.json")
        )
        result.append(
            {
                "path": str(destination.resolve()),
                "start_s": clip.start_s,
                "end_s": clip.end_s,
                "qc": qc,
            }
        )
    report = {
        "renderer": "delivery-controls-v4",
        "elapsed_s": round(time.monotonic() - started, 3),
        "layout": args.layout,
        "purpose": args.purpose,
        "platform": args.platform,
        "visual_focus": focus.model_dump(),
        "llm_called": False,
        "asr_called": False,
        "clips": result,
    }
    (args.directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "clips": [
                    {
                        "path": c["path"],
                        "width": c["qc"]["width"],
                        "height": c["qc"]["height"],
                        "framing": c["qc"]["framing"]["mode"],
                        "content": c["qc"]["framing"]["content_kind"],
                        "max_caption_words": c["qc"]["caption_max_words"],
                        "max_caption_lines": c["qc"]["caption_max_lines"],
                        "hook_shown": c["qc"]["hook_shown"],
                        "passed": c["qc"]["passed"],
                    }
                    for c in result
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
