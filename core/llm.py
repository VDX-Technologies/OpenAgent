"""
Core · LLM Client (Ollama)
==========================
Thin wrapper around the local Ollama HTTP API (http://localhost:11434):
streaming chat with tools and reasoning, model management, warm-up and
embeddings. Failures raise :class:`LLMError` with Ollama's own message, so
callers can tell "model not installed" from "Ollama is not running".
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator
from typing import Any

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)
_AUTO_CTX: int | None = None


class LLMError(RuntimeError):
    """A chat request failed (Ollama unreachable, model missing, error mid-stream…)."""


def _usage(data: dict[str, Any]) -> dict[str, Any]:
    """Ollama token/time stats of a finished request (it reports nanoseconds)."""
    ms = lambda k: (data.get(k) or 0) // 1_000_000  # noqa: E731
    return {
        "prompt_tokens": data.get("prompt_eval_count") or 0,
        "completion_tokens": data.get("eval_count") or 0,
        "duration_ms": ms("total_duration"),
        "load_ms": ms("load_duration"),
        "prompt_ms": ms("prompt_eval_duration"),
        "eval_ms": ms("eval_duration"),
    }


def _error_text(resp: httpx.Response) -> str:
    try:
        resp.read()
        return str(resp.json().get("error") or resp.text)[:300]
    except Exception:
        return f"HTTP {resp.status_code}"


class OllamaClient:
    """Client for the Ollama chat API."""

    def __init__(self) -> None:
        cfg = get_settings().ollama
        self.base_url = cfg.base_url.rstrip("/")
        self.model = cfg.model
        self.temperature = cfg.temperature
        self.timeout = cfg.timeout
        self._http: httpx.Client | None = None
        self._caps: dict[str, list[str]] = {}

    @property
    def keep_alive(self) -> str:
        return get_settings().ollama.keep_alive or "30m"

    @property
    def num_ctx(self) -> int:
        """Context window sent to Ollama: the setting, or 16K tokens on 32 GB+ Macs and 8K below."""
        if (n := get_settings().ollama.num_ctx) > 0:
            return n
        global _AUTO_CTX
        if _AUTO_CTX is None:
            try:
                from core.hardware import _ram_bytes
                _AUTO_CTX = 16384 if _ram_bytes() >= 32 * 1024**3 else 8192
            except Exception:
                _AUTO_CTX = 8192
        return _AUTO_CTX

    def _options(self, temperature: float | None = None) -> dict[str, Any]:
        return {"temperature": self.temperature if temperature is None else temperature, "num_ctx": self.num_ctx}

    def _session(self) -> httpx.Client:
        """One pooled HTTP client (reconnecting per request costs time).

        The timeout is per read, so a long streamed answer never times out while tokens keep coming.
        """
        if self._http is None or self._http.timeout.read != self.timeout:
            self._http = httpx.Client(timeout=httpx.Timeout(self.timeout, connect=5))
        return self._http

    def apply_config(self, base_url: str | None = None, model: str | None = None,
                     temperature: float | None = None, timeout: int | None = None) -> None:
        """Hot-reload connection parameters without recreating the client."""
        if base_url is not None:
            self.base_url = base_url.rstrip("/")
            self._caps.clear()
        if model is not None:
            self.model = model
        if temperature is not None:
            self.temperature = temperature
        if timeout is not None:
            self.timeout = timeout

    # ── Server / models ──────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True if the Ollama server answers."""
        try:
            return self._session().get(f"{self.base_url}/api/version", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def _tags(self) -> list[dict[str, Any]]:
        resp = self._session().get(f"{self.base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        return resp.json().get("models", [])

    def list_models(self) -> list[str]:
        """Names of the models installed on the Ollama server (chat models only)."""
        try:
            return [m["name"] for m in self._tags() if m.get("name") and "bert" not in (m.get("details") or {}).get("family", "")]
        except httpx.HTTPError as exc:
            logger.warning("Could not list Ollama models: %s", exc)
            return []

    def list_models_detailed(self) -> list[dict[str, Any]]:
        """Installed models with size, family, parameters and quantization."""
        try:
            tags = self._tags()
        except httpx.HTTPError:
            return []
        out = []
        for m in tags:
            d = m.get("details") or {}
            out.append({
                "name": m.get("name", ""), "size": m.get("size", 0), "modified_at": m.get("modified_at"),
                "family": d.get("family", ""), "parameter_size": d.get("parameter_size", ""),
                "quantization": d.get("quantization_level", ""),
            })
        return out

    def running_models(self) -> list[dict[str, Any]]:
        """Models currently loaded in memory (Ollama /api/ps)."""
        try:
            resp = self._session().get(f"{self.base_url}/api/ps", timeout=5)
            resp.raise_for_status()
            return [
                {"name": m.get("name"), "size_vram": m.get("size_vram", 0), "expires_at": m.get("expires_at")}
                for m in resp.json().get("models", [])
            ]
        except httpx.HTTPError:
            return []

    def capabilities(self, model: str | None = None) -> list[str]:
        """What a model can do (``tools``, ``thinking``, ``vision``, ``embedding``…), cached."""
        name = model or self.model
        if name not in self._caps:
            try:
                resp = self._session().post(f"{self.base_url}/api/show", json={"model": name}, timeout=10)
                resp.raise_for_status()
                self._caps[name] = list(resp.json().get("capabilities") or [])
            except (httpx.HTTPError, ValueError):
                return []
        return self._caps[name]

    def warm(self, model: str | None = None) -> None:
        """Load a model into memory in the background, so the first message doesn't wait for it."""
        name = model or self.model

        def run() -> None:
            try:
                self._session().post(f"{self.base_url}/api/generate",
                                     json={"model": name, "keep_alive": self.keep_alive}, timeout=300)
                self.capabilities(name)
                logger.info("Model %s loaded", name)
            except httpx.HTTPError as exc:
                logger.info("Could not preload %s: %s", name, exc)

        threading.Thread(target=run, name="ollama-warm", daemon=True).start()

    def pull_model(self, name: str, on_progress: Any = None) -> None:
        """Download a model, calling ``on_progress(status, completed, total)`` per chunk."""
        with httpx.Client(timeout=None) as client:
            with client.stream("POST", f"{self.base_url}/api/pull", json={"model": name}) as resp:
                if resp.status_code >= 400:
                    raise RuntimeError(_error_text(resp))
                for line in resp.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise RuntimeError(chunk["error"])
                    if on_progress:
                        on_progress(chunk.get("status", ""), chunk.get("completed", 0), chunk.get("total", 0))
        self._caps.pop(name, None)

    def delete_model(self, name: str) -> None:
        """Remove an installed model from Ollama."""
        resp = self._session().request("DELETE", f"{self.base_url}/api/delete", json={"model": name}, timeout=30)
        resp.raise_for_status()

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Embedding vectors for *texts* (raises LLMError when the model is missing)."""
        name = model or get_settings().ollama.embed_model
        try:
            resp = self._session().post(f"{self.base_url}/api/embed",
                                        json={"model": name, "input": texts, "keep_alive": self.keep_alive}, timeout=120)
        except httpx.HTTPError as exc:
            raise LLMError(f"Cannot reach Ollama at {self.base_url} — is it running?") from exc
        if resp.status_code >= 400:
            raise LLMError(f"Embedding model '{name}': {_error_text(resp)}")
        return resp.json().get("embeddings") or []

    # ── Chat ─────────────────────────────────────────────────────────

    def _think_flag(self, model: str, think: bool | None) -> bool | None:
        """``think`` for Ollama: only sent to models that support reasoning."""
        if "thinking" not in self.capabilities(model):
            return None
        if think is not None:
            return think
        return get_settings().ollama.think.lower() in ("on", "1", "true", "yes")

    def chat_events(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        think: bool | None = None,
        temperature: float | None = None,
    ) -> Iterator[tuple[str, Any]]:
        """Stream a chat call.

        Yields ``("thinking", str)`` and ``("token", str)`` chunks, then exactly one
        ``("message", dict)`` with the assembled reply (``tool_calls``, ``thinking`` and
        ``_usage`` included). Raises :class:`LLMError` on any failure. Closing the
        generator early closes the connection, which makes Ollama stop generating.
        """
        name = model or self.model
        payload: dict[str, Any] = {
            "model": name, "messages": messages, "stream": True,
            "options": self._options(temperature), "keep_alive": self.keep_alive,
        }
        if tools:
            payload["tools"] = tools
        if (flag := self._think_flag(name, think)) is not None:
            payload["think"] = flag
        content, thinking, calls, last = "", "", [], {}
        try:
            with self._session().stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                if resp.status_code >= 400:
                    raise LLMError(f"Ollama ({name}): {_error_text(resp)}")
                for line in resp.iter_lines():
                    if not line:
                        continue
                    last = json.loads(line)
                    if last.get("error"):
                        raise LLMError(f"Ollama ({name}): {last['error']}")
                    msg = last.get("message") or {}
                    calls += msg.get("tool_calls") or []
                    if msg.get("thinking"):
                        thinking += msg["thinking"]
                        yield "thinking", msg["thinking"]
                    if msg.get("content"):
                        content += msg["content"]
                        yield "token", msg["content"]
                    if last.get("done"):
                        break
        except httpx.TimeoutException as exc:
            raise LLMError(f"Ollama did not answer within {self.timeout}s (Settings → Timeout).") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Cannot reach Ollama at {self.base_url} — is it running?") from exc
        except json.JSONDecodeError as exc:
            raise LLMError("Ollama sent an unreadable reply.") from exc
        reply: dict[str, Any] = {"role": "assistant", "content": content, "_usage": _usage(last)}
        if thinking:
            reply["thinking"] = thinking
        if calls:
            reply["tool_calls"] = calls
        yield "message", reply

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             temperature: float | None = None, model: str | None = None) -> dict[str, Any]:
        """Run a chat call to completion and return the reply message (see :meth:`chat_events`)."""
        reply: dict[str, Any] = {}
        for kind, val in self.chat_events(messages, tools=tools, model=model, temperature=temperature):
            if kind == "message":
                reply = val
        return reply
