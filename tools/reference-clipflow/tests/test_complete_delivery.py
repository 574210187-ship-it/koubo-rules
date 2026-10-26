"""First-stage complete ZIP delivery contract; no internet or Whisper model required."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

import cv2
import numpy as np

import pytest

from clipflow.cli import build_complete_delivery_zip, main
from clipflow.transcript import write_segment_document


def test_md_only_one_time_window_per_segment(tmp_path: Path):
    entries = [
        {"index": 1, "file": "001_镜头.mp4", "start": 0., "end": 5.2},
        {"index": 2, "file": "002_镜头.mp4", "start": 5.2, "end": 9.0},
    ]
    path = tmp_path / "segments_transcript.md"
    write_segment_document(path, "原片.mp4", 9.0, entries,
                           ["大家好，我是律师。", "合同纠纷，可以来问我。"],
                           "cloud_whisper_asr", "cloud_word_timestamps", "small")
    md = path.read_text("utf-8")
    headers = re.findall(r"^### 第\d{3}段｜.*$", md, re.M)
    assert len(headers) == 2
    assert "### 第001段｜00:00.000—00:05.200｜5.200 秒" in md
    assert "### 第002段｜00:05.200—00:09.000｜3.800 秒" in md
    assert md.count("**台词：**") == 2
    assert "大家好，我是律师。" in md
    assert "合同纠纷，可以来问我。" in md
    assert "已授权的云端 Whisper ASR" in md
    assert "00:01.000—" not in md  # sentences don't get individual timecodes


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="FFmpeg and FFprobe required")
def test_reference_srt_delivers_complete_zip(tmp_path: Path):
    source = tmp_path/"original.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=navy:s=160x288:r=12:d=3.4",
                    "-f", "lavfi", "-i", "sine=frequency=620:sample_rate=16000:duration=3.4",
                    "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(source)], check=True)
    srt = tmp_path/"subtitle.srt"
    srt.write_text("1\n00:00:00,200 --> 00:00:01,100\n大家好，我是律师。\n\n"
                   "2\n00:00:01,300 --> 00:00:03,200\n遇到合同纠纷，可以找我。\n", encoding="utf-8")
    out = tmp_path/"output"
    assert main(["reference", "--input", str(source), "--out", str(out),
                 "--srt", str(srt), "--max-seconds", "1.7", "--preset", "ultrafast"]) == 0
    delivery = out/"ClipFlow_完整交付.zip"
    assert delivery.is_file() and delivery.stat().st_size > 5000
    assert zipfile.is_zipfile(delivery)
    with zipfile.ZipFile(delivery) as z:
        assert z.testzip() is None
        names = set(z.namelist())
        required = {"captions.srt", "segments_transcript.md", "manifest.json",
                    "segments_list.csv", "subtitle_style_profile.json",
                    "subtitle_samples/subtitle_reference_contact.jpg",
                    "subtitle_samples/sample_index.json"}
        assert required <= names
        clips = sorted(x for x in names if x.startswith("segments/") and x.endswith(".mp4"))
        stills = sorted(x for x in names if x.startswith("segment_stills/") and x.endswith(".jpg"))
        assert len(stills) == len(clips)
        assert [Path(x).stem for x in stills] == [Path(x).stem for x in clips]
        assert len(clips) >= 2
        assert len(clips) == len(list((out/"segments").glob("*.mp4")))
        assert any(x.startswith("subtitle_samples/cue_") for x in names)
        delivered_srt = z.read("captions.srt").decode("utf-8-sig")
        assert "大家好，我是律师\n" in delivered_srt
        assert "遇到合同纠纷，可以找我\n" in delivered_srt
        assert "大家好，我是律师。" not in delivered_srt
        assert "遇到合同纠纷，可以找我。" not in delivered_srt
        assert z.read("captions.srt") == (out/"captions.srt").read_bytes()
        script = z.read("segments_transcript.md").decode("utf-8")
        assert script.count("**台词：**") == len(clips)
        assert "大家好，我是律师。" in script  # MD keeps original words and punctuation
        assert script.count("### 第") == len(clips)
        data = json.loads(z.read("manifest.json"))
        assert data["version"] == "0.4.4"
        assert data["caption_source"] == "supplied_srt"
        assert len(data["segments"]) == len(clips)
        assert all(x["duration"] <= 1.7 for x in data["segments"])
        for segment in data["segments"]:
            name = "segment_stills/" + Path(segment["file"]).stem + ".jpg"
            assert segment["still_image"] == name
            assert segment["still_sequence_number"] == f"{segment['index']:03d}"
            assert segment["still_watermark_scheme"] == "C"
            assert segment["still_has_sequence_watermark"] is True
            assert segment["still_offset_seconds"] <= .6 + .002
            assert segment["start"] <= segment["still_source_time_seconds"] < segment["end"]
            encoded = np.frombuffer(z.read(name), dtype=np.uint8)
            decoded_still = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            assert decoded_still is not None and decoded_still.shape[:2] == (288,160)
        decoded = z.read("segments_list.csv").decode("utf-8-sig").splitlines()
        rows = list(csv.reader(decoded))
        assert len(rows) == len(clips)+1
        assert rows[0][-1] == "截图文件"
        assert [row[-1] for row in rows[1:]] == stills
        assert "00:00:00,200" in z.read("captions.srt").decode("utf-8-sig")
    # Existing compatibility artifacts are still available but not the primary download.
    assert (out/"numbered_segments.zip").is_file()
    assert (out/"subtitle_reference_stylekit.zip").is_file()


def test_missing_required_sample_fails_without_partial_zip(tmp_path: Path):
    files = ["captions.srt", "segments_transcript.md", "manifest.json",
             "segments_list.csv", "subtitle_style_profile.json"]
    for name in files:
        (tmp_path/name).write_text("content", encoding="utf-8")
    (tmp_path/"segments_transcript.md").write_text("### 第001段｜00:00.000—00:01.000｜1.000 秒\n**台词：** 大家好", encoding="utf-8")
    (tmp_path/"manifest.json").write_text('{"segments":[{"index":1}]}', encoding="utf-8")
    (tmp_path/"segments").mkdir()
    (tmp_path/"segments/001_镜头.mp4").write_bytes(b"video")
    (tmp_path/"subtitle_samples").mkdir()
    with pytest.raises(RuntimeError, match="缺少对标字幕样张总览"):
        build_complete_delivery_zip(tmp_path, [{"index":1,"file":"001_镜头.mp4", "start":0,"end":1}])
    assert not (tmp_path/"ClipFlow_完整交付.zip").exists()
    assert not (tmp_path/".ClipFlow_完整交付.zip.partial").exists()


def test_missing_single_still_blocks_delivery(tmp_path: Path):
    """A JPEG is mandatory for every MP4, not a best-effort extra."""
    folder = tmp_path
    for name in ("captions.srt", "segments_transcript.md", "manifest.json",
                 "segments_list.csv", "subtitle_style_profile.json"):
        (folder/name).write_text("ready", encoding="utf-8")
    (folder/"segments_transcript.md").write_text("### 第001段｜00:00.000—00:01.000｜1.000 秒\n**台词：** 你好",encoding="utf-8")
    (folder/"segments").mkdir()
    (folder/"segments/001_镜头.mp4").write_bytes(b"valid-bytes-for-test")
    (folder/"subtitle_samples").mkdir()
    (folder/"subtitle_samples/subtitle_reference_contact.jpg").write_bytes(b"contact")
    (folder/"subtitle_samples/cue_001_test.jpg").write_bytes(b"frame")
    (folder/"manifest.json").write_text('{"segments":[{"index":1,"file":"001_镜头.mp4","still_image":"segment_stills/001_镜头.jpg"}]}',encoding="utf-8")
    entries = [{"index":1,"file":"001_镜头.mp4", "start":0., "end":1., "still_image":"segment_stills/001_镜头.jpg"}]
    with pytest.raises(RuntimeError, match="交付文件不存在或为空"):
        build_complete_delivery_zip(folder,entries)
    assert not (folder/"ClipFlow_完整交付.zip").exists()


def test_mismatched_still_number_blocks_delivery(tmp_path: Path):
    """Even a nonempty JPG must be rejected if its sequence watermark disagrees."""
    root = tmp_path
    for name in ("captions.srt", "segments_transcript.md", "manifest.json",
                 "segments_list.csv", "subtitle_style_profile.json"):
        (root/name).write_text("ready", encoding="utf-8")
    (root/"segments_transcript.md").write_text(
        "### 第001段｜00:00.000—00:01.000｜1.000 秒\n**台词：** 你好", encoding="utf-8")
    (root/"segments").mkdir()
    (root/"segments/001_镜头.mp4").write_bytes(b"fake-video-for-unit-test")
    (root/"segment_stills").mkdir()
    (root/"segment_stills/001_镜头.jpg").write_bytes(b"fake-image-for-unit-test")
    (root/"subtitle_samples").mkdir()
    (root/"subtitle_samples/subtitle_reference_contact.jpg").write_bytes(b"contact")
    (root/"subtitle_samples/cue_001_mock.jpg").write_bytes(b"cue")
    entry = {"index":1,"file":"001_镜头.mp4", "start":0., "end":1.,
             "still_image":"segment_stills/001_镜头.jpg",
             "still_sequence_number":"002", "still_watermark_scheme":"C",
             "still_has_sequence_watermark":True}
    (root/"manifest.json").write_text(json.dumps({"segments":[entry]}), encoding="utf-8")
    with pytest.raises(RuntimeError,match="截图缺少对应序号水印验证记录"):
        build_complete_delivery_zip(root,[entry])
    assert not (root/"ClipFlow_完整交付.zip").exists()
