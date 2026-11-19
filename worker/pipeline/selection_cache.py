import hashlib
import json
from pathlib import Path

from api.app.config import ROOT
from worker.pipeline.llm import LLMClient
from worker.pipeline.storage import atomic_json, json_object


def call_stage(client: LLMClient, name, variables, schema, directory: Path):
    """Cache only validated replies, keyed by data, prompt, schema, provider and model."""
    prompt_files = sorted((ROOT / "worker/prompts").glob(f"{name}.*txt"))
    digest = hashlib.sha256(
        json.dumps(
            {
                "version": 1,
                "name": name,
                "variables": variables,
                "schema": schema.model_json_schema(),
                "provider": client.settings.llm_provider,
                "model": client.settings.llm_model_fast,
                "prompts": [p.read_text() for p in prompt_files],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    cache = directory / "selection-cache"
    cache.mkdir(exist_ok=True)
    path = cache / f"{name}-{digest}.json"
    cached = json_object(path)
    if cached:
        try:
            return schema.model_validate(cached)
        except ValueError:
            pass
    result = client.call_json(name, variables, schema, directory / "llm_log.jsonl")
    atomic_json(path, result.model_dump())
    return result
