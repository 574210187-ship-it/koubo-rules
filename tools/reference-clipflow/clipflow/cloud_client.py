"""Authenticated, audio-only client for a shared ClipFlow ASR server.

Only compressed speech chunks are sent; video frames, source MP4, subtitles,
and user identifiers never leave the client. Requires an explicit endpoint
and API key in environment variables (no anonymous fallback).
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .asr import Recognition, TimedText, _captions_from_words, estimate_character_timing

DEFAULT_CHUNK_SECONDS = 20
MAX_CHUNK_BYTES = 3_000_000  # stays below common serverless 4.5 MB limits


class _RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("云端ASR地址发生跳转，为防止密钥泄漏已拒绝跟随重定向")


def configured() -> bool:
    return bool(os.getenv("CLIPFLOW_ASR_URL") and os.getenv("CLIPFLOW_ASR_API_KEY"))


def _endpoint(url: str) -> str:
    url = url.rstrip("/")
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("云端ASR地址不能包含账号、口令、查询参数或片段")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")):
        raise ValueError("云端ASR必须使用 HTTPS（仅 localhost 允许 HTTP 用于测试）")
    if not parsed.netloc:
        raise ValueError("无效的云端ASR URL")
    if parsed.path and parsed.path != "/":
        raise ValueError("云端ASR URL 应是服务器根地址，不要包含具体路由")
    return url + "/v1/transcribe"


def _audio_duration(source: Path) -> float:
    proc = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(source),
    ], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("无法读取音频时长，可能缺少可用音轨")
    try:
        duration = float(proc.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("无法读取音频时长") from exc
    if not 0 < duration <= 10800:
        raise RuntimeError("音频时长无效或超过3小时上限")
    return duration


def _extract_chunk(source: Path, path: Path, offset: float, duration: float) -> bytes:
    proc = subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{offset:.3f}", "-i", str(source), "-t", f"{duration:.3f}",
        "-vn", "-sn", "-dn", "-map", "0:a:0", "-ac", "1", "-ar", "16000",
        "-c:a", "flac", str(path),
    ], capture_output=True, text=True)
    if proc.returncode or not path.is_file():
        raise RuntimeError("无法提取云端ASR所需的音频片段: " + proc.stderr[-200:])
    if path.stat().st_size > MAX_CHUNK_BYTES:
        raise RuntimeError("音频分块超过3MB限制；可将 CLIPFLOW_ASR_CHUNK_SECONDS 调小")
    return path.read_bytes()


def _span(item: dict, shift: float, end: float) -> TimedText:
    if not isinstance(item, dict):
        raise ValueError("云端ASR返回了无效的时间戳结构")
    text = item.get("text", "")
    if not isinstance(text, str):
        raise ValueError("云端ASR返回非文字内容")
    start = float(item["start"])
    finish = float(item["end"])
    if not math.isfinite(start) or not math.isfinite(finish) or start < 0 or finish <= start or start > end + .2:
        raise ValueError("云端ASR返回无效的起止时间")
    return TimedText(shift + start, shift + min(finish, end), text)


def recognize_cloud(source: Path, model: str = "small", language: str = "zh") -> Recognition:
    url = os.getenv("CLIPFLOW_ASR_URL", "")
    key = os.getenv("CLIPFLOW_ASR_API_KEY", "")
    if not url or not key:
        raise RuntimeError("云端ASR尚未配置：需要在安全环境变量中设置 CLIPFLOW_ASR_URL 和 CLIPFLOW_ASR_API_KEY；不要把密钥写入提示词或GitHub")
    endpoint = _endpoint(url)
    try:
        chunk_seconds = int(os.getenv("CLIPFLOW_ASR_CHUNK_SECONDS", str(DEFAULT_CHUNK_SECONDS)))
    except ValueError as exc:
        raise ValueError("CLIPFLOW_ASR_CHUNK_SECONDS 必须是整数") from exc
    if not 5 <= chunk_seconds <= 25:
        raise ValueError("CLIPFLOW_ASR_CHUNK_SECONDS 必须为5至25秒")
    if not source.is_file():
        raise FileNotFoundError(source)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("云端ASR客户端仍需要本地 FFmpeg/FFprobe 来提取音频")
    duration = _audio_duration(source)
    opener = build_opener(_RejectRedirect())
    all_words: list[TimedText] = []
    all_captions: list[TimedText] = []
    used_estimation = False
    recognized_language = language
    with tempfile.TemporaryDirectory(prefix="clipflow_asr_upload_") as temp:
        for i in range(math.ceil(duration/chunk_seconds)):
            offset = i * chunk_seconds
            length = min(chunk_seconds, duration - offset)
            chunk_path = Path(temp) / "speech.flac"
            data = _extract_chunk(source, chunk_path, offset, length)
            params = f"?language={language if language in ('auto','zh','en') else 'auto'}"
            req = Request(endpoint + params, data=data, method="POST", headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "audio/flac",
                "Accept": "application/json",
                "User-Agent": "ClipFlow-ASR-Client",
            })
            try:
                with opener.open(req, timeout=180) as resp:
                    body = resp.read(3_000_000 + 1)
            except HTTPError as exc:
                raise RuntimeError(f"云端ASR HTTP {exc.code}；请核对服务状态、访问密钥与额度") from exc
            except (URLError, TimeoutError) as exc:
                raise RuntimeError("云端ASR连接失败；请核对服务域名与网络可达性") from exc
            if len(body) > 3_000_000:
                raise RuntimeError("云端ASR响应超出安全大小限制")
            try:
                payload = json.loads(body)
                raw_words = payload.get("words", [])
                raw_captions = payload.get("captions", [])
                if not isinstance(raw_words, list) or not isinstance(raw_captions, list):
                    raise ValueError("无效响应类型")
                words = [_span(w, offset, length) for w in raw_words if w.get("text", "").strip()]
                captions = [_span(w, offset, length) for w in raw_captions if w.get("text", "").strip()]
                recognized_language = payload.get("language", recognized_language)
                if payload.get("alignment") != "word_timestamps":
                    used_estimation = True
                if not words and captions:
                    words = estimate_character_timing(captions)
                    used_estimation = True
                all_words.extend(words)
                all_captions.extend(captions)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                raise RuntimeError("云端ASR返回无效JSON或时间戳结构") from exc
            chunk_path.unlink(missing_ok=True)
    if not all_captions and all_words:
        all_captions = _captions_from_words(all_words)
    if not all_captions:
        raise RuntimeError("云端ASR没有识别到有效人声，不能生成虚构字幕")
    all_words.sort(key=lambda v:v.start)
    all_captions.sort(key=lambda v:v.start)
    return Recognition(all_captions,all_words,
                       "cloud_mixed_estimated" if used_estimation else "cloud_word_timestamps",
                       str(recognized_language))
