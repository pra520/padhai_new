"""Speech-to-text for uploaded audio lectures.

Uses faster-whisper (free, open-source, runs fully locally — no API, no
billing). It is an OPTIONAL dependency because the model download is
~75 MB; install it with:

    pip install -r backend/requirements-audio.txt

Text-to-speech is handled in the browser with the free built-in
SpeechSynthesis API — nothing needed server-side.
"""
import io
import logging
import os

log = logging.getLogger("padhai.audio")

try:
    from faster_whisper import WhisperModel
    _INSTALLED = True
except ImportError:
    _INSTALLED = False

_model = None

INSTALL_HINT = (
    "Audio transcription is not enabled on this server. Install the free "
    "open-source Whisper engine with:  pip install -r backend/requirements-audio.txt  "
    "then restart Padhai. (First transcription downloads a ~75 MB model once.)"
)


def available() -> bool:
    return _INSTALLED


def transcribe(data: bytes) -> tuple[str, dict]:
    """Return (transcript_text, meta). Raises RuntimeError if unavailable."""
    if not _INSTALLED:
        raise RuntimeError(INSTALL_HINT)

    global _model
    if _model is None:
        # "base" is a good speed/accuracy balance on CPU; override via env.
        model_name = os.getenv("WHISPER_MODEL", "base")
        log.info("Loading Whisper model '%s' (first run downloads it)…", model_name)
        _model = WhisperModel(model_name, device="cpu", compute_type="int8")

    segments, info = _model.transcribe(io.BytesIO(data), vad_filter=True)
    parts = [seg.text.strip() for seg in segments]
    text = "\n".join(p for p in parts if p)
    if not text.strip():
        raise RuntimeError("No speech detected in this audio file.")

    meta = {
        "pages": None,
        "words": len(text.split()),
        "duration_sec": round(info.duration or 0),
        "language": info.language,
        "kind": "audio",
    }
    return text, meta
