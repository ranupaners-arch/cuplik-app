import base64
import json
import time
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import TypeVar

import httpx
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ValidationError

from api.app.config import ROOT, get_settings
from api.app.schemas import Candidate, ChapterPlan, OutlinePlan, Ranking, Rubric, Selection

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMImage:
    id: str
    data: bytes

    def encoded(self):
        return base64.b64encode(self.data).decode("ascii")


class LLMError(RuntimeError):
    pass


class LLMValidationError(LLMError):
    """Bad structured output may skip one window; transport/config failures must surface."""


def render_messages(name: str, variables: dict) -> tuple[str, str]:
    root = ROOT / "worker/prompts"
    if (root / f"{name}.system.txt").exists():
        env = Environment(loader=FileSystemLoader(root), undefined=StrictUndefined, autoescape=True)
        system = env.get_template(f"{name}.system.txt").render(**variables)
        # Escaping prevents transcript text from closing data tags or forging a clip.
        user = env.get_template(f"{name}.user.txt").render(**variables)
        return system, user
    return (root / f"{name}.txt").read_text(), "<transcript>\n" + json.dumps(
        variables, ensure_ascii=False
    ) + "\n</transcript>"


class LLMClient:
    def __init__(self, *, transport: httpx.BaseTransport | None = None):
        self.settings = get_settings()
        self.transport = transport
        self.usage: list[dict] = []

    def call_json(
        self,
        name: str,
        variables: dict,
        schema: type[T],
        log_path: Path | None = None,
        *,
        images: list[LLMImage] | None = None,
        model: str | None = None,
    ) -> T:
        if images and (len(images) > 16 or sum(len(i.data) for i in images) > 12 * 1024**2):
            raise LLMError("Batch vision melebihi batas 16 gambar atau 12 MiB.")
        if self.settings.llm_provider == "mock":
            result = schema.model_validate(self._mock(name, variables))
            record = {
                "prompt": name,
                "provider": "mock",
                "model": "deterministic-fixture",
                "input_tokens": 0,
                "output_tokens": 0,
                "images": len(images or []),
            }
            self._record(record, log_path)
            return result
        model = model or self.settings.llm_model_fast
        if not model:
            raise LLMError(
                "Isi LLM_MODEL_FAST di .env dengan model yang tersedia pada provider Anda."
            )
        system, user = render_messages(name, variables)
        for attempt in range(2):
            content, usage = self._request(
                system, user, schema.model_json_schema(), images=images, model=model
            )
            self._record(
                {
                    "prompt": name,
                    "provider": self.settings.llm_provider,
                    "model": model,
                    "repair": bool(attempt),
                    "images": len(images or []),
                    **usage,
                },
                log_path,
            )
            try:
                return schema.model_validate_json(content)
            except (ValidationError, ValueError) as exc:
                if attempt:
                    raise LLMValidationError(
                        "Provider mengembalikan JSON tidak valid setelah satu percobaan perbaikan."
                    ) from exc
                user += (
                    "\nYour previous response failed schema validation. Return corrected JSON only.\n<previous_response>"
                    + escape(content[:30000])
                    + "</previous_response>"
                    + "\n<validation_error>"
                    + escape(str(exc)[:4000])
                    + "</validation_error>"
                )
        raise AssertionError("unreachable")

    def _record(self, record: dict, path: Path | None):
        self.usage.append(record)
        if path:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")

    def _request(
        self,
        system: str,
        user: str,
        schema: dict,
        *,
        images: list[LLMImage] | None = None,
        model: str | None = None,
    ) -> tuple[str, dict]:
        settings = self.settings
        provider = settings.llm_provider
        model = model or settings.llm_model_fast
        headers = {}
        if provider == "gemini":
            if not settings.gemini_api_key:
                raise LLMError("GEMINI_API_KEY belum diisi pada server.")
            # Keep keys in headers, never in URLs/logs.
            headers = {"x-goog-api-key": settings.gemini_api_key}
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            payload = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": schema,
                },
            }
            for item in images or []:
                payload["contents"][0]["parts"].extend(
                    [
                        {"text": f"Frame {item.id}:"},
                        {"inlineData": {"mimeType": "image/jpeg", "data": item.encoded()}},
                    ]
                )
        elif provider == "anthropic":
            if not settings.anthropic_api_key:
                raise LLMError("ANTHROPIC_API_KEY belum diisi pada server.")
            headers = {"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01"}
            url = "https://api.anthropic.com/v1/messages"
            payload = {
                "model": model,
                "max_tokens": 8192,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "tools": [
                    {
                        "name": "structured_result",
                        "description": "Return the structured result",
                        "input_schema": schema,
                    }
                ],
                "tool_choice": {"type": "tool", "name": "structured_result"},
            }
            if images:
                blocks = []
                for item in images:
                    blocks.extend(
                        [
                            {"type": "text", "text": f"Frame {item.id}:"},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": item.encoded(),
                                },
                            },
                        ]
                    )
                payload["messages"][0]["content"] = [*blocks, {"type": "text", "text": user}]
        else:
            url = settings.ollama_base_url.rstrip("/") + "/api/chat"
            payload = {
                "model": model,
                "stream": False,
                "format": schema,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "options": {"temperature": 0.2, "num_ctx": settings.ollama_num_ctx},
            }
            if images:
                payload["messages"][1]["images"] = [item.encoded() for item in images]
        try:
            with httpx.Client(
                transport=self.transport, timeout=settings.llm_timeout_seconds
            ) as client:
                for attempt in range(3):
                    try:
                        response = client.post(url, headers=headers, json=payload)
                    except httpx.TransportError:
                        if attempt == 2:
                            raise
                        time.sleep(2**attempt)
                        continue
                    if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                        time.sleep(2**attempt)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    break
            if provider == "gemini":
                content = "".join(
                    p.get("text", "")
                    for p in data["candidates"][0]["content"]["parts"]
                    if not p.get("thought")
                )
                usage = data.get("usageMetadata", {})
                return content, {
                    "input_tokens": usage.get("promptTokenCount", 0),
                    "output_tokens": usage.get("candidatesTokenCount", 0),
                }
            if provider == "anthropic":
                tool = next(
                    c
                    for c in data["content"]
                    if c["type"] == "tool_use" and c["name"] == "structured_result"
                )
                return json.dumps(tool["input"]), data.get("usage", {})
            return data["message"]["content"], {
                "input_tokens": data.get("prompt_eval_count", 0),
                "output_tokens": data.get("eval_count", 0),
            }
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"LLM {provider} menolak permintaan (HTTP {exc.response.status_code}). Periksa key, model, dan kuota."
            ) from exc
        except (httpx.TransportError, KeyError, ValueError, StopIteration) as exc:
            raise LLMError(
                f"Koneksi atau respons LLM {provider} tidak dapat digunakan. Periksa layanan dan konfigurasi."
            ) from exc

    @staticmethod
    def _mock(name: str, variables: dict) -> dict:
        sentences = variables.get("sentences", [])
        if name == "frame_describer":
            return {
                "frames": [
                    {
                        "id": f["id"],
                        "action": "Fixture vision: isi gambar belum dinilai model nyata.",
                        "uncertain": True,
                    }
                    for f in variables["frames"]
                ]
            }
        if name == "beat_annotator":
            return {
                "beats": [
                    {
                        "id": b["id"],
                        "label": "manual" if b["kind"] == "visual" else "step",
                        "step_hint": "Langkah fixture",
                        "specs": [],
                        "uncertain": True,
                    }
                    for b in variables["beats"]
                ]
            }
        if name == "outline_builder":
            beats = variables["beats"]
            return {
                "chapters": [
                    {
                        "title": f"Langkah fixture {i // 3 + 1}",
                        "goal": "Tinjau bukti sumber; outline mock tidak menilai gambar.",
                        "start_id": beats[i]["id"],
                        "end_id": beats[min(i + 2, len(beats) - 1)]["id"],
                        "required_beat_ids": [beats[i]["id"]],
                        "importance": "core",
                    }
                    for i in range(0, len(beats), 3)
                ]
            }
        if name == "moment_finder":
            sentences = variables["sentence_data"]
            candidates = []
            i = 0
            while i < len(sentences):
                end = i
                while (
                    end + 1 < len(sentences)
                    and end < i + 2
                    and sentences[end + 1]["end"] - sentences[i]["start"]
                    <= variables["max_seconds"]
                ):
                    end += 1
                while (
                    end + 1 < len(sentences)
                    and sentences[end]["end"] - sentences[i]["start"] < variables["min_seconds"]
                ):
                    end += 1
                duration = sentences[end]["end"] - sentences[i]["start"]
                if variables["min_seconds"] <= duration <= variables["max_seconds"]:
                    candidates.append(
                        {
                            "start_id": sentences[i]["id"],
                            "end_id": sentences[end]["id"],
                            "hook_sentence_id": sentences[i]["id"],
                            "cold_open_id": None,
                            "angle": "Fixture deterministik untuk uji alur; bukan rekomendasi editorial.",
                        }
                    )
                i = end + 1
                if len(candidates) >= variables["max_candidates"]:
                    break
            return {"candidates": candidates}
        if name == "scorer":
            clips = []
            for c in variables["candidates"]:
                index = int(c["id"][1:])
                words = c["raw_text"].split()
                title = " ".join(words[:7])[:60]
                clips.append(
                    {
                        "id": c["id"],
                        "scores": {
                            "hook": max(0, 8.5 - index * 0.02),
                            "standalone": 8,
                            "payoff": 8,
                            "emotion": 6,
                            "density": 8,
                        },
                        "topic": f"contoh {((index - 1) // 3) + 1}",
                        "titles": [title, f"Apa pelajaran bagian {index}?"],
                        "hook_texts": [" ".join(words[:6]), f"Sudah tahu langkah {index} ini?"],
                        "reason": "Fixture: hook terkuat dan emosi terlemah; bukan skor AI nyata.",
                        "keywords": list(dict.fromkeys(words))[:3],
                        "emphasis_word_ids": [],
                        "emoji": [],
                        "description": "Contoh alur pengemasan. Apa yang Anda pelajari?",
                        "hashtags": ["#contoh", "#cuplik", "#belajar"],
                        "trim_start_id": None,
                        "trim_end_id": None,
                    }
                )
            return {"clips": clips}
        if name == "reranker":
            return {
                "ranking": [
                    {
                        "id": c["id"],
                        "note": "Urutan fixture menurut skor dasar, bukan penilaian LLM nyata.",
                    }
                    for c in sorted(
                        variables["finalists"], key=lambda c: c["base_score"], reverse=True
                    )
                ]
            }
        if name == "rank":
            return Ranking(
                ids=sorted(
                    range(len(variables["candidates"])),
                    key=lambda i: variables["candidates"][i]["score"],
                    reverse=True,
                )
            ).model_dump()
        if name == "outline":
            return OutlinePlan(
                chapters=[
                    ChapterPlan(
                        title=f"Langkah {i // 3 + 1}",
                        goal=sentences[i]["text"],
                        start_id=sentences[i]["id"],
                        end_id=sentences[min(i + 2, len(sentences) - 1)]["id"],
                        required_sentence_ids=[sentences[i]["id"]],
                        importance="core",
                    )
                    for i in range(0, len(sentences), 3)
                ]
            ).model_dump()
        if name != "select":
            raise LLMError(f"Prompt mock tidak dikenal: {name}")
        candidates = []
        for i in range(0, len(sentences), 3):
            end = min(i + 2, len(sentences) - 1)
            while (
                end > i
                and sentences[end]["end"] - sentences[i]["start"] > variables["max_clip_seconds"]
            ):
                end -= 1
            if sentences[end]["end"] - sentences[i]["start"] > variables["max_clip_seconds"]:
                continue
            index = len(candidates)
            text = sentences[i]["text"]
            candidates.append(
                Candidate(
                    start_id=sentences[i]["id"],
                    end_id=sentences[end]["id"],
                    titles=[text[:60], f"Apa pelajaran dari bagian {index + 1}?"],
                    hook_options=[text[:65], f"Perhatikan langkah {index + 1} ini"],
                    topic=f"topik-{index + 1}",
                    scores=Rubric(
                        hook=8.5 - index * 0.2, standalone=8, payoff=8, emotion=6, density=8
                    ),
                    reason="Contoh deterministik untuk menguji workflow; bukan penilaian AI nyata.",
                )
            )
            if len(candidates) >= variables["requested_count"]:
                break
        return Selection(candidates=candidates).model_dump()
