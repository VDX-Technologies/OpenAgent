"""
Core · Voice (speech-to-text)
=============================
Transcribes recorded audio on this Mac with faster-whisper, so voice input
never leaves the machine. The model is downloaded once on first use and kept
in memory afterwards.
"""

from __future__ import annotations

import io
import logging
import threading
from typing import Any

from config.settings import get_settings

logger = logging.getLogger(__name__)

_model: Any = None
_model_name = ""
_lock = threading.Lock()


class VoiceUnavailable(RuntimeError):
    """faster-whisper is not installed."""


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def _load() -> Any:
    global _model, _model_name
    name = get_settings().voice.whisper_model or "small"
    if _model is None or _model_name != name:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise VoiceUnavailable("Voice input needs faster-whisper: .venv/bin/pip install faster-whisper") from exc
        logger.info("Loading Whisper model %s", name)
        _model, _model_name = WhisperModel(name, device="cpu", compute_type="int8"), name
    return _model


def transcribe(audio: bytes, language: str | None = None) -> dict[str, Any]:
    """Return ``{"text", "language"}`` for an audio clip (webm/ogg/mp4/wav…)."""
    with _lock:  # one transcription at a time; the model isn't shared across threads
        model = _load()
        segments, info = model.transcribe(io.BytesIO(audio), language=language or None, vad_filter=True, beam_size=1)
        text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "language": info.language}
