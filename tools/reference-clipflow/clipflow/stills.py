"""Select a clear reference opening frame, then draw its video-matching C number.

Frame selection samples the ORIGINAL reference MP4 to avoid compression artifacts
and pre-existing added watermarks from the re-encoded numbered segment. The
selected frame is left at original resolution; only the same sequence overlay
as the numbered MP4 is added. Existing subtitles and picture are preserved.
Selection prioritizes the fewest recognized original-frame characters among the
first ten decoded frames; dark/flash/unusable frames are discarded first.
OCR confidence is an estimate, not a visual proof of zero text.
"""
from __future__ import annotations

import math
from pathlib import Path
import subprocess

from .still_text import count_visible_text, ocr_language


def _frame_score(frame, previous=None) -> tuple[bool, float]:
    """Prefer exposed, sharp, stable frames; exclude black/flash when possible."""
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    if h < 8 or w < 8:
        raise ValueError("视频帧太小，无法判断清晰度")
    scale = min(1.0, 360.0 / w, 480.0 / h)
    small = cv2.resize(frame, (max(8, round(w * scale)), max(8, round(h * scale))),
                       interpolation=cv2.INTER_AREA) if scale < 1 else frame
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    sh, sw = gray.shape
    # Reduce title / hard-subtitle bias: emphasize the central picture content.
    focus = gray[max(0, int(sh * .08)):max(1, int(sh * .76)),
                 max(0, int(sw * .08)):max(1, int(sw * .92))]
    if focus.size < 64:
        focus = gray
    sharp = float(cv2.Laplacian(focus, cv2.CV_64F).var())
    brightness = float(gray.mean())
    contrast = float(gray.std())
    low = float(np.mean(gray < 12))
    high = float(np.mean(gray > 244))
    exposure_bad = low + high
    stable_penalty = 0.0
    if previous is not None and previous.shape == gray.shape:
        stable_penalty = float(np.abs(gray.astype(np.int16) - previous.astype(np.int16)).mean())
    # Bad boundaries/flash frames can be technically sharp but unusable.
    plausible = 20 <= brightness <= 235 and exposure_bad < .82
    score = (2.6 * math.log1p(sharp) + 0.017 * contrast
             - 6.5 * exposure_bad - 0.016 * abs(brightness - 120.0)
             - 0.024 * stable_penalty)
    return plausible, score


def select_opening_frame(source: Path, start: float, end: float,
                         *, max_frames: int = 10,
                         include_details: bool = False):
    """Return (original BGR pixels, source-time, offset-in-clip, frame number).

    Samples only the first <=10 actual sequential decoded source frames.
    Black/flash frames are filtered first; then choose least OCR-visible text.
    Original picture has no added watermark during selection. Cannot guarantee
    open eyes or a particular mouth position.
    """
    import cv2

    if end <= start or start < 0:
        raise ValueError("无效片段起止时间")
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开原视频以提取截图: {source}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        if not math.isfinite(fps) or fps <= .1:
            raise RuntimeError("无法获得可靠的视频帧率，停止截图提取")
        duration_frames = max(1, int(round((end - start) * fps)))
        start_frame = max(0, math.ceil(start * fps - 1e-7))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total > 0 and start_frame >= total:
            raise RuntimeError(f"片段起点超出原片帧数: {start:.3f}s")
        if max_frames != 10:
            raise ValueError("每段只允许从前10帧选择截图")
        window_frames = min(10, duration_frames)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        candidates = []
        previous_gray = None
        for offset_frame in range(window_frames):
            ok, pixels = cap.read()
            if not ok or pixels is None:
                break
            # Frames are decoded sequentially, so selected images are sourced
            # only from the start of this real segment, not a random thumbnail.
            if (start_frame + offset_frame) / fps >= end - 1e-6:
                break
            valid, rank = _frame_score(pixels, previous_gray)
            candidates.append((valid, rank, offset_frame, pixels))
            sh, sw = pixels.shape[:2]
            scale = min(1.0, 360.0 / sw, 480.0 / sh)
            small = cv2.resize(pixels, (max(8, round(sw * scale)), max(8, round(sh * scale))),
                               interpolation=cv2.INTER_AREA) if scale < 1 else pixels
            previous_gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if not candidates:
            raise RuntimeError(f"未能解码片段开头画面：{start:.3f}—{end:.3f}s")
        usable = [q for q in candidates if q[0]]
        if not usable:
            raise RuntimeError("前10帧全部属于黑场、闪白或严重曝光异常，无法选有效截图")
        lang = ocr_language()  # fail clearly if Chinese OCR is not installed
        rankings = []
        for valid, rank, relative, pixels in usable:
            count, coverage = count_visible_text(pixels, language=lang)
            rankings.append((count, coverage, -rank, relative, pixels))
        count, coverage, _, relative, frame = min(rankings,
                                key=lambda q:(q[0],q[1],q[2],q[3]))
        selection = {
            "selected_relative_frame": relative,
            "visible_text_characters": count,
            "visible_text_area_ratio": coverage,
            "ocr_language": lang,
            "frames_examined": len(candidates),
            "usable_frames": len(usable),
            "selection_policy": "fewest_OCR_characters_then_area_then_clarity_first_10_frames",
        }
        global_index = start_frame + relative
        stamp = global_index / fps
        result = (frame, stamp, max(0.0, stamp - start), global_index)
        return result + (selection,) if include_details else result
    finally:
        cap.release()


def export_segment_still(source: Path, start: float, end: float,
                         target: Path, *, number: int,
                         watermark_filter: str) -> dict:
    """Write an original-size JPEG with the *same* C-style number as its MP4.

    ``watermark_filter`` must be produced with cli.drawtext_filter(number,...)
    (the same filter used for the video). FFmpeg overlays the number on the
    actually selected decoded opening frame, not on a separate/exact-cut seek.
    An overlay failure is fatal: never deliver an unnumbered JPEG as success.
    """
    import cv2

    if type(number) is not int or not (1 <= number <= 999):
        raise ValueError("截图编号必须是001至999的正整数")
    if not watermark_filter or "drawtext=" not in watermark_filter:
        raise ValueError("截图缺少与视频相同的C方案序号滤镜")
    frame, stamp, offset, frame_index, selection = select_opening_frame(
        source, start, end, include_details=True)
    height, width = frame.shape[:2]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    try:
        proc = subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pixel_format", "bgr24",
            "-video_size", f"{width}x{height}", "-framerate", "1", "-i", "pipe:0",
            "-vf", watermark_filter, "-frames:v", "1",
            "-q:v", "2", "-f", "image2", "-update", "1", str(target)
        ], input=frame.tobytes(), capture_output=True, timeout=60, check=False)
        if proc.returncode != 0 or not target.is_file() or target.stat().st_size <= 0:
            raise RuntimeError("分段截图序号叠加失败：" + proc.stderr.decode("utf-8", "replace")[-400:])
        rendered = cv2.imread(str(target))
        if rendered is None or rendered.shape[:2] != (height, width):
            raise RuntimeError("分段截图分辨率或解码校验失败")
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {"still_image": f"segment_stills/{target.name}",
            "still_source_time_seconds": round(stamp, 3),
            "still_offset_seconds": round(offset, 3),
            "still_source_frame_index": frame_index,
            "still_offset_frame_index": selection["selected_relative_frame"],
            "still_sequence_number": f"{number:03d}",
            "still_text_characters": selection["visible_text_characters"],
            "still_text_area_ratio": selection["visible_text_area_ratio"],
            "still_ocr_language": selection["ocr_language"],
            "still_candidate_frames": selection["frames_examined"],
            "still_usable_frames": selection["usable_frames"],
            "still_selection_policy": selection["selection_policy"],
            "still_watermark_scheme": "C",
            "still_has_sequence_watermark": True,
            "still_source": "original_video_opening_frame_with_clipflow_C_sequence_overlay"}
