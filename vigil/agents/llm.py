"""Local LLM/VLM access via Ollama. Nothing leaves the machine.

Text reasoning + tool calling: VIGIL_LLM_MODEL (default qwen3.8, already
resident for the FRS AI operator). Vision: VIGIL_VLM_MODEL (qwen3-vl:8b).
Each is serialised behind a semaphore: the GPU is shared with perception.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from typing import Any

import httpx

from vigil.config import get_settings

log = logging.getLogger("vigil.llm")


class LLMError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self) -> None:
        s = get_settings()
        self.url = s.ollama_url.rstrip("/")
        self.text_model, self.vision_model = s.llm_model, s.vlm_model
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(s.llm_timeout_s, connect=5.0))
        self.text_sem = asyncio.Semaphore(1)
        self.vision_sem = asyncio.Semaphore(1)
        self.stats = {"text_calls": 0, "vision_calls": 0, "errors": 0, "text_s": 0.0, "vision_s": 0.0}

    async def close(self) -> None:
        await self._http.aclose()

    async def health(self) -> dict:
        try:
            r = await self._http.get(f"{self.url}/api/tags", timeout=5)
            names = {m["name"] for m in r.json().get("models", [])}
            return {"reachable": True, "text_model": self.text_model, "text_available": self.text_model in names,
                    "vision_model": self.vision_model, "vision_available": self.vision_model in names}
        except Exception as e:  # noqa: BLE001
            return {"reachable": False, "error": str(e)}

    async def chat(self, messages: list[dict], tools: list[dict] | None = None, fmt: Any = None,
                   model: str | None = None, temperature: float = 0.2, think: bool = False) -> dict:
        body: dict = {"model": model or self.text_model, "messages": messages, "stream": False,
                      "think": think, "options": {"temperature": temperature, "num_ctx": 16384}}
        if tools:
            body["tools"] = tools
        if fmt is not None:
            body["format"] = fmt
        async with self.text_sem:
            t = time.perf_counter()
            try:
                r = await self._http.post(f"{self.url}/api/chat", json=body)
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001
                self.stats["errors"] += 1
                raise LLMError(f"LLM call failed: {e}") from e
            finally:
                self.stats["text_calls"] += 1
                self.stats["text_s"] += time.perf_counter() - t
        return r.json()["message"]

    async def vision(self, prompt: str, images: list[bytes], schema: dict, system: str | None = None) -> dict:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt, "images": [base64.b64encode(b).decode() for b in images]})
        body = {"model": self.vision_model, "messages": msgs, "stream": False, "format": schema,
                "options": {"temperature": 0.1, "num_ctx": 8192}}
        async with self.vision_sem:
            t = time.perf_counter()
            try:
                r = await self._http.post(f"{self.url}/api/chat", json=body)
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001
                self.stats["errors"] += 1
                raise LLMError(f"VLM call failed: {e}") from e
            finally:
                self.stats["vision_calls"] += 1
                self.stats["vision_s"] += time.perf_counter() - t
        return parse_json(r.json()["message"]["content"])


def parse_json(text: str) -> dict:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {"raw": text}


_client: OllamaClient | None = None


def llm() -> OllamaClient:
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client
