"""OCR ONLY from visible video-frame subtitles; never reads an audio track.

The OCR timestamps describe when text was *seen on the video*, not when a
speaker said those words. All machine-read captions require human review.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from difflib import SequenceMatcher
from io import StringIO
from pathlib import Path
import re
import shutil
import subprocess


@dataclass(frozen=True)
class VisualCue:
    start: float
    end: float
    text: str
    confidence: float = 0.0


def check_ocr(language: str = 'chi_sim+eng') -> dict:
    """Fail clearly when Tesseract or required Chinese language data is missing."""
    exe = shutil.which('tesseract')
    if not exe:
        raise RuntimeError('画面字幕OCR需要Tesseract及中文语言包 chi_sim；当前缺少 tesseract 命令。不会改用音频识别。')
    proc = subprocess.run([exe, '--list-langs'], capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError('无法查询Tesseract语言包：' + proc.stderr[-400:])
    available = set(proc.stdout.splitlines()) | set(proc.stderr.splitlines())
    missing = [lang for lang in language.split('+') if lang not in available]
    if missing:
        raise RuntimeError('Tesseract缺少OCR语言包：' + ', '.join(missing) + '；请安装语言数据后重试。不会调用语音识别。')
    return {'tesseract': exe, 'languages': language}


def _clean_text(text: str) -> str:
    s = re.sub(r'\s+', ' ', str(text)).strip()
    s = re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])', '', s)
    return s.strip('|／/·-_,，。．*~').strip()


def _substantive(text: str) -> bool:
    # A random stroke or a face pattern is NOT a subtitle.
    han = re.findall(r'[\u3400-\u9fff]', text)
    ascii_words = re.findall(r'[a-zA-Z0-9]', text)
    return len(han) >= 2 or len(ascii_words) >= 5


def _read_tsv(image, language: str, *, psm: int = 6) -> list[tuple[str, float, int]]:
    """Tesseract TSV grouped by OCR line, retaining confidence and width."""
    import cv2
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        return []
    result = subprocess.run(
        ['tesseract', 'stdin', 'stdout', '-l', language,
         '--psm', str(psm), 'tsv'], input=encoded.tobytes(), capture_output=True,
        timeout=28,
    )
    if result.returncode:
        return []
    content = result.stdout.decode('utf-8-sig', errors='replace')
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in csv.DictReader(StringIO(content), delimiter='\t'):
        if row.get('level') != '5' or not str(row.get('text') or '').strip():
            continue
        try:
            confidence = float(row.get('conf') or -1)
        except ValueError:
            continue
        if confidence < 20:
            continue
        key = (row.get('block_num') or '', row.get('par_num') or '', row.get('line_num') or '')
        groups.setdefault(key, []).append(row)
    lines = []
    for words in groups.values():
        words.sort(key=lambda x:int(x.get('left') or 0))
        text = _clean_text(''.join(w['text'].strip() if re.search(r'[\u3400-\u9fff]',w['text'])
                                   else ' '+w['text'] for w in words))
        if not _substantive(text):
            continue
        confs = [float(w['conf']) for w in words]
        confidence = sum(confs)/len(confs)
        if confidence < 39:
            continue
        # English-only faces and background patterns often hallucinate words.
        # Real English captions normally OCR with much higher confidence.
        if len(re.findall(r'[\u3400-\u9fff]',text)) < 2 and confidence < 80:
            continue
        x0 = min(int(w['left']) for w in words)
        x1 = max(int(w['left']) + int(w['width']) for w in words)
        # Ignore tiny narrow OCR artifacts and small background labels.
        if x1 - x0 < max(42, image.shape[1]*.08):
            continue
        lines.append((text, round(confidence, 2), x1-x0))
    return lines


def read_frame_subtitle(frame, *, language: str = 'chi_sim+eng',
                        region=(0.06, 0.49, 0.94, 0.94)) -> tuple[str, float]:
    """Read central lower subtitle band of a raw video frame (never watermark)."""
    import cv2
    x0,y0,x1,y1 = region
    h,w = frame.shape[:2]
    crop = frame[max(0, int(h*y0)):min(h,int(h*y1)),
                 max(0,int(w*x0)):min(w,int(w*x1))]
    if not crop.size:
        return '', 0.
    # Upscale the native subtitle region for fine strokes in compressed video.
    scale = max(1.0, 1000/max(1,crop.shape[1]))
    if scale > 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(gray)
    candidates = _read_tsv(enhanced, language)
    if not candidates:
        # White text with black outline or black text on light background.
        binary = cv2.adaptiveThreshold(enhanced,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY,35,9)
        candidates = _read_tsv(binary, language)
    if not candidates:
        return '', 0.
    # Multiple subtitle rows are joined only when they are in the same crop.
    # This is deliberately conservative; verify OCR with original screenshots.
    candidates.sort(key=lambda x:x[1],reverse=True)
    text, conf, width = candidates[0]
    return _clean_text(text), conf


def subtitles_from_video(video: Path, duration: float, *, step: float = 0.55,
                         language: str = 'chi_sim+eng',
                         region=(0.06,0.49,0.94,0.94)) -> tuple[list[VisualCue], dict]:
    """Sample original video frames; collect persistent lines as subtitle cues.

    At least 2 agreeing samples required, except one highly confident long
    line. This prevents face/background objects from becoming invented dialog.
    """
    import cv2
    if step < 0.2 or step > 2.0:
        raise ValueError('OCR采样间隔须为0.2—2.0秒')
    check_ocr(language)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f'无法读取视频画面进行OCR：{video}')
    observations: list[tuple[float,str,float]] = []
    samples = 0
    try:
        t = min(step/2, max(0,duration/2))
        while t < duration:
            cap.set(cv2.CAP_PROP_POS_MSEC, t*1000)
            ok, frame = cap.read()
            if ok:
                samples += 1
                text, confidence = read_frame_subtitle(frame, language=language, region=region)
                if text:
                    observations.append((round(t,3),text,confidence))
            t += step
    finally:
        cap.release()

    runs = []
    for t,text,conf in observations:
        last = runs[-1] if runs else None
        if last and t - last['last'] < step*2.55 and (text == last['text'] or
            SequenceMatcher(None,text,last['text']).ratio() >= .82):
            last['last'] = t
            last['n'] += 1
            if conf > last['conf']:
                last['text'] = text; last['conf'] = conf
        else:
            runs.append({'first':t,'last':t,'text':text,'conf':conf,'n':1})

    cues = []
    for run in runs:
        if run['n'] < 2 and not (run['conf'] >= 85 and len(run['text']) >= 8):
            continue
        start = max(0, run['first'] - step/2)
        end = min(duration, run['last'] + step/2)
        if end > start:
            cues.append(VisualCue(round(start,3),round(end,3),run['text'],run['conf']))
    audit = {
        'ocr_engine':'tesseract', 'mode':'visible_frames_only',
        'speech_audio_used':False, 'sample_step_seconds':step,
        'region_ratio':[float(z) for z in region],
        'frames_sampled':samples,'raw_text_observations':len(observations),
        'confirmed_visible_subtitle_cues':len(cues),
        'status':'captions_detected_needs_review' if cues else 'no_reliable_visible_subtitles',
        'note':'OCR仅来自视频画面，时间轴为屏幕可见时间，非原声词级时间戳。须逐帧校对，纯口播且无画面字幕无法恢复台词。'
    }
    return cues,audit
