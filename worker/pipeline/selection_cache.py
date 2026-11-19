import hashlib
import json
from pathlib import Path

from api.app.config import ROOT
from worker.pipeline.llm import LLMClient, LLMValidationError
from worker.pipeline.storage import atomic_json, json_object


def call_stage(
    client: LLMClient,
    name,
    variables,
    schema,
    directory: Path,
    *,
    images=None,
    model=None,
    validate=None,
):
    """Cache only validated replies, keyed by data, prompt, schema, provider and model."""
    prompt_files = sorted((ROOT / "worker/prompts").glob(f"{name}.*txt"))
    inputs = {
        "version": 1,
        "name": name,
        "variables": variables,
        "schema": schema.model_json_schema(),
        "provider": client.settings.llm_provider,
        "model": model or client.settings.llm_model_fast,
        "prompts": [p.read_text() for p in prompt_files],
    }
    if images is not None:
        inputs["images"] = [
            {"id": i.id, "sha256": hashlib.sha256(i.data).hexdigest()} for i in images
        ]
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    cache = directory / "selection-cache"
    cache.mkdir(exist_ok=True)
    path = cache / f"{name}-{digest}.json"
    cached = json_object(path)
    if cached:
        try:
            result = schema.model_validate(cached)
            if validate:
                validate(result)
            return result
        except (ValueError, LLMValidationError):
            pass
    options = {"images": images, "model": model} if images is not None or model else {}
    result = client.call_json(name, variables, schema, directory / "llm_log.jsonl", **options)
    if validate:
        validate(result)
    atomic_json(path, result.model_dump())
    return result
