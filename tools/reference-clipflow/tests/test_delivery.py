import json
from pathlib import Path
import zipfile

import pytest

from clipflow.delivery import build_final_delivery_packages


def _file(path: Path, data: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _entry(index: int = 1) -> dict:
    return {
        "index": index,
        "file": f"{index:03d}_镜头.mp4",
        "start": 0.0,
        "end": 4.0,
        "encoded_duration": 4.0,
        "still_image": f"segment_stills/{index:03d}_镜头.jpg",
        "still_candidate_frames": 10,
        "still_offset_frame_index": 0,
        "still_selection_policy": "fewest_OCR_characters_then_area_then_clarity_first_10_frames",
        "still_sequence_number": f"{index:03d}",
        "still_watermark_scheme": "C",
        "still_has_sequence_watermark": True,
    }


def _valid_out(tmp_path: Path) -> list[dict]:
    entry = _entry()
    _file(tmp_path / "segments" / entry["file"], b"fake-mp4")
    _file(tmp_path / entry["still_image"], b"fake-jpg")
    _file(tmp_path / "captions.srt", "1\n00:00:00,000 --> 00:00:04,000\n你好\n".encode("utf-8-sig"))
    (tmp_path / "segments_transcript.md").write_text("### 第001段｜00:00.000—00:04.000｜4.000秒\n你好\n", encoding="utf-8")
    (tmp_path / "segments_list.csv").write_text("编号\n001\n", encoding="utf-8")
    (tmp_path / "subtitle_style_profile.json").write_text("{}", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"segments": [entry]}, ensure_ascii=False), encoding="utf-8")
    _file(tmp_path / "subtitle_samples" / "subtitle_reference_contact.jpg", b"contact")
    _file(tmp_path / "subtitle_samples" / "cue_001.jpg", b"cue")
    (tmp_path / "文案.txt").write_text("你好\n", encoding="utf-8")
    return [entry]


def test_builds_exactly_two_archives_and_one_standalone_txt(tmp_path: Path) -> None:
    entries = _valid_out(tmp_path)
    media_zip, support_zip, script = build_final_delivery_packages(tmp_path, entries)

    assert [path.name for path in (media_zip, support_zip, script)] == [
        "videos_and_screenshot.zip", "supporting_materials.zip", "文案.txt"
    ]
    with zipfile.ZipFile(media_zip) as archive:
        assert set(archive.namelist()) == {"segments/001_镜头.mp4", "segment_stills/001_镜头.jpg"}
    with zipfile.ZipFile(support_zip) as archive:
        assert "captions.srt" in archive.namelist()
        assert "segments/001_镜头.mp4" not in archive.namelist()
        assert "文案.txt" not in archive.namelist()


def test_rejects_eight_seconds_or_less_segment(tmp_path: Path) -> None:
    entries = _valid_out(tmp_path)
    entries[0]["end"] = 3.0
    with pytest.raises(RuntimeError, match="时长"):
        build_final_delivery_packages(tmp_path, entries)


def test_rejects_plain_text_inside_archives_by_contract(tmp_path: Path) -> None:
    entries = _valid_out(tmp_path)
    _, _, script = build_final_delivery_packages(tmp_path, entries)
    assert script.read_text(encoding="utf-8") == "你好\n"
