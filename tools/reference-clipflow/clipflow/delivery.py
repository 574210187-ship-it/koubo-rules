"""Final three-file delivery packaging for Reference ClipFlow.

The two archives deliberately separate customer-facing media from audit and
editing support files.  ``文案.txt`` stays outside both archives.
"""
from __future__ import annotations

import json
from pathlib import Path
import zipfile


MIN_SECONDS_EXCLUSIVE = 3.0
MAX_SECONDS_INCLUSIVE = 8.0
STILL_POLICY = "fewest_OCR_characters_then_area_then_clarity_first_10_frames"


def _require_file(path: Path, label: str) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"交付文件不存在或为空: {label}")


def _validate_plain_script(path: Path) -> None:
    _require_file(path, "文案.txt")
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise RuntimeError("文案.txt必须是UTF-8无BOM")
    text = raw.decode("utf-8")
    lines = text.splitlines()
    if not lines or any(not line.strip() for line in lines):
        raise RuntimeError("文案.txt必须逐行纯文字，不能含空行")
    if "\x00" in text:
        raise RuntimeError("文案.txt包含非法NUL字符")


def _validate_entry_contract(entries: list[dict]) -> None:
    if not entries:
        raise RuntimeError("没有拆分片段，不能生成最终交付")
    if [int(row["index"]) for row in entries] != list(range(1, len(entries) + 1)):
        raise RuntimeError("片段编号不连续，不能交付")
    for row in entries:
        number = f"{int(row['index']):03d}"
        duration = float(row["end"]) - float(row["start"])
        encoded = float(row.get("encoded_duration", duration))
        if not (MIN_SECONDS_EXCLUSIVE < duration <= MAX_SECONDS_INCLUSIVE + 1e-8
                and MIN_SECONDS_EXCLUSIVE < encoded <= MAX_SECONDS_INCLUSIVE + 1e-4):
            raise RuntimeError(f"第{number}段时长不在(3,8]秒内，禁止交付")
        filename = str(row["file"])
        if Path(filename).name != filename or not filename.lower().endswith(".mp4"):
            raise RuntimeError(f"不安全的片段文件名: {filename!r}")
        expected_still = "segment_stills/" + Path(filename).stem + ".jpg"
        if row.get("still_image") != expected_still:
            raise RuntimeError(f"截图文件与视频编号不一致: {filename}")
        if not (1 <= int(row.get("still_candidate_frames", 0)) <= 10
                and 0 <= int(row.get("still_offset_frame_index", -1)) < 10
                and row.get("still_selection_policy") == STILL_POLICY):
            raise RuntimeError("截图未验证前10帧最少OCR文字规则，拒绝交付")
        if (row.get("still_sequence_number") != number
                or row.get("still_watermark_scheme") != "C"
                or row.get("still_has_sequence_watermark") is not True):
            raise RuntimeError(f"第{number}段截图缺少对应序号水印验证记录，拒绝交付")


def _write_and_verify_archive(destination: Path, members: dict[str, Path]) -> Path:
    partial = destination.with_name("." + destination.name + ".partial")
    try:
        with zipfile.ZipFile(partial, "w", allowZip64=True) as archive:
            for name in sorted(members):
                path = members[name]
                compression = (zipfile.ZIP_STORED if path.suffix.lower() in {".mp4", ".jpg", ".png"}
                               else zipfile.ZIP_DEFLATED)
                archive.write(path, arcname=name, compress_type=compression)
        if not zipfile.is_zipfile(partial):
            raise RuntimeError(f"{destination.name}格式校验失败")
        with zipfile.ZipFile(partial, "r") as archive:
            names = archive.namelist()
            if len(names) != len(members) or set(names) != set(members):
                raise RuntimeError(f"{destination.name}成员清单与实际文件不一致")
            if "文案.txt" in {Path(name).name for name in names}:
                raise RuntimeError("文案.txt必须独立交付，禁止放入ZIP")
            corrupt = archive.testzip()
            if corrupt:
                raise RuntimeError(f"{destination.name}内部成员校验失败: {corrupt}")
            for name, path in members.items():
                if archive.getinfo(name).file_size != path.stat().st_size:
                    raise RuntimeError(f"{destination.name}内部文件长度不一致: {name}")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def build_final_delivery_packages(out: Path, entries: list[dict]) -> tuple[Path, Path, Path]:
    """Build exactly two ZIPs and one standalone pure-text TXT.

    ``videos_and_screenshots.zip`` contains only numbered MP4s and their
    matching JPGs.  ``supporting_materials.zip`` contains all non-media
    delivery evidence.  The returned ``文案.txt`` remains outside both ZIPs.
    """
    _validate_entry_contract(entries)
    plain_script = out / "文案.txt"
    _validate_plain_script(plain_script)

    media: dict[str, Path] = {}
    for row in entries:
        filename = str(row["file"])
        media["segments/" + filename] = out / "segments" / filename
        media[str(row["still_image"])] = out / str(row["still_image"])

    required_support = [
        "captions.srt",
        "segments_transcript.md",
        "manifest.json",
        "segments_list.csv",
        "subtitle_style_profile.json",
    ]
    support = {name: out / name for name in required_support}
    samples = sorted(path for path in (out / "subtitle_samples").glob("*") if path.is_file())
    if not any(path.name == "subtitle_reference_contact.jpg" for path in samples):
        raise RuntimeError("缺少对标字幕样张总览，拒绝交付")
    if not any(path.name.startswith("cue_") and path.suffix.lower() == ".jpg" for path in samples):
        raise RuntimeError("缺少原分辨率字幕样张，拒绝交付")
    support.update({"subtitle_samples/" + path.name: path for path in samples})

    for name, path in {**media, **support}.items():
        _require_file(path, name)

    srt = (out / "captions.srt").read_text("utf-8-sig")
    if not srt.strip():
        raise RuntimeError("交付SRT为空，拒绝交付")
    transcript = (out / "segments_transcript.md").read_text("utf-8")
    for row in entries:
        if f"### 第{int(row['index']):03d}段｜" not in transcript:
            raise RuntimeError(f"台词MD缺少第{int(row['index']):03d}段")

    manifest = json.loads((out / "manifest.json").read_text("utf-8"))
    if len(manifest.get("segments", [])) != len(entries):
        raise RuntimeError("manifest切分清单与片段数量不一致")
    for row in manifest["segments"]:
        expected = "segment_stills/" + Path(str(row["file"])).stem + ".jpg"
        if row.get("still_image") != expected:
            raise RuntimeError("manifest内截图与MP4编号无法一一对应")

    media_zip = _write_and_verify_archive(out / "videos_and_screenshots.zip", media)
    support_zip = _write_and_verify_archive(out / "supporting_materials.zip", support)
    return media_zip, support_zip, plain_script
