"""Exercise Phase 4 through the running web proxy using a synthetic demo and mock LLM."""

import argparse
import json
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--report", type=Path, default=Path("data/phase4-validation/docker-smoke.json")
    )
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=30) as client:

        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response

        assert request("GET", "/api/config").json()["provider"] == "mock", (
            "Use an isolated mock deployment"
        )
        original = request("GET", "/api/preferences").json()

        def completed(identifier):
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                detail = request("GET", f"/api/outputs/{identifier}").json()
                if detail["output"]["status"] == "failed":
                    raise AssertionError(detail["output"]["error"])
                if detail["output"]["status"] == "done":
                    return detail
                time.sleep(0.3)
            raise TimeoutError("Output did not complete")

        try:
            defaults = json.loads(json.dumps(original))
            defaults["clips"].update(
                clip_count=1, purpose="tutorial", platform="youtube_shorts", layout="auto"
            )
            defaults["clips"]["retention"].update(
                shorten_pauses=False, remove_fillers=False, zoom=False, emphasis=False
            )
            defaults["condense"]["target_seconds"] = 25
            request("PUT", "/api/preferences", json=defaults)
            project = request("POST", "/api/projects", json={"source_kind": "demo"}).json()
            output = request(
                "POST", f"/api/projects/{project['id']}/outputs", json={"mode": "clips"}
            ).json()
            identifier = output["id"]
            detail = completed(identifier)
            clip = detail["clips"][0]
            assert clip["platform"] == "youtube_shorts"
            assert clip["qc"]["width"] * 16 == clip["qc"]["height"] * 9
            sentence = next(
                s
                for s in detail["transcript"]["sentences"]
                if s["start"] < clip["end_s"] and s["end"] > clip["start_s"]
            )
            request(
                "PATCH",
                f"/api/clips/{clip['id']}",
                json={
                    "caption_overrides": {sentence["id"]: "Caption diperbaiki pada uji kontainer."},
                    "purpose": "tutorial",
                    "platform": "youtube",
                    "layout": "source",
                    "rating": "up",
                    "rating_note": "Konteks demonstrasi utuh",
                },
            )
            request("POST", f"/api/clips/{clip['id']}/render")
            fresh = completed(identifier)["clips"][0]
            assert not fresh["needs_render"]
            assert fresh["render_fingerprint"] != clip["render_fingerprint"]
            assert fresh["qc"]["width"] > fresh["qc"]["height"]
            assert fresh["rating_note"] == "Konteks demonstrasi utuh"
            assert request("GET", fresh["file_url"]).content[4:8] == b"ftyp"
            assert (
                request("GET", fresh["thumbnail_url"])
                .headers["content-type"]
                .startswith("image/jpeg")
            )
            assert request("GET", f"/api/outputs/{identifier}/export.zip").content[:2] == b"PK"
            assert "complete" in request("GET", f"/api/outputs/{identifier}/events").text
            report = {
                "status": "passed",
                "provider": "mock",
                "source": "synthetic_demo",
                "project_id": project["id"],
                "output_id": identifier,
                "shorts_dimensions": [clip["qc"]["width"], clip["qc"]["height"]],
                "source_dimensions": [fresh["qc"]["width"], fresh["qc"]["height"]],
                "preferences_saved": True,
                "single_clip_rerender": True,
                "rating_note_saved": True,
                "mp4_thumbnail_zip_sse": True,
            }
        finally:
            request("PUT", "/api/preferences", json=original)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
