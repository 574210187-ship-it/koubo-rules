"""Generate one grounded, human-readable script/timing report per source video."""
from __future__ import annotations

from bisect import bisect_right
from pathlib import Path
from typing import Iterable

from .asr import TimedText


def human_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    minutes, rest = divmod(millis, 60_000)
    sec, ms = divmod(rest, 1000)
    return f"{minutes:02d}:{sec:02d}.{ms:03d}"


def assign_words_to_segments(entries: list[dict], words: Iterable[TimedText]) -> list[str]:
    """Assign each recognized token exactly once by its timestamp midpoint.

    Token timing is speech aligned from Whisper when available, or clearly
    documented as estimated when words were reconstructed from an SRT.
    """
    if not entries:
        return []
    boundaries = [float(x["start"]) for x in entries] + [float(entries[-1]["end"])]
    buffers: list[list[str]] = [[] for _ in entries]
    for word in words:
        midpoint = (word.start+word.end)/2
        if not word.text or midpoint < boundaries[0]-.1 or midpoint > boundaries[-1]+.1:
            continue
        idx = max(0,min(len(entries)-1,bisect_right(boundaries,midpoint)-1))
        buffers[idx].append(word.text)
    return ["".join(x).strip() for x in buffers]


def write_segment_document(path: Path, reference_name: str, duration: float,
                           entries: list[dict], transcript_parts: list[str],
                           source: str, alignment: str, model: str | None = None) -> None:
    if len(entries) != len(transcript_parts):
        raise ValueError("片段数量与台词列表不一致")
    source_label = ("本地 faster-whisper ASR（原视频音频）" if source == "faster_whisper_asr"
                    else "用户提供的 SRT（非本次自动语音识别）")
    alignment_label = ("Whisper词级时间戳" if alignment == "word_timestamps"
                       else "部分词级时间由ASR片段估算" if alignment == "mixed_estimated"
                       else "按SRT字幕时间估算字级位置")
    lines = [
        "# 对标视频｜逐片段时间与台词",
        "",
        f"- 原视频：`{reference_name.replace('`','')}`",
        f"- 总时长：{human_time(duration)}（{duration:.3f} 秒）",
        f"- 片段数量：{len(entries)}",
        f"- 文字来源：{source_label}" + (f"；模型：`{model}`" if model and source=="faster_whisper_asr" else ""),
        f"- 分配依据：{alignment_label}；时间均以原视频开头为 00:00.000",
        "- 校对提示：ASR可能识别错字；建议根据原声复核人名、法律术语、方言与句尾。",
        "",
        "## 按镜头顺序逐段台词",
        "",
    ]
    for entry,script in zip(entries,transcript_parts):
        idx=int(entry["index"])
        start=float(entry["start"]);end=float(entry["end"])
        lines.extend([
            f"### {idx:03d}｜{human_time(start)} — {human_time(end)}｜{end-start:.3f} 秒",
            f"- 文件：`{entry['file']}`",
            f"- 台词：{script if script else '（本段未识别到讲话）'}",
            "",
        ])
    path.write_text("\n".join(lines),encoding="utf-8")


def write_whole_transcript(path: Path, input_name: str, captions: list[TimedText],
                          model: str, language: str, alignment: str) -> None:
    lines = ["# 视频／音频语音识别稿", "", f"- 来源：`{input_name.replace('`','')}`",
             f"- ASR模型：`{model}`",f"- 语言：`{language}`",
             f"- 时间戳：`{alignment}`", "- 提醒：机器识别内容需人工校对。", "",
             "## 原声识别结果", ""]
    for cue in captions:
        lines.append(f"**{human_time(cue.start)} — {human_time(cue.end)}**  {cue.text}")
        lines.append("")
    path.write_text("\n".join(lines),encoding="utf-8")
