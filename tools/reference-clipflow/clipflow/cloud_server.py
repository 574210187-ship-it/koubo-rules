"""Opt-in, shared Cloud ASR endpoint; suitable for private CPU containers.

Security: bearer token required, audio-only, HTTPS termination at provider,
3 MB / 25s chunks, serialized transcriptions, ephemeral file deletion.
No customer media is written to GitHub or to persistent application storage.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .asr import recognize_local

app = FastAPI(title="ClipFlow ASR", docs_url=None, redoc_url=None, openapi_url=None)
_LOCK = asyncio.Lock()
_MAX_BYTES = 3_000_000
_MAX_SECONDS = 30


def _key() -> str:
    return os.getenv("CLIPFLOW_ASR_SERVER_KEY", "")


def _authorize(request: Request) -> None:
    key = _key()
    provided = request.headers.get("authorization", "")
    if not key:
        raise HTTPException(503, "ASR service not configured")
    if not provided.startswith("Bearer ") or not secrets.compare_digest(provided[7:], key):
        raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel
    selected = os.getenv("CLIPFLOW_ASR_SERVER_MODEL", "small")
    return WhisperModel(selected,device="cpu",compute_type="int8",
                        download_root=os.getenv("CLIPFLOW_ASR_MODEL_CACHE", "/opt/asr-cache"))


@app.get("/health")
async def health():
    if not _key():
        return JSONResponse({"status":"not_configured"},status_code=503)
    return {"status":"ready_for_authenticated_requests","model_loaded":_model.cache_info().currsize>0}


@app.post("/v1/transcribe")
async def transcribe(request: Request, language: str = "zh"):
    _authorize(request)
    if language not in ("zh","en","auto"):
        raise HTTPException(400, "Unsupported language")
    if request.headers.get("content-type", "").split(";",1)[0].strip() not in ("audio/flac","audio/wav","application/octet-stream"):
        raise HTTPException(415, "Audio FLAC or WAV required")
    if _LOCK.locked():
        raise HTTPException(429, "ASR busy; retry later")
    async with _LOCK:
        with tempfile.TemporaryDirectory(prefix="clipflow_asr_server_") as temp:
            target=Path(temp)/"speech.flac"
            size=0
            with target.open("wb") as stream:
                async for block in request.stream():
                    size+=len(block)
                    if size > _MAX_BYTES:
                        raise HTTPException(413,"Audio chunk too large")
                    stream.write(block)
            if not size:
                raise HTTPException(400,"Empty audio upload")
            proc = await asyncio.create_subprocess_exec(
                "ffprobe","-v","error","-select_streams","a:0",
                "-show_entries","format=duration","-of","default=nw=1:nk=1",str(target),
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            out, _ = await proc.communicate()
            try:
                duration=float(out.decode().strip())
            except ValueError:
                duration=0
            if proc.returncode != 0 or not 0 < duration <= _MAX_SECONDS:
                raise HTTPException(422,"Invalid audio chunk or duration exceeds 30s")
            try:
                # One model per process; inference uses a thread to avoid blocking I/O.
                recognized = await asyncio.to_thread(recognize_local, target,
                                   model="small",device="cpu",language=language,
                                   model_instance=_model())
            except RuntimeError as exc:
                # Never print audio, tokens, or source data in logs.
                raise HTTPException(503,"ASR inference unavailable") from exc
            return {
                "captions":[{"start":s.start,"end":s.end,"text":s.text} for s in recognized.captions],
                "words":[{"start":s.start,"end":s.end,"text":s.text} for s in recognized.words],
                "alignment":recognized.alignment,
                "language":recognized.language,
            }
