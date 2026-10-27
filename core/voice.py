"""
Core · Voice (speech-to-text)
=============================
Transcribes audio on this Mac with faster-whisper, so voice input never
leaves the machine. The model is downloaded once on first use and kept in
memory afterwards.

The app records the microphone itself (``start_recording`` /
``stop_recording``, via sounddevice): the app window (WKWebView in
pywebview) can't be granted microphone access, and recording natively only
needs the macOS microphone permission of the app.
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


SAMPLE_RATE = 16_000  # what Whisper expects
MAX_SECONDS = 300
_rec: dict[str, Any] = {"stream": None, "chunks": []}


def can_record() -> bool:
    """Whether the Mac's microphone can be recorded natively (sounddevice + PortAudio)."""
    try:
        import sounddevice  # noqa: F401  — raises OSError when PortAudio is missing
    except (ImportError, OSError):
        return False
    return True


def start_recording() -> None:
    """Start recording the default microphone."""
    import sounddevice as sd

    stop_recording(discard=True)
    chunks: list[Any] = []
    limit = SAMPLE_RATE * MAX_SECONDS

    def on_audio(data: Any, frames: int, _time: Any, _status: Any) -> None:
        if sum(len(c) for c in chunks) < limit:
            chunks.append(data[:, 0].copy())

    try:
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=on_audio)
        stream.start()
    except Exception as exc:
        raise RuntimeError(f"Could not open the microphone: {exc}") from exc
    _rec.update(stream=stream, chunks=chunks)


def stop_recording(discard: bool = False) -> Any:
    """Stop recording; returns the audio (float32 numpy array at 16 kHz) or None."""
    stream, chunks = _rec["stream"], _rec["chunks"]
    _rec.update(stream=None, chunks=[])
    if stream is None:
        return None
    stream.stop()
    stream.close()
    if discard or not chunks:
        return None
    import numpy as np

    return np.concatenate(chunks)


def transcribe_recording() -> dict[str, Any]:
    """Stop the recording and transcribe it."""
    audio = stop_recording()
    if audio is None or len(audio) < SAMPLE_RATE // 4:
        return {"text": "", "language": ""}
    if float(abs(audio).max()) == 0.0:
        # macOS hands a blocked app silence instead of an error
        raise PermissionError(
            "The microphone is blocked: open System Settings → Privacy & Security → Microphone "
            "and turn on VDX OpenAgent (or Terminal, if you started it from there), then reopen the app."
        )
    return transcribe(audio)


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


def transcribe(audio: Any, language: str | None = None) -> dict[str, Any]:
    """Return ``{"text", "language"}`` for an audio clip (webm/ogg/mp4/wav bytes, or 16 kHz samples)."""
    with _lock:  # one transcription at a time; the model isn't shared across threads
        model = _load()
        source = io.BytesIO(audio) if isinstance(audio, (bytes, bytearray)) else audio
        segments, info = model.transcribe(source, language=language or None, vad_filter=True, beam_size=1)
        text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "language": info.language}
