"""Opening stills must carry matching C-scheme sequence numbers."""
from __future__ import annotations
import math
from pathlib import Path
import cv2
import numpy as np
import pytest
from clipflow.stills import _frame_score, select_opening_frame, export_segment_still
from clipflow.cli import drawtext_filter, ffmpeg_font


def test_reject_flash_and_blurry_frames():
    black = np.zeros((144, 256, 3), np.uint8)
    white = np.full_like(black, 255)
    rng = np.random.default_rng(44)
    clean = rng.integers(35, 210, (144, 256, 3),dtype=np.uint8)
    blurred = cv2.GaussianBlur(clean, (23, 23), 0)
    ok_black, _ = _frame_score(black)
    ok_white, _ = _frame_score(white)
    ok_clean, sharp = _frame_score(clean)
    ok_blur, blurry = _frame_score(blurred)
    assert not ok_black and not ok_white
    assert ok_clean and ok_blur
    assert sharp > blurry


def test_opening_selection_then_overlays_matching_C_sequence_number(tmp_path: Path):
    path = tmp_path/"reference.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 12, (256, 144))
    assert writer.isOpened()
    random = np.random.default_rng(42)
    clear = random.integers(40, 205, (144,256,3),dtype=np.uint8)
    for idx in range(24):
        if idx==0:
            frame = np.zeros_like(clear)
        elif idx==1:
            frame = np.full_like(clear, 255)
        elif idx==2:
            frame = cv2.GaussianBlur(clear, (29,29), 0)
        else:
            frame=clear
        writer.write(frame)
    writer.release()
    frame, stamp, offset, frame_number = select_opening_frame(path,0.,2.)
    assert frame.shape[:2] == (144,256)
    assert 0.0 <= stamp <= .6
    assert frame_number >= 3
    assert not np.all(frame==0)
    target = tmp_path/"001_镜头.jpg"
    meta={"width":256,"height":144}
    font=ffmpeg_font()
    info = export_segment_still(path,0,2,target,number=1,
                                watermark_filter=drawtext_filter(1,meta,font))
    assert target.is_file() and target.stat().st_size>500
    assert info["still_image"] == "segment_stills/001_镜头.jpg"
    assert info["still_source"] == "original_video_opening_frame_with_clipflow_C_sequence_overlay"
    assert info["still_sequence_number"] == "001"
    assert info["still_watermark_scheme"] == "C"
    assert info["still_has_sequence_watermark"] is True
    assert info["still_offset_seconds"] <= .6
    jpg=cv2.imread(str(target))
    assert jpg.shape[:2] == frame.shape[:2]
    # The top left has an added number; the image away from it remains unmodified.
    number_roi = cv2.absdiff(jpg[:85,:120], frame[:85,:120])
    untouched_roi = cv2.absdiff(jpg[-44:,-96:], frame[-44:,-96:])
    assert number_roi.mean() > untouched_roi.mean() * 1.5 + 3
    second = tmp_path/"002_镜头.jpg"
    info2 = export_segment_still(path,0,2,second,number=2,
                                 watermark_filter=drawtext_filter(2,meta,font))
    assert info2["still_sequence_number"] == "002"
    second_jpg = cv2.imread(str(second))
    assert cv2.absdiff(jpg[:65,:95],second_jpg[:65,:95]).mean() > 2.0
    assert cv2.absdiff(jpg[-44:,-96:],second_jpg[-44:,-96:]).mean() < 3.0


def test_invalid_interval_rejected(tmp_path:Path):
    with pytest.raises(ValueError):
        select_opening_frame(tmp_path/"none.mp4",4.0,3.0)
