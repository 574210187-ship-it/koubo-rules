"""One paragraph per numbered clip from *visible* subtitle OCR only.

Never infer spoken content from a moving mouth or a filename.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable


def human_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    minutes, rest = divmod(millis, 60_000)
    sec, ms = divmod(rest, 1000)
    if not ms:
        return f'{minutes:02d}:{sec:02d}'
    return f'{minutes:02d}:{sec:02d}.{ms:03d}'


def assign_cues_to_segments(entries: list[dict], captions: Iterable) -> list[str]:
    """Return visible subtitle text for each clip, deduplicated within it.

    A caption straddling a shot boundary is shown in both clips, because the
    words are visibly present in both. There is *no* fabricated speech timing.
    """
    captions = list(captions)
    out: list[str] = []
    for entry in entries:
        start,end=float(entry['start']),float(entry['end'])
        lines = []
        for cue in captions:
            overlap = max(0, min(float(cue.end),end) - max(float(cue.start),start))
            # OCR sample times are approximate (+/- half the scan interval).
            # Do not leak a preceding caption into the next clip for a tiny
            # overlap introduced by sampling around a hard scene cut.
            min_overlap = min(0.28, max(0.12, 0.20*(float(cue.end)-float(cue.start))))
            if overlap < min_overlap:
                continue
            text = str(cue.text).strip()
            if text and (not lines or text != lines[-1]):
                lines.append(text)
        out.append(' '.join(lines).strip())
    return out


def write_segment_document(path: Path, reference_name: str, duration: float,
                           entries: list[dict], transcript_parts: list[str],
                           source: str) -> None:
    """Always write MD, even when video has no visible captions."""
    if len(entries) != len(transcript_parts):
        raise ValueError('视频片段数量与分段台词不一致')
    labels = {
        'visual_ocr':'原视频画面中的可见字幕（机器OCR识别，待核对）',
        'supplied_srt':'用户提供的字幕文件（非音频识别）',
        'none_visible':'原视频画面未发现可信的可识别字幕',
    }
    lines = [
        '# ClipFlow｜按视频片段整理的台词', '',
        f'- 原视频：`{reference_name.replace("`", "")}`',
        f'- 原视频总时长：{human_time(duration)}',
        f'- 切分视频：{len(entries)} 段',
        f'- 文案来源：{labels.get(source, source)}',
        '- 说明：每个视频段只标一次起止时间；不显示逐句时间轴。',
        '- 重要：只识别画面上可见文字，不读取音轨。无画面字幕的口播台词无法据此还原。',
        '',
    ]
    for entry,text in zip(entries,transcript_parts):
        i=int(entry['index'])
        start,end=float(entry['start']),float(entry['end'])
        lines.extend([
            f'## 第{i:03d}段｜{human_time(start)}—{human_time(end)}',
            f'- 视频：`{entry["file"]}`',
            '',
            f'**台词：** {text if text else "（本段未检测到可识别画面字幕；口播内容未知）"}',
            '',
        ])
    path.write_text('\n'.join(lines).rstrip()+'\n', encoding='utf-8')
