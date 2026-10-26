"""
Core · Anonymous telemetry sharing (opt-in)
===========================================
When the user allows it, per-request performance numbers are sent to VDX Core
(``POST /api/agent/telemetry``, no token) to learn how models behave on real Macs.

What is sent:
    * an install record: random install id, app version, Mac model, chip,
      CPU cores, RAM, macOS / Python / Ollama versions;
    * per request: model name/family/size/quantization, token counts, load /
      prompt / GPU (Ollama compute) / CPU (this process) times, tool count, ok.

What is never sent: prompts, replies, tool arguments, file names, account
names, hostnames, IP addresses (requests carry no identifying headers; Core
does not store the caller's address) or anything typed by the user.

Consent and the install id live in ``data/telemetry.json``. Nothing leaves the
machine until ``consent`` is ``True``.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from config.settings import project_root
from core.hardware import _sysctl, system_profile

logger = logging.getLogger(__name__)

APP_VERSION = "0.4.0"

# Public VDX Core ingest; it only accepts these anonymous numbers, so no token.
DEFAULT_URL = "https://dash.vdxtechnologies.com/api/agent/telemetry"

_STATE = project_root() / "data" / "telemetry.json"
_BATCH = 20
_FLUSH_S = 60


def _endpoint() -> str:
    return os.getenv("VDX_TELEMETRY_URL", DEFAULT_URL)


class TelemetryShare:
    """Consent store and batched, anonymous uploader."""

    def __init__(self, path: Path = _STATE) -> None:
        """Load (or create) the consent file and start the flush timer."""
        self._path = path
        self._lock = threading.Lock()
        self._queue: list[dict[str, Any]] = []
        self._install_sent = False
        self._state = self._load()
        self._timer: threading.Timer | None = None
        self._schedule()

    # ── Consent ──────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self._path.read_text())
        except (OSError, ValueError):
            return {"consent": None, "install_id": str(uuid.uuid4())}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._state))

    def status(self) -> dict[str, Any]:
        """Consent (``None`` = not asked yet), whether an endpoint is set, and queue size."""
        return {"consent": self._state.get("consent"), "configured": bool(_endpoint()),
                "install_id": self._state["install_id"], "pending": len(self._queue)}

    def set_consent(self, allow: bool) -> dict[str, Any]:
        """Record the user's choice; denying drops anything queued."""
        with self._lock:
            self._state["consent"] = bool(allow)
            self._state["decided_at"] = datetime.now(timezone.utc).isoformat()
            if not allow:
                self._queue.clear()
            self._save()
        return self.status()

    @property
    def enabled(self) -> bool:
        """True only with explicit consent and a configured endpoint."""
        return self._state.get("consent") is True and bool(_endpoint())

    # ── Payload ──────────────────────────────────────────────────────

    def install(self) -> dict[str, Any]:
        """The anonymous install record (hardware and versions only)."""
        p = system_profile()
        return {
            "app_version": APP_VERSION,
            "mac_model": _sysctl("hw.model") or platform.machine(),
            "chip": p.get("chip", ""),
            "cpu_cores": int(p.get("cpu_cores") or os.cpu_count() or 0),
            "ram_gb": p.get("ram_gb", 0),
            "macos": platform.mac_ver()[0] or platform.release(),
            "python": platform.python_version(),
            "ollama": self._ollama_version(),
        }

    def _ollama_version(self) -> str:
        from config.settings import get_settings
        try:
            r = httpx.get(f"{get_settings().ollama.base_url.rstrip('/')}/api/version", timeout=3)
            return r.json().get("version", "")
        except (httpx.HTTPError, ValueError):
            return ""

    def record(self, summary: dict[str, Any], model: str, ok: bool, cpu_ms: int,
               models: list[dict[str, Any]], running: list[dict[str, Any]]) -> None:
        """Queue one request's numbers (no-op without consent)."""
        if not self.enabled:
            return
        info = next((m for m in models if m.get("name") == model), {})
        vram = next((m.get("size_vram", 0) for m in running if m.get("name") == model), 0)
        eval_ms = int(summary.get("eval_ms") or 0)
        gen = int(summary.get("completion_tokens") or 0)
        turn = {
            "model": model, "family": info.get("family", ""), "parameter_size": info.get("parameter_size", ""),
            "quantization": info.get("quantization", ""), "model_bytes": int(info.get("size") or 0),
            "vram_bytes": int(vram or 0),
            "prompt_tokens": int(summary.get("prompt_tokens") or 0), "completion_tokens": gen,
            "duration_ms": int(summary.get("total_ms") or 0), "load_ms": int(summary.get("load_ms") or 0),
            "prompt_ms": int(summary.get("prompt_ms") or 0),
            # Ollama runs the model on the GPU (Metal): prefill + decode is GPU time
            "gpu_ms": int(summary.get("prompt_ms") or 0) + eval_ms,
            "cpu_ms": max(0, cpu_ms),
            "tokens_per_s": round(gen / (eval_ms / 1000), 2) if eval_ms > 0 else 0,
            "tools": int(summary.get("tool_calls") or 0), "ok": ok,
        }
        with self._lock:
            self._queue.append({"ts": datetime.now(timezone.utc).isoformat(), "payload": turn})
            full = len(self._queue) >= _BATCH
        if full:
            threading.Thread(target=self.flush, daemon=True).start()

    # ── Upload ───────────────────────────────────────────────────────

    def _schedule(self) -> None:
        self._timer = threading.Timer(_FLUSH_S, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self) -> None:
        try:
            self.flush()
        finally:
            self._schedule()

    def flush(self) -> None:
        """Send queued turns (and the install record once per run); keep them on failure."""
        if not self.enabled:
            return
        with self._lock:
            batch, self._queue = self._queue, []
        if not batch and self._install_sent:
            return
        # the install record goes with every batch: the server upserts it before the turns
        body = {"install": {"id": self._state["install_id"], **self.install()},
                "turns": [{"ts": e["ts"], **e["payload"]} for e in batch]}
        try:
            r = httpx.post(_endpoint(), json=body, timeout=10, headers={"User-Agent": "vdx-agent"})
            r.raise_for_status()
            self._install_sent = True
        except httpx.HTTPError as exc:
            logger.info("Telemetry upload deferred: %s", exc)
            with self._lock:
                self._queue = (batch + self._queue)[-500:]

    def stop(self) -> None:
        """Cancel the timer and try a last flush."""
        if self._timer:
            self._timer.cancel()
        self.flush()
