"""Local speech-to-text via faster-whisper (CTranslate2), exposed as a BFF.

Adapted from the companion project's `services/stt.py`. CPU int8 by default --
local, no torch, no cloud, and no contention with LM Studio for VRAM (which on
this box is already holding most of the 12GB).

`faster-whisper` bundles ffmpeg through PyAV, so it decodes the browser's
WebM/Opus recording directly; no system ffmpeg is needed.

The model is baked into the image at build time (see Containerfile) so the
container does not reach for the network on first use. If latency disappoints on
longer clips, the escape hatch is to point WHISPER_* at a GPU whisper container
on ai-net instead of growing this one.

Transport note: audio arrives base64-encoded because pytincture's BFF transport
is JSON. `BFF_REQUEST_MAX_BYTES` defaults to 1 MiB, which after base64's 4/3
inflation is roughly four minutes of Opus -- ample for push-to-talk, and the
widget caps a single take anyway.
"""

from __future__ import annotations

import base64
import binascii
import io
import os

from pytincture.dataclass import backend_for_frontend

MODEL = os.environ.get("WHISPER_MODEL", "base.en")
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8")
CACHE = os.environ.get("WHISPER_CACHE", "/app/models/whisper")

# Refuse obviously oversized payloads before decoding them. The BFF layer has
# its own limit; this keeps a bad caller from materialising a large bytes object
# inside the worker.
MAX_AUDIO_BYTES = int(os.environ.get("WA_STT_MAX_BYTES", str(8 * 1024 * 1024)))

_model = None


def _whisper():
    """Load the model once, lazily.

    Import inside the function so that merely importing this module -- which the
    app does at startup -- does not pull in ctranslate2 and PyAV.
    """
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            MODEL, device=DEVICE, compute_type=COMPUTE, download_root=CACHE
        )
    return _model


def transcribe_bytes(audio: bytes, language: str | None = None) -> str:
    """Transcribe audio bytes (any ffmpeg-decodable container) to plain text.

    `vad_filter` trims leading and trailing silence, so a push-to-talk clip with
    dead air at either end does not hallucinate words into it; `beam_size=1`
    keeps latency down, which matters more than the last point of accuracy for
    short dictation.
    """
    segments, _info = _whisper().transcribe(
        io.BytesIO(audio),
        language=language,
        beam_size=1,
        vad_filter=True,
    )
    return "".join(segment.text for segment in segments).strip()


@backend_for_frontend
class stt:
    """Speech-to-text for the composer's push-to-talk button."""

    def transcribe(self, payload):
        """Transcribe a base64 audio clip.

        Accepts the payload the wapyt chat widget emits on its ``voice`` event:
        ``{"audio": "<base64>", "mimeType": "audio/webm;codecs=opus", ...}``.

        Returns ``{"text": ...}`` on success or ``{"error": ...}`` on failure.
        Errors are returned rather than raised so the UI can show something
        useful instead of a dead button -- the same in-band convention the
        streaming proxy uses.
        """
        if not isinstance(payload, dict):
            return {"error": "payload must be an object"}

        raw = payload.get("audio")
        if not raw:
            return {"error": "no audio in payload"}

        # base64 is 4/3 the size of the bytes it encodes.
        if len(raw) > MAX_AUDIO_BYTES * 4 // 3:
            return {"error": "audio too large"}

        try:
            audio = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            return {"error": "audio is not valid base64"}

        if not audio:
            return {"error": "audio is empty"}
        if len(audio) > MAX_AUDIO_BYTES:
            return {"error": "audio too large"}

        language = payload.get("language") or os.environ.get("WA_STT_LANGUAGE")
        # base.en is English-only; passing a language to it is meaningless and
        # faster-whisper warns. Only forward one for multilingual models.
        if MODEL.endswith(".en"):
            language = None

        try:
            text = transcribe_bytes(audio, language=language)
        except Exception as exc:  # pragma: no cover - engine/runtime failures
            return {"error": f"transcription failed: {exc}"}

        return {"text": text, "bytes": len(audio), "model": MODEL}

    def get_status(self):
        """Whether STT is usable, without loading the model.

        The UI calls this to decide whether to offer the microphone at all.
        """
        try:
            import faster_whisper  # noqa: F401
        except Exception as exc:
            return {"available": False, "reason": str(exc), "model": MODEL}
        return {"available": True, "model": MODEL, "device": DEVICE, "compute": COMPUTE}
