"""Local, optional speech-to-text backend for ClipFlow.

The reference video can have no visible captions: speech is recognized from its
original audio track.  Timestamp quality is recorded; estimated character
positions are never presented as real word alignment.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


@dataclass(frozen=True)
class TimedText:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Recognition:
    captions: list[TimedText]
    words: list[TimedText]
    alignment: str
    language: str


def estimate_character_timing(captions: list[TimedText]) -> list[TimedText]:
    """Approximate token timing when a supplied SRT/ASR lacks word stamps."""
    tokens: list[TimedText] = []
    for cue in captions:
        chars = list(cue.text)
        if not chars or cue.end <= cue.start:
            continue
        for i, char in enumerate(chars):
            start = cue.start + (cue.end-cue.start)*i/len(chars)
            end = cue.start + (cue.end-cue.start)*(i+1)/len(chars)
            tokens.append(TimedText(start,end,char))
    return tokens


def _captions_from_words(words: list[TimedText], max_chars: int = 16,
                         max_duration: float = 3.5) -> list[TimedText]:
    """Group word-stamped recognition into short, readable SRT cues."""
    cues: list[TimedText] = []
    bucket: list[TimedText] = []

    def flush() -> None:
        if not bucket:
            return
        msg = "".join(w.text for w in bucket).strip()
        if msg:
            cues.append(TimedText(bucket[0].start, bucket[-1].end, msg))
        bucket.clear()

    for word in words:
        if bucket and word.start - bucket[-1].end >= 0.65:
            flush()
        bucket.append(word)
        msg = "".join(w.text for w in bucket).strip()
        if (len(msg) >= max_chars or bucket[-1].end-bucket[0].start >= max_duration
                or bool(re.search(r"[。！？!?；;]$", msg))):
            flush()
    flush()
    return cues


def recognize_local(source: Path, model: str = "small", device: str = "cpu",
                    language: str = "zh", model_instance=None) -> Recognition:
    """Transcribe audio/video offline using installed faster-whisper.

    First invocation of a named model such as ``small`` normally needs an
    internet connection for the weights; a local model directory also works.
    It never sends user media to ClipFlow or GitHub servers.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "缺少语音识别依赖 faster-whisper。进入ClipFlow目录执行 "
            "python -m pip install -e '.[asr]'，再运行 clipflow doctor。"
            "首次使用模型可能需要联网下载权重；也可使用 --srt 导入已核对字幕。"
        ) from exc
    if not source.is_file():
        raise FileNotFoundError(source)
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("语音提取需要安装 FFmpeg。")

    with tempfile.TemporaryDirectory(prefix="clipflow_asr_") as tmp:
        wav = Path(tmp) / "speech_mono16k.wav"
        proc = subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-vn", "-sn", "-dn", "-map", "0:a:0",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)
        ], capture_output=True, text=True)
        if proc.returncode or not wav.is_file():
            raise RuntimeError(
                "无法从输入文件提取音频；请确认视频包含可解码的音轨。"
                f" FFmpeg: {proc.stderr[-600:]}"
            )
        try:
            wm = model_instance if model_instance is not None else WhisperModel(
                model, device=device, compute_type="int8" if device == "cpu" else "auto")
            segments, details = wm.transcribe(
                str(wav), language=None if language == "auto" else language, vad_filter=True,
                word_timestamps=True, beam_size=5,
                condition_on_previous_text=False,
            )
            captions: list[TimedText] = []
            words: list[TimedText] = []
            had_estimates = False
            for seg in segments:
                seg_words: list[TimedText] = []
                for word in getattr(seg, "words", None) or []:
                    text = str(getattr(word,"word","") or "")
                    if not text.strip():
                        continue
                    start = max(0.0, float(word.start))
                    end = max(start + 0.01, float(word.end))
                    seg_words.append(TimedText(start,end,text))
                if seg_words:
                    words.extend(seg_words)
                    captions.extend(_captions_from_words(seg_words))
                elif str(seg.text).strip():
                    start = max(0.0, float(seg.start))
                    end = max(start+0.05, float(seg.end))
                    approx = TimedText(start,end,str(seg.text).strip())
                    # Not word-level alignment: only an estimate from ASR span.
                    words.extend(estimate_character_timing([approx]))
                    captions.extend(_captions_from_words(
                        estimate_character_timing([approx])))
                    had_estimates = True
        except Exception as exc:
            raise RuntimeError(
                "本地ASR模型加载或转写失败。请检查模型下载/缓存、运行设备"
                "和内存；可用 --model 指定本地模型目录。"
                f" 原因：{type(exc).__name__}: {str(exc)[:400]}"
            ) from exc
    captions.sort(key=lambda x:x.start)
    words.sort(key=lambda x:x.start)
    if not captions or not words:
        raise RuntimeError("ASR未识别到有效语音，不会生成虚构SRT；请检查音轨或提供 --srt。")
    return Recognition(captions, words,
                       "mixed_estimated" if had_estimates else "word_timestamps",
                       str(getattr(details,"language",language)))


def recognize(source: Path, model: str = "small", device: str = "cpu",
              language: str = "zh", backend: str = "auto") -> Recognition:
    """Cloud-first if configured, otherwise backwards-compatible local ASR."""
    import os
    backend = os.getenv("CLIPFLOW_ASR_BACKEND", backend) if backend == "auto" else backend
    if backend not in ("auto", "cloud", "local"):
        raise ValueError("ASR backend must be auto, cloud or local")
    cloud_ready = bool(os.getenv("CLIPFLOW_ASR_URL") and os.getenv("CLIPFLOW_ASR_API_KEY"))
    if backend == "cloud" or (backend == "auto" and cloud_ready):
        from .cloud_client import recognize_cloud
        return recognize_cloud(source, model=model, language=language)
    if backend == "auto" and (os.getenv("CLIPFLOW_ASR_URL") or os.getenv("CLIPFLOW_ASR_API_KEY")):
        raise RuntimeError("云端ASR配置不完整：需要同时设置URL和API_KEY")
    return recognize_local(source, model=model, device=device, language=language)
