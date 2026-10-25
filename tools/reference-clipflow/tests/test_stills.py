"""Still extraction: opening-only, original dimensions and no added watermark."""
from __future__ import annotations
import math
from pathlib import Path
import cv2
import numpy as np
import pytest
from clipflow.stills import _frame_score, select_opening_frame, export_segment_still


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


def test_opening_selection_is_original_without_sequence_watermark(tmp_path: Path):
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
    info = export_segment_still(path,0,2,target)
    assert target.is_file() and target.stat().st_size>500
    assert info["still_image"] == "segment_stills/001_镜头.jpg"
    assert info["still_source"] == "original_video_without_added_sequence_watermark"
    assert info["still_offset_seconds"] <= .6
    jpg=cv2.imread(str(target))
    assert jpg.shape[:2] == frame.shape[:2]


def test_invalid_interval_rejected(tmp_path:Path):
    with pytest.raises(ValueError):
        select_opening_frame(tmp_path/"none.mp4",4.0,3.0)
