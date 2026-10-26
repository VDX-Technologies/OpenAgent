"""
Core · LLM Client (Ollama)
==========================
Thin wrapper around the local Ollama HTTP API
(http://localhost:11434) for chat completions with
streaming support, using the qwen2.5:7b model by default.
"""

from __future__ import annotations

import json
import logging
from contextlib import nullcontext
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)
_AUTO_CTX: int | None = None


def _with_usage(data: dict[str, Any]) -> dict[str, Any]:
    """Return the reply message with Ollama token/time stats under ``_usage``.

    Callers must ``pop("_usage")`` before sending the message back to Ollama.
    """
    msg = dict(data.get("message") or {})
    ms = lambda k: (data.get(k) or 0) // 1_000_000  # noqa: E731 — Ollama reports nanoseconds
    msg["_usage"] = {
        "prompt_tokens": data.get("prompt_eval_count") or 0,
        "completion_tokens": data.get("eval_count") or 0,
        "duration_ms": ms("total_duration"),
        "load_ms": ms("load_duration"),
        "prompt_ms": ms("prompt_eval_duration"),
        "eval_ms": ms("eval_duration"),
    }
    return msg


class OllamaClient:
    """Synchronous and streaming client for the Ollama chat API."""

    def __init__(self) -> None:
        """Initialise the client from application settings."""
        cfg = get_settings().ollama
        self.base_url = cfg.base_url.rstrip("/")
        self.model = cfg.model
        self.temperature = cfg.temperature
        self.timeout = cfg.timeout
        self._http: httpx.Client | None = None

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
        return {"temperature": temperature or self.temperature, "num_ctx": self.num_ctx}

    def _session(self) -> httpx.Client:
        """One pooled HTTP client for the sync calls (reconnecting per request costs time)."""
        if self._http is None or self._http.timeout.read != self.timeout:
            self._http = httpx.Client(timeout=self.timeout)
        return self._http

    # ── Health check ─────────────────────────────────────────────────

    def apply_config(
        self,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        timeout: int | None = None,
    ) -> None:
        """Hot-reload connection parameters without recreating the client."""
        if base_url is not None:
            self.base_url = base_url.rstrip("/")
        if model is not None:
            self.model = model
        if temperature is not None:
            self.temperature = temperature
        if timeout is not None:
            self.timeout = timeout

    def is_available(self) -> bool:
        """Return True if the Ollama server responds to /api/tags."""
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def list_models(self) -> list[str]:
        """Return names of models currently available on the Ollama server."""
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                models = resp.json().get("models", [])
                return [m.get("name", "") for m in models if m.get("name")]
        except httpx.HTTPError as exc:
            logger.warning("Could not list Ollama models: %s", exc)
            return []

    def list_models_detailed(self) -> list[dict[str, Any]]:
        """Return installed models with size, family, parameters and quantization."""
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
        except httpx.HTTPError:
            return []
        out = []
        for m in resp.json().get("models", []):
            d = m.get("details") or {}
            out.append({
                "name": m.get("name", ""),
                "size": m.get("size", 0),
                "modified_at": m.get("modified_at"),
                "family": d.get("family", ""),
                "parameter_size": d.get("parameter_size", ""),
                "quantization": d.get("quantization_level", ""),
            })
        return out

    def running_models(self) -> list[dict[str, Any]]:
        """Return models currently loaded in memory (Ollama /api/ps)."""
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/api/ps")
                resp.raise_for_status()
                return [
                    {"name": m.get("name"), "size_vram": m.get("size_vram", 0), "expires_at": m.get("expires_at")}
                    for m in resp.json().get("models", [])
                ]
        except httpx.HTTPError:
            return []

    def pull_model(self, name: str, on_progress: Any = None) -> None:
        """Download a model, calling ``on_progress(status, completed, total)`` per chunk.

        Raises:
            httpx.HTTPError / RuntimeError on failure.
        """
        with httpx.Client(timeout=None) as client:
            with client.stream("POST", f"{self.base_url}/api/pull", json={"model": name}) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise RuntimeError(chunk["error"])
                    if on_progress:
                        on_progress(chunk.get("status", ""), chunk.get("completed", 0), chunk.get("total", 0))

    def delete_model(self, name: str) -> None:
        """Remove an installed model from Ollama."""
        with httpx.Client(timeout=30) as client:
            resp = client.request("DELETE", f"{self.base_url}/api/delete", json={"model": name})
            resp.raise_for_status()

    # ── Non-streaming chat ───────────────────────────────────────────

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat request and return the full response message.

        Args:
            messages: Conversation history in OpenAI-compatible format.
            tools: Optional list of tool/function descriptors for
                   Ollama native function-calling.
            temperature: Override the default sampling temperature.
            model: Override the configured model for this call.

        Returns:
            The assistant message dict (may contain ``tool_calls``).
        """
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
            "options": self._options(temperature),
            "keep_alive": self.keep_alive,
        }
        if tools:
            payload["tools"] = tools

        try:
            with nullcontext(self._session()) as client:
                resp = client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return _with_usage(data)
        except httpx.TimeoutException:
            logger.error("Ollama request timed out after %ss", self.timeout)
            return {"role": "assistant", "content": "Error: LLM request timed out."}
        except httpx.HTTPError as exc:
            logger.error("Ollama HTTP error: %s", exc)
            return {"role": "assistant", "content": f"Error: Cannot reach Ollama — {exc}"}

    # ── Streaming chat ───────────────────────────────────────────────

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
    ) -> Iterator[str]:
        """Yield content tokens as they arrive from Ollama.

        Useful for updating the GUI balloon in real time.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": self._options(temperature),
            "keep_alive": self.keep_alive,
        }

        try:
            with nullcontext(self._session()) as client:
                with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            break
        except httpx.TimeoutException:
            logger.error("Ollama stream timed out")
            yield "Error: LLM request timed out."
        except httpx.HTTPError as exc:
            logger.error("Ollama stream error: %s", exc)
            yield f"Error: Cannot reach Ollama — {exc}"

    def chat_events(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> Iterator[tuple[str, Any]]:
        """Stream a chat call with tools.

        Yields ``("token", str)`` for each content chunk, then exactly one
        ``("message", dict)`` with the assembled reply (``tool_calls`` and
        ``_usage`` included, like :meth:`chat`).
        """
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": True,
            "options": self._options(),
            "keep_alive": self.keep_alive,
        }
        if tools:
            payload["tools"] = tools
        content, calls, last = "", [], {}
        try:
            with nullcontext(self._session()) as client:
                with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        last = json.loads(line)
                        msg = last.get("message") or {}
                        calls += msg.get("tool_calls") or []
                        if msg.get("content"):
                            content += msg["content"]
                            yield "token", msg["content"]
                        if last.get("done"):
                            break
        except httpx.TimeoutException:
            content = content or "Error: LLM request timed out."
        except httpx.HTTPError as exc:
            content = content or f"Error: Cannot reach Ollama — {exc}"
        reply = _with_usage({**last, "message": {"role": "assistant", "content": content}})
        if calls:
            reply["tool_calls"] = calls
        yield "message", reply

    # ── Async streaming (for Discord bot) ────────────────────────────

    async def achat_stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Async variant of :meth:`chat_stream` for Discord / asyncio contexts."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": self._options(temperature),
            "keep_alive": self.keep_alive,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            break
        except httpx.TimeoutException:
            logger.error("Ollama async stream timed out")
            yield "Error: LLM request timed out."
        except httpx.HTTPError as exc:
            logger.error("Ollama async stream error: %s", exc)
            yield f"Error: Cannot reach Ollama — {exc}"

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Async non-streaming chat — used by the Discord bot path."""
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
            "options": self._options(temperature),
            "keep_alive": self.keep_alive,
        }
        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return _with_usage(data)
        except httpx.TimeoutException:
            logger.error("Ollama async request timed out")
            return {"role": "assistant", "content": "Error: LLM request timed out."}
        except httpx.HTTPError as exc:
            logger.error("Ollama async HTTP error: %s", exc)
            return {"role": "assistant", "content": f"Error: Cannot reach Ollama — {exc}"}
