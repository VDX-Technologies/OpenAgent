"""
Core · Voice (speech-to-text and text-to-speech)
================================================
Speech-to-text runs on this Mac with faster-whisper; voice never leaves the
machine. The app records the microphone itself (sounddevice): the app window
(WKWebView) can't be granted microphone access.

Fast recognition:

* the Whisper model starts loading the moment recording starts, while the user
  is still talking, and stays in memory afterwards;
* speech is transcribed *while* the user talks: a worker cuts the recording at
  pauses and transcribes each phrase in the background, so pressing stop only
  leaves the last phrase to do (and the UI shows the text live);
* the language found in the first phrase is reused for the next ones (no
  re-detection), greedy decoding, no timestamps, threads = performance cores.

The same pause detection tells hands-free conversation mode when the user has
finished speaking. Text-to-speech uses macOS's built-in ``say`` voices.
"""

from __future__ import annotations

import io
import logging
import os
import re
import subprocess
import threading
import time
from typing import Any

from config.settings import get_settings

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000  # what Whisper expects
FRAME = SAMPLE_RATE // 10  # 100 ms analysis frames
MAX_SECONDS = 300
PAUSE_CUT = 0.5  # silence (s) after which a phrase is transcribed in the background
END_SILENCE = 1.5  # silence (s) after speech that counts as "finished talking" (hands-free mode)
MAX_SEGMENT = 25  # seconds; longer phrases are cut at their quietest point

_model: Any = None
_model_name = ""
_lock = threading.Lock()  # one transcription at a time; the model isn't shared across threads
_load_lock = threading.Lock()


class VoiceUnavailable(RuntimeError):
    """faster-whisper is not installed."""


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def can_record() -> bool:
    """Whether the Mac's microphone can be recorded natively (sounddevice + PortAudio)."""
    try:
        import sounddevice  # noqa: F401  — raises OSError when PortAudio is missing
    except (ImportError, OSError):
        return False
    return True


def _threads() -> int:
    try:
        from core.hardware import _sysctl

        n = int(_sysctl("hw.perflevel0.physicalcpu") or 0)
    except Exception:
        n = 0
    return n or max(1, (os.cpu_count() or 4) // 2)


def _load() -> Any:
    global _model, _model_name
    name = get_settings().voice.whisper_model or "small"
    with _load_lock:
        if _model is None or _model_name != name:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise VoiceUnavailable("Voice input needs faster-whisper: .venv/bin/pip install faster-whisper") from exc
            t0 = time.perf_counter()
            _model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=_threads())
            _model_name = name
            logger.info("Whisper %s loaded in %.1fs", name, time.perf_counter() - t0)
    return _model


def preload() -> None:
    """Load the Whisper model in the background (no-op when it's loaded or not installed)."""
    if _model is not None or not available():
        return
    threading.Thread(target=lambda: _safe(_load), name="whisper-load", daemon=True).start()


def _safe(fn: Any) -> None:
    try:
        fn()
    except Exception:
        logger.warning("Whisper preload failed", exc_info=True)


def _run(audio: Any, language: str | None, prompt: str = "") -> tuple[str, str]:
    with _lock:
        model = _load()
        segments, info = model.transcribe(
            audio, language=language or None, beam_size=1, vad_filter=True,
            condition_on_previous_text=False, without_timestamps=True,
            initial_prompt=prompt[-200:] or None,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
    return text, info.language


def transcribe(audio: Any, language: str | None = None) -> dict[str, Any]:
    """``{"text", "language"}`` for an audio clip (webm/ogg/mp4/wav bytes, or 16 kHz float samples)."""
    source = io.BytesIO(audio) if isinstance(audio, (bytes, bytearray)) else audio
    text, lang = _run(source, language or get_settings().voice.language or None)
    return {"text": text, "language": lang}


# ── Live recording ───────────────────────────────────────────────────

class _Recording:
    """One microphone recording with background, pause-based transcription."""

    def __init__(self) -> None:
        import numpy as np

        self.np = np
        self.buf = np.zeros(SAMPLE_RATE * MAX_SECONDS, dtype="float32")  # preallocated: no copying while recording
        self.total = 0
        self.stream: Any = None
        self.stopping = threading.Event()
        self.texts: list[str] = []
        self.language: str | None = get_settings().voice.language or None
        self.levels: list[float] = []
        self.committed = 0  # samples already transcribed (or skipped as silence)
        self.last_voice = -1  # end (in samples) of the last frame with speech
        self.heard = False
        self.peak = 0.0
        self.error: Exception | None = None
        self.started = time.monotonic()
        self.worker = threading.Thread(target=self._work, name="voice-live", daemon=True)

    # audio thread
    def on_audio(self, data: Any, frames: int, _time: Any, _status: Any) -> None:
        import sounddevice as sd

        n = min(frames, len(self.buf) - self.total)
        if n > 0:
            self.buf[self.total:self.total + n] = data[:n, 0]
            self.total += n  # published after the samples are written
        if self.total >= len(self.buf):
            raise sd.CallbackStop  # closes the stream: the mic is never left recording

    def audio(self, start: int, end: int) -> Any:
        return self.buf[start:min(end, self.total)].copy()

    def threshold(self) -> float:
        if not self.levels:
            return 0.01
        floor = float(self.np.percentile(self.levels[-600:], 15))
        return max(0.008, floor * 3)

    def _transcribe(self, start: int, end: int) -> None:
        if end - start < SAMPLE_RATE // 4:
            return
        try:
            text, lang = _run(self.audio(start, end), self.language, " ".join(self.texts))
        except Exception as exc:
            self.error = exc
            return
        self.language = self.language or lang  # detect once, then reuse
        if text:
            self.texts.append(text)

    def _work(self) -> None:
        analysed = 0
        while not self.stopping.is_set():
            time.sleep(0.2)
            total = self.total
            while analysed + FRAME <= total:
                frame = self.audio(analysed, analysed + FRAME)
                level = float(self.np.sqrt(self.np.mean(frame * frame))) if len(frame) else 0.0
                self.peak = max(self.peak, float(abs(frame).max()) if len(frame) else 0.0)
                self.levels.append(level)
                analysed += FRAME
                if level > self.threshold():
                    self.last_voice = analysed
                    self.heard = True
            voiced = self.last_voice > self.committed
            if voiced and analysed - self.last_voice >= PAUSE_CUT * SAMPLE_RATE \
                    and self.last_voice - self.committed >= SAMPLE_RATE:
                cut = min(analysed, self.last_voice + int(0.3 * SAMPLE_RATE))
                self._transcribe(self.committed, cut)
                self.committed = cut
            elif analysed - self.committed > MAX_SEGMENT * SAMPLE_RATE:
                # long phrase without a pause: cut at the quietest point of its last 3 seconds
                tail = self.levels[-30:]
                cut = analysed - (len(tail) - int(self.np.argmin(tail))) * FRAME
                self._transcribe(self.committed, cut)
                self.committed = cut
            elif not voiced and analysed - self.committed > 2 * SAMPLE_RATE:
                self.committed = analysed - int(0.3 * SAMPLE_RATE)  # skip silence

    def status(self) -> dict[str, Any]:
        silence = (self.total - self.last_voice) / SAMPLE_RATE if self.heard else 0.0
        return {
            "text": " ".join(self.texts),
            "seconds": round(self.total / SAMPLE_RATE, 1),
            "speaking": self.heard and silence < 0.4,
            "ended": self.heard and silence >= END_SILENCE,
            "level": round(min(1.0, (self.levels[-1] if self.levels else 0) * 12), 3),
        }

    def finish(self) -> dict[str, Any]:
        self.stopping.set()
        self.worker.join(timeout=120)
        if self.total < SAMPLE_RATE // 4:
            return {"text": "", "language": self.language or ""}
        if self.peak == 0.0 and float(abs(self.audio(0, self.total)).max()) == 0.0:
            # macOS hands a blocked app silence instead of an error
            raise PermissionError(
                "The microphone is blocked: open System Settings → Privacy & Security → Microphone "
                "and turn on VDX OpenAgent (or Terminal, if you started it from there), then reopen the app."
            )
        tail = self.audio(self.committed, self.total)
        if len(tail) >= SAMPLE_RATE // 4 and (not self.heard or self.last_voice > self.committed):
            self._transcribe(self.committed, self.total)
        if self.error and not self.texts:
            raise self.error
        return {"text": " ".join(self.texts).strip(), "language": self.language or ""}


_rec: dict[str, Any] = {"current": None}
_rec_lock = threading.Lock()


def start_recording() -> None:
    """Start recording the default microphone (and loading Whisper meanwhile)."""
    import sounddevice as sd

    stop_recording(discard=True)
    preload()
    rec = _Recording()
    try:
        rec.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=FRAME // 2,
                                    callback=rec.on_audio)
        rec.stream.start()
    except Exception as exc:
        raise RuntimeError(f"Could not open the microphone: {exc}") from exc
    rec.worker.start()
    with _rec_lock:
        _rec["current"] = rec


def _close(rec: _Recording) -> None:
    try:
        rec.stream.stop()
    except Exception:
        pass
    try:
        rec.stream.close()
    except Exception:
        pass


def stop_recording(discard: bool = False) -> _Recording | None:
    """Stop recording; returns the recording (None when discarded or nothing was recording)."""
    with _rec_lock:
        rec, _rec["current"] = _rec["current"], None
    if rec is None:
        return None
    _close(rec)
    if discard:
        rec.stopping.set()
        return None
    return rec


def recording_status() -> dict[str, Any]:
    """Live text and pause detection of the recording in progress."""
    rec = _rec["current"]
    if rec is None:
        return {"recording": False, "text": "", "seconds": 0, "speaking": False, "ended": False, "level": 0}
    return {"recording": True, **rec.status()}


def transcribe_recording() -> dict[str, Any]:
    """Stop the recording and return its full transcription."""
    rec = stop_recording()
    if rec is None:
        return {"text": "", "language": ""}
    return rec.finish()


# ── Text to speech (macOS `say`) ─────────────────────────────────────

_say: dict[str, Any] = {"proc": None, "voices": None, "language": ""}
_STOP = {
    "it": "il lo la gli le che di per non sono è una con questo anche come più ma",
    "en": "the and is are you that this with for not have be it of to",
    "es": "el los las que de por para con una está son pero como más",
    "fr": "le les des que est pour pas une avec dans sont mais vous nous",
    "de": "der die das und ist nicht mit ein eine für auf sind aber wie",
    "pt": "o os as que de para com uma não são mas como mais você",
}
_PREFERRED = {"it": ("Alice", "Federica", "Luca"), "en": ("Samantha", "Ava", "Daniel", "Karen"),
              "es": ("Mónica", "Paulina", "Jorge"), "fr": ("Amélie", "Thomas"), "de": ("Anna", "Petra"),
              "pt": ("Luciana", "Joana")}


def _guess_language(text: str) -> str:
    words = re.findall(r"[a-zàèéìòùáíóúñçäöüß]+", text.lower())[:300]
    scores = {lang: sum(w in set(sw.split()) for w in words) for lang, sw in _STOP.items()}
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    return best if scores[best] >= 2 else ""


def _voices() -> list[tuple[str, str]]:
    if _say["voices"] is None:
        try:
            out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        _say["voices"] = [(m.group(1).strip(), m.group(2)) for m in
                          re.finditer(r"^(.+?)\s{2,}([a-z]{2,3}[_-][A-Za-z]{2,4})", out, re.M)]
    return _say["voices"]


def _voice_for(lang: str) -> str:
    cands = [name for name, loc in _voices() if loc.lower().startswith(lang)]
    if not cands:
        return ""
    for tag in ("(Premium)", "(Enhanced)"):
        if (v := next((c for c in cands if tag in c), None)):
            return v
    for pref in _PREFERRED.get(lang, ()):
        if (v := next((c for c in cands if c.split(" (")[0] == pref), None)):
            return v
    return cands[0]


def _plain(text: str) -> str:
    """Markdown → something worth reading aloud."""
    text = re.sub(r"```.*?```", " (code omitted) ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.M)
    text = re.sub(r"[*_`#>|]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def speak(text: str, language: str = "") -> bool:
    """Read *text* aloud with a voice matching its language; returns False when ``say`` is missing."""
    stop_speaking()
    clean = _plain(text)[:6000]
    if not clean:
        return True
    lang = (language or _guess_language(clean) or "").split("-")[0].lower()
    voice = _voice_for(lang) if lang else ""
    try:
        proc = subprocess.Popen(["say", *(["-v", voice] if voice else [])], stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    _say["proc"] = proc
    try:
        assert proc.stdin
        proc.stdin.write(clean.encode("utf-8"))
        proc.stdin.close()
    except OSError:
        pass
    return True


def speaking() -> bool:
    p = _say["proc"]
    return bool(p and p.poll() is None)


def stop_speaking() -> None:
    p = _say["proc"]
    if p and p.poll() is None:
        p.terminate()
    _say["proc"] = None
