"""Pick one clear, unmodified reference frame from each segment's opening frames.

The image is taken from the ORIGINAL reference MP4 rather than the numbered
re-encode, so it does not contain ClipFlow's added sequence watermark.  Original
hard-coded subtitles/visual elements remain.  This is a technical ranking of
sharpness, exposure and rapid changes, not an infallible judgment of facial
expression or photographic aesthetics.
"""
from __future__ import annotations

import math
from pathlib import Path


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
                         *, max_window_seconds: float = .6,
                         max_frames: int = 20):
    """Return (original BGR pixels, source-time, offset-in-clip, frame number).

    Samples the first <=0.6 seconds / <=20 source frames (whichever is smaller).
    Each candidate is an actual decoded original frame with no enhancement or
    content edits. Cannot guarantee open eyes or a particular mouth position.
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
        window_frames = max(1, min(max_frames,
                                   math.ceil(max_window_seconds * fps),
                                   duration_frames))
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
        # Among equally clean shots, prefer frames closer to the segment start.
        valid, rank, relative, frame = max(candidates,
                                           key=lambda q: (int(q[0]), q[1], -q[2]))
        global_index = start_frame + relative
        stamp = global_index / fps
        return frame, stamp, max(0.0, stamp - start), global_index
    finally:
        cap.release()


def export_segment_still(source: Path, start: float, end: float,
                         target: Path) -> dict:
    """Write original-resolution JPEG, return auditable selection metadata."""
    import cv2

    frame, stamp, offset, frame_index = select_opening_frame(source, start, end)
    target.parent.mkdir(parents=True, exist_ok=True)
    params = [cv2.IMWRITE_JPEG_QUALITY, 94]
    if hasattr(cv2, "IMWRITE_JPEG_OPTIMIZE"):
        params += [cv2.IMWRITE_JPEG_OPTIMIZE, 1]
    if not cv2.imwrite(str(target), frame, params):
        raise RuntimeError(f"无法写出分段截图：{target}")
    if not target.is_file() or target.stat().st_size <= 0:
        raise RuntimeError(f"截图为空：{target}")
    return {"still_image": f"segment_stills/{target.name}",
            "still_source_time_seconds": round(stamp, 3),
            "still_offset_seconds": round(offset, 3),
            "still_source_frame_index": frame_index,
            "still_source": "original_video_without_added_sequence_watermark"}
