"""Minimal client for a local Ollama server. No cloud fallback exists by design."""
from __future__ import annotations

import json
from collections.abc import Iterator

import httpx

from app.core.config import get_settings


class LLMUnavailable(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str | None = None, timeout: int | None = None):
        s = get_settings()
        self.base_url = (base_url or s.ollama_base_url).rstrip("/")
        self.timeout = timeout or s.ollama_timeout_seconds

    def list_models(self) -> list[dict]:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            r.raise_for_status()
            return r.json().get("models", [])
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"Ollama is not reachable at {self.base_url}: {e}") from e

    def status(self, model: str) -> dict:
        try:
            models = self.list_models()
        except LLMUnavailable as e:
            return {"reachable": False, "model": model, "model_available": False, "error": str(e),
                    "hint": "Install Ollama from https://ollama.com and run `ollama serve`."}
        names = {m.get("name") for m in models} | {m.get("model") for m in models}
        available = model in names or f"{model}:latest" in names
        return {
            "reachable": True, "model": model, "model_available": available,
            "installed_models": sorted(n for n in names if n),
            "hint": None if available else f"Run `ollama pull {model}` (or choose an installed model in Settings).",
        }

    def _payload(self, model: str, messages: list[dict], temperature: float, num_ctx: int, stream: bool, fmt: str | None):
        p = {"model": model, "messages": messages, "stream": stream,
             "options": {"temperature": temperature, "num_ctx": num_ctx}}
        if fmt:
            p["format"] = fmt
        return p

    def chat(self, model: str, messages: list[dict], temperature: float = 0.1, num_ctx: int = 8192,
             fmt: str | None = None) -> str:
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=self._payload(model, messages, temperature, num_ctx, False, fmt),
                           timeout=self.timeout)
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"Ollama request failed: {e}") from e
        if r.status_code == 404:
            raise LLMUnavailable(f"Model '{model}' is not installed in Ollama. Run `ollama pull {model}`.")
        if r.status_code >= 400:
            raise LLMUnavailable(f"Ollama error {r.status_code}: {r.text[:300]}")
        return r.json().get("message", {}).get("content", "")

    def chat_stream(self, model: str, messages: list[dict], temperature: float = 0.1, num_ctx: int = 8192) -> Iterator[str]:
        try:
            with httpx.stream("POST", f"{self.base_url}/api/chat",
                              json=self._payload(model, messages, temperature, num_ctx, True, None),
                              timeout=self.timeout) as r:
                if r.status_code == 404:
                    raise LLMUnavailable(f"Model '{model}' is not installed in Ollama. Run `ollama pull {model}`.")
                if r.status_code >= 400:
                    r.read()
                    raise LLMUnavailable(f"Ollama error {r.status_code}: {r.text[:300]}")
                for line in r.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise LLMUnavailable(f"Ollama error: {data['error']}")
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"Ollama request failed: {e}") from e


def get_llm() -> OllamaClient:
    return OllamaClient()
