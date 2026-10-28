"""Reference ClipFlow: deterministic, portable FFmpeg video workflow.

Use `clipflow --help`, `clipflow reference --help`, and
`clipflow assemble --help`. Does not upload user media to any service.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable

from .subtitle_style import (create_reference_samples, create_style_template,
                             read_style_profile, convert_matched_ass)
from .asr import TimedText, recognize, estimate_character_timing
from .cut_planner import (plan_sentence_cuts, verified_sentence_ends,
                          NoFeasibleSegmentation, MIN_SECONDS_EXCLUSIVE,
                          MAX_SECONDS_INCLUSIVE)
from .transcript import (assign_words_to_segments, write_segment_document,
                         write_whole_transcript, human_time)
from .stills import export_segment_still


def require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"缺少 {name}，请先安装 FFmpeg（ffmpeg 和 ffprobe）。")


def command(args: list[str], *, text: bool = True) -> str:
    result = subprocess.run(args, capture_output=True, text=text)
    if result.returncode:
        err = result.stderr[-2500:] if text else "非文本命令失败"
        raise RuntimeError(f"命令失败: {' '.join(map(str, args[:10]))}\n{err}")
    return result.stdout if text else ""


def media_info(path: Path) -> dict:
    require_binary("ffprobe")
    result = json.loads(command([
        "ffprobe", "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(path)
    ]))
    videos = [s for s in result["streams"] if s["codec_type"] == "video"]
    audios = [s for s in result["streams"] if s["codec_type"] == "audio"]
    if not videos:
        raise ValueError(f"无视频流: {path}")
    v = videos[0]
    dur = float(result.get("format", {}).get("duration") or v.get("duration") or 0)
    if dur <= 0:
        raise ValueError(f"无法读取视频时长: {path}")
    rate = v.get("avg_frame_rate", "0/0")
    try:
        fps = float(Fraction(rate))
    except (ZeroDivisionError, ValueError):
        fps = 0.0
    return {"duration": dur, "width": int(v["width"]),
            "height": int(v["height"]), "fps": fps,
            "vcodec": v.get("codec_name"), "acodec": audios[0].get("codec_name") if audios else None,
            "has_audio": bool(audios)}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class Caption:
    start: float
    end: float
    text: str


def clock(t: float) -> str:
    millis = max(0, round(t * 1000))
    h, rem = divmod(millis, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def seconds(s: str) -> float:
    match = re.match(r"^(\d+):(\d\d):(\d\d)[,.](\d{1,3})$", s.strip())
    if not match:
        raise ValueError(f"无效SRT时间: {s}")
    h, m, sec, ms = match.groups()
    return int(h)*3600 + int(m)*60 + int(sec) + int(ms.ljust(3,"0"))/1000


def load_srt(path: Path) -> list[Caption]:
    content = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    out = []
    for block in re.split(r"\n\s*\n", content.strip()):
        ls = [x.strip() for x in block.splitlines() if x.strip()]
        ix = next((i for i, s in enumerate(ls) if "-->" in s), -1)
        if ix < 0:
            continue
        start, end = ls[ix].split("-->", 1)
        content_text = " ".join(ls[ix+1:]).strip()
        if content_text:
            out.append(Caption(seconds(start), seconds(end), content_text))
    out.sort(key=lambda x: x.start)
    if not out:
        raise ValueError(f"SRT没有有效字幕: {path}")
    if any(c.start >= c.end for c in out):
        raise ValueError("SRT起止时间异常")
    return out


def srt_without_terminal_punctuation(text: str) -> str:
    """Remove punctuation at the end of EACH displayed subtitle line.

    Operates only on exported SRT text, not the ASR result or per-segment MD.
    Keep commas and punctuation within a line; retain numbers/decimals and
    original cue timings. Unicode punctuation includes Chinese/ASCII marks,
    repeated ellipses and closing quotes. Wave dashes are also end markers.
    """
    cleaned: list[str] = []
    for line in text.splitlines():
        line = line.rstrip()
        while line and (unicodedata.category(line[-1]).startswith("P")
                        or line[-1] in "~～"):
            line = line[:-1].rstrip()
        if line:
            cleaned.append(line)
    return "\n".join(cleaned).strip()


def write_plain_script_txt(captions: Iterable[Caption], path: Path) -> None:
    """Export only spoken text to a standalone UTF-8 TXT, without metadata.

    Retains the original transcription punctuation (SRT display cleanup is a
    separate rule). Each source transcript cue becomes one plain-text line.
    No numbering, timestamps, filename, title, or Markdown formatting.
    """
    lines: list[str] = []
    for caption in captions:
        spoken = " ".join(line.strip() for line in caption.text.splitlines()
                          if line.strip())
        if spoken:
            lines.append(spoken)
    if not lines:
        raise ValueError("没有可信台词，不能写出空白文案TXT")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_srt(captions: Iterable[Caption], path: Path) -> None:
    """Export UTF-8 BOM SRT without sentence-ending punctuation in cues."""
    prepared = [(c, srt_without_terminal_punctuation(c.text)) for c in captions]
    prepared = [(c, text) for c, text in prepared if text]
    if not prepared:
        raise ValueError("没有有效字幕可写出（句末标点清理后为空）")
    path.write_text("\n".join(
        f"{i}\n{clock(c.start)} --> {clock(c.end)}\n{text}\n"
        for i, (c, text) in enumerate(prepared, 1)), encoding="utf-8-sig")


def validate_srt_export_punctuation(srt_text: str) -> None:
    """Reject a delivery SRT with punctuation at the end of a subtitle line."""
    cue_count = 0
    for block in re.split(r"\n\s*\n", srt_text.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timestamp = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timestamp < 0 or timestamp + 1 >= len(lines):
            raise RuntimeError("交付SRT包含无效或空白字幕块")
        for line in lines[timestamp+1:]:
            if line != srt_without_terminal_punctuation(line):
                raise RuntimeError("交付SRT字幕行结尾存在标点符号，拒绝交付")
        cue_count += 1
    if cue_count == 0:
        raise RuntimeError("交付SRT为空，拒绝交付")


def chunks_by_char(text: str, start: float, end: float, max_chars: int = 16) -> list[Caption]:
    """Fallback for ASR spans without word timing; boundaries are approximate."""
    parts = re.findall(r"[^，。！？；;!?]+[，。！？；;!?]?", text.strip()) or [text]
    tiny: list[str] = []
    for part in parts:
        while len(part) > max_chars:
            tiny.append(part[:max_chars]); part = part[max_chars:]
        if part:
            tiny.append(part)
    weights = [max(1, len(p.strip())) for p in tiny]
    total = sum(weights)
    pos = start
    out = []
    for n, (piece, weight) in enumerate(zip(tiny, weights)):
        nxt = end if n == len(tiny)-1 else pos + (end-start)*weight/total
        out.append(Caption(pos, nxt, piece.strip()))
        pos = nxt
    return out


def asr_captions(video: Path, model: str, device: str, language: str) -> list[Caption]:
    """Backwards-compatible entry point; audio recognition uses the ASR module."""
    recognition = recognize(video, model=model, device=device, language=language)
    return [Caption(x.start, x.end, x.text) for x in recognition.captions]


def detect_scenes(path: Path, duration: float, *, step: float=0.23,
                  min_spacing: float=0.7) -> list[float]:
    """Detect candidate visual scene cuts, not semantic actor/angle labels."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("镜头检测需要 numpy 和 opencv-python-headless。") from exc
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"无法解码视频: {path}")
    previous = None
    candidates = []
    try:
        for i in range(int(duration/step)+1):
            t = i*step
            cap.set(cv2.CAP_PROP_POS_MSEC, t*1000)
            ok, frame = cap.read()
            if not ok:
                continue
            small = cv2.resize(frame,(128,72), interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0,1], None, [24,16], [0,180,0,256])
            cv2.normalize(hist,hist,alpha=1,norm_type=cv2.NORM_L1)
            if previous is not None:
                ph,pf = previous
                hd = float(cv2.compareHist(ph,hist,cv2.HISTCMP_BHATTACHARYYA))
                mad = float(np.mean(np.abs(small.astype(np.int16)-pf.astype(np.int16))))
                if (hd >= 0.48 and mad >= 28.0) or (hd >= 0.38 and mad >= 55.0):
                    if not candidates or t-candidates[-1] >= min_spacing:
                        candidates.append(round(t,3))
            previous = (hist,small)
    finally:
        cap.release()
    return [t for t in candidates if 0.25 < t < duration-0.25]


def choose_cuts(duration: float, shots: list[float], captions: list[Caption],
                maximum: float=MAX_SECONDS_INCLUSIVE,
                snap_tolerance: float=1.0) -> list[float]:
    """Legacy entrypoint, now subject to the strict phrase/3–8s contract.

    snap_tolerance is retained only for backward API compatibility; nearest
    real scene changes are integrated in the global planner scoring function.
    """
    return plan_sentence_cuts(duration, shots, captions, maximum=maximum)


def ffmpeg_font(family: str="DejaVu Sans:style=Bold") -> str:
    try:
        match = command(["fc-match", "-f", "%{file}", family]).strip()
        if match and Path(match).exists():
            return match
    except (OSError, RuntimeError):
        pass
    raise RuntimeError("没有可用字体。Linux 请安装 fonts-dejavu-core / fonts-noto-cjk，或通过 --font-file 指定。")


def drawtext_filter(number: int, info: dict, font_file: str) -> str:
    w,h = info["width"], info["height"]
    landscape = w >= h
    size = max(32,round(260*w/1920))
    stroke = max(1,round((10 if landscape else 7)*w/(1920 if landscape else 1080)))
    x = round(44*w/1920) if landscape else round(27*w/1080)
    y = round(32*h/1080) if landscape else round(33*h/1920)
    ff_font = str(font_file).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return (f"drawtext=fontfile='{ff_font}':text='{number:03d}':"
            f"fontsize={size}:fontcolor=white@0.40:"
            f"bordercolor=black@0.80:borderw={stroke}:x={x}:y={y}")


def export_reference_segment(source: Path, target: Path,
                             start: float, end: float, info: dict, index: int,
                             font: str, crf: int, preset: str) -> None:
    require_binary("ffmpeg")
    vf = drawtext_filter(index,info,font)
    command(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", f"{start:.3f}", "-i", str(source),
             "-t", f"{end-start:.3f}",
             "-map", "0:v:0", "-map", "0:a:0?",
             "-vf", vf, "-c:v", "libx264", "-preset", preset,
             "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-b:a", "160k", "-movflags", "+faststart", str(target)])


def write_segment_list_csv(path: Path, entries: list[dict]) -> None:
    """Produce a simple importable segment inventory; never a second transcript."""
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["编号", "文件", "开始", "结束", "时长（秒）", "截图文件"])
        for segment in entries:
            start, end = float(segment["start"]), float(segment["end"])
            writer.writerow([f"{int(segment['index']):03d}", segment["file"],
                             human_time(start), human_time(end), f"{end-start:.3f}",
                             segment.get("still_image", "")])


def build_complete_delivery_zip(out: Path, entries: list[dict]) -> Path:
    """Single first-stage ZIP: video, one still per clip, SRT, MD, index, samples.

    Atomic output and real ZIP readback are mandatory. An output must not be
    reported to the user if one requested member is missing or unreadable.
    """
    if not entries:
        raise RuntimeError("没有拆分片段，不能生成完整交付ZIP")
    if [int(x["index"]) for x in entries] != list(range(1, len(entries)+1)):
        raise RuntimeError("片段编号不连续，不能交付")
    for row in entries:
        duration=float(row["end"])-float(row["start"])
        encoded=float(row.get("encoded_duration",duration))
        if not (MIN_SECONDS_EXCLUSIVE < duration <= MAX_SECONDS_INCLUSIVE + 1e-8
                and MIN_SECONDS_EXCLUSIVE < encoded <= MAX_SECONDS_INCLUSIVE + 1e-4):
            raise RuntimeError(f"第{int(row['index']):03d}段时长不在(3,8]秒内，禁止交付")
        if (row.get("still_candidate_frames",0)>10
                or row.get("still_selection_policy") !=
                "fewest_OCR_characters_then_area_then_clarity_first_10_frames"):
            raise RuntimeError("截图未验证前10帧最少OCR文字规则，拒绝交付")
    mandatory = ["captions.srt", "segments_transcript.md", "manifest.json",
                 "segments_list.csv", "subtitle_style_profile.json"]
    members: dict[str, Path] = {}
    for name in mandatory:
        members[name] = out/name
    for row in entries:
        filename = str(row["file"])
        if Path(filename).name != filename or not filename.lower().endswith(".mp4"):
            raise RuntimeError(f"不安全的片段文件名: {filename!r}")
        members["segments/" + filename] = out/"segments"/filename
    samples = sorted((out/"subtitle_samples").glob("*"))
    samples = [f for f in samples if f.is_file()]
    if not any(f.name == "subtitle_reference_contact.jpg" for f in samples):
        raise RuntimeError("缺少对标字幕样张总览，拒绝交付")
    if not any(f.name.startswith("cue_") and f.suffix.lower() == ".jpg" for f in samples):
        raise RuntimeError("缺少原分辨率字幕样张，拒绝交付")
    for sample in samples:
        members["subtitle_samples/"+sample.name] = sample
    for row in entries:
        still_name = "segment_stills/" + Path(str(row["file"])).stem + ".jpg"
        if row.get("still_image") != still_name:
            raise RuntimeError(f"截图文件与视频编号不一致: {row['file']}")
        members[still_name] = out/still_name
    for name, path in members.items():
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"交付文件不存在或为空: {name}")
    # The image must carry the same visible three-digit number as the MP4.
    # Check both in-memory segment metadata and the ZIP-embedded manifest.
    for row in entries:
        number = f"{int(row['index']):03d}"
        if (row.get("still_sequence_number") != number
                or row.get("still_watermark_scheme") != "C"
                or row.get("still_has_sequence_watermark") is not True):
            raise RuntimeError(f"第{number}段截图缺少对应序号水印验证记录，拒绝交付")
    validate_srt_export_punctuation((out/"captions.srt").read_text("utf-8-sig"))
    plain_text_file = out/"文案.txt"
    if not plain_text_file.is_file() or not plain_text_file.read_text("utf-8").strip():
        raise RuntimeError("缺少独立纯文字文案TXT，拒绝完整交付")
    md = (out/"segments_transcript.md").read_text("utf-8")
    for item in entries:
        if f"### 第{int(item['index']):03d}段｜" not in md:
            raise RuntimeError(f"台词MD缺少第{item['index']:03d}段")
    destination = out/"ClipFlow_完整交付.zip"
    intermediate = out/".ClipFlow_完整交付.zip.partial"
    try:
        with zipfile.ZipFile(intermediate, "w", allowZip64=True) as z:
            for name, path in members.items():
                compress = (zipfile.ZIP_STORED if path.suffix.lower() in {".mp4", ".jpg", ".png"}
                            else zipfile.ZIP_DEFLATED)
                z.write(path, arcname=name, compress_type=compress)
        if not zipfile.is_zipfile(intermediate):
            raise RuntimeError("交付ZIP格式校验失败")
        with zipfile.ZipFile(intermediate, "r") as z:
            if len(z.namelist()) != len(members) or set(z.namelist()) != set(members):
                raise RuntimeError("交付ZIP清单与实际成员不一致")
            if any(Path(name).name == "文案.txt" for name in z.namelist()):
                raise RuntimeError("文案TXT必须独立交付，禁止放入ZIP")
            corrupt = z.testzip()
            if corrupt:
                raise RuntimeError(f"交付ZIP内部成员校验失败: {corrupt}")
            validate_srt_export_punctuation(z.read("captions.srt").decode("utf-8-sig"))
            for name, path in members.items():
                if z.getinfo(name).file_size != path.stat().st_size:
                    raise RuntimeError(f"交付ZIP内部文件长度不一致: {name}")
            check = json.loads(z.read("manifest.json").decode("utf-8"))
            if len(check.get("segments", [])) != len(entries):
                raise RuntimeError("交付ZIP中切分清单与片段数量不一致")
            for row in check["segments"]:
                if row.get("still_image") != "segment_stills/" + Path(row["file"]).stem + ".jpg":
                    raise RuntimeError("清单内截图与MP4编号无法一一对应")
                if (row.get("still_sequence_number") != f"{int(row['index']):03d}"
                        or row.get("still_watermark_scheme") != "C"
                        or row.get("still_has_sequence_watermark") is not True):
                    raise RuntimeError("清单内截图编号水印记录不匹配")
            if sum(name.startswith("segment_stills/") and name.endswith(".jpg")
                   for name in z.namelist()) != len(entries):
                raise RuntimeError("截图张数与片段数量不一致")
        intermediate.replace(destination)
    finally:
        intermediate.unlink(missing_ok=True)
    return destination


def make_reference(args) -> None:
    source = args.input.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    info = media_info(source)
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()) and not args.overwrite:
        raise FileExistsError(f"输出目录非空: {out}。换目录或指定 --overwrite")
    out.mkdir(parents=True,exist_ok=True)
    if args.srt:
        captions = load_srt(args.srt)
        # SRT contains cue timestamps, not actual word timestamps.
        words = estimate_character_timing([TimedText(c.start,c.end,c.text) for c in captions])
        origin = "supplied_srt"
        alignment = "srt_estimated"
        recognized_language = None
    else:
        print("[ASR] 正在从原视频音轨识别中文（无需画面自带字幕）...",flush=True)
        recognition = recognize(source,args.model,args.device,args.language,backend=args.asr_backend)
        captions = [Caption(x.start,x.end,x.text) for x in recognition.captions]
        words = recognition.words
        origin = "cloud_whisper_asr" if recognition.alignment.startswith("cloud_") else "faster_whisper_asr"
        alignment = recognition.alignment
        recognized_language = recognition.language
    captions = [Caption(max(0,c.start),min(info["duration"],c.end),c.text)
                for c in captions if c.start < info["duration"] and c.end > 0]
    if not captions:
        raise RuntimeError("当前视频时间范围内无有效字幕")
    save_srt(captions,out/"captions.srt")
    write_plain_script_txt(captions, out/"文案.txt")
    # These are visual samples, NOT an automatic font recognition claim.
    reference_samples=create_reference_samples(source,captions,out/"subtitle_samples",
                                                info["width"],info["height"])
    profile_template=out/"subtitle_style_profile.json"
    create_style_template(profile_template,info["width"],info["height"])
    print(f"[subtitle style] 已生成对标截图 {reference_samples}; 样式待人工/视觉模型核实: {profile_template}",flush=True)
    shots = detect_scenes(source,info["duration"],step=args.scene_step)
    try:
        cuts = plan_sentence_cuts(info["duration"], shots, captions, words,
                                  maximum=args.max_seconds)
    except NoFeasibleSegmentation as exc:
        conflict = out/"cut_conflict.json"
        conflict.write_text(json.dumps(exc.diagnostic(),ensure_ascii=False,indent=2),
                            encoding="utf-8")
        raise RuntimeError(f"切分HOLD：{exc.reason}；已记录冲突：{conflict}") from exc
    font = str(args.font_file) if args.font_file else ffmpeg_font()
    clip_dir = out/"segments"
    clip_dir.mkdir(exist_ok=True)
    entries=[]
    for i,(start,end) in enumerate(zip(cuts,cuts[1:]),1):
        filename=f"{i:03d}_镜头.mp4"
        target=clip_dir/filename
        export_reference_segment(source,target,start,end,info,i,font,args.crf,args.preset)
        actual=media_info(target)
        if not (MIN_SECONDS_EXCLUSIVE < actual["duration"] <= MAX_SECONDS_INCLUSIVE + 1e-4):
            raise RuntimeError(
                f"片段 {filename} 编码后时长不满足>3且<=8秒："
                f"{actual['duration']:.3f}s；拒绝完整ZIP交付")
        still_target = out/"segment_stills"/(Path(filename).stem + ".jpg")
        still_info = export_segment_still(
            source, start, end, still_target, number=i,
            watermark_filter=drawtext_filter(i, info, font))
        entries.append({"index":i,"file":filename,"start":start,"end":end,
                        "duration":round(end-start,3),"encoded_duration":round(actual["duration"],3),
                        "scene_label":f"镜头{i:03d}","role":"待确认", **still_info})
        print(f"[reference] {filename} {start:.2f}–{end:.2f}s",flush=True)
    transcript_parts = assign_words_to_segments(entries, words)
    for entry, script in zip(entries, transcript_parts):
        entry["transcript"] = script
    transcript_md = out / "segments_transcript.md"
    write_segment_document(transcript_md, source.name, info["duration"],
                           entries, transcript_parts, origin, alignment,
                           args.model if origin in ("cloud_whisper_asr", "faster_whisper_asr") else None)
    manifest={"version":"0.4.6","reference_filename":source.name,
              "reference_duration":round(info["duration"],3),
              "reference_sha256":sha256(source),"original_media":{
                  "width":info["width"],"height":info["height"],"fps":info["fps"]},
              "caption_source":origin,
              "transcript_document":"segments_transcript.md",
              "plain_script_document":"文案.txt",
              "plain_script_delivery":"standalone_outside_complete_zip",
              "transcript_alignment":alignment,
              "asr_model":args.model if origin in ("cloud_whisper_asr", "faster_whisper_asr") else None,
              "asr_language":recognized_language,
              "subtitle_style_status":"pending_visual_review",
              "subtitle_style_profile":"subtitle_style_profile.json",
              "subtitle_sample_contact":"subtitle_samples/subtitle_reference_contact.jpg",
                             "cut_policy":{
                   "minimum_exclusive_seconds":MIN_SECONDS_EXCLUSIVE,
                   "maximum_inclusive_seconds":MAX_SECONDS_INCLUSIVE,
                   "algorithm":"global_DP_sentence_terminal_scene_preferred",
                   "source":"raw_ASR_or_supplied_SRT_before_display_punctuation_cleanup",
                   "confirmed_sentence_end_candidates": verified_sentence_ends(
                       captions, words, info["duration"]),
                   "all_nonfinal_cuts_are_confirmed_sentence_ends":True,
               },
               "segment_still_policy":"first_10_frames_minimum_OCR_text_before_C_watermark",
              "watermark":{
                  "scheme":"C","text_alpha":0.4,"stroke_alpha":0.8,
                  "landscape_stroke_px_at_1920w":10,"portrait_stroke_px_at_1080w":7},
              "segments":entries,"scene_detected_at":shots,
              "notes":"场景边界是自动候选；人物和机位标签需要人工核对。"}
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    with zipfile.ZipFile(out/"numbered_segments.zip","w",zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(clip_dir.glob("*.mp4")):
            archive.write(file,arcname=file.name)
    # Easy cross-window transfer: includes reference samples, timing and style status,
    # never the full original video or private audio.
    with zipfile.ZipFile(out/"subtitle_reference_stylekit.zip","w",zipfile.ZIP_DEFLATED) as archive:
        for name in ("captions.srt","segments_transcript.md","manifest.json","subtitle_style_profile.json"):
            archive.write(out/name,arcname=name)
        for sample in sorted((out/"subtitle_samples").glob("*")):
            if sample.is_file():
                archive.write(sample,arcname="subtitle_samples/"+sample.name)
    write_segment_list_csv(out/"segments_list.csv", entries)
    complete_zip = build_complete_delivery_zip(out, entries)
    print(f"[delivery] 完整交付ZIP已通过成员、CRC、时长清单与片段数量校验：{complete_zip} ({complete_zip.stat().st_size} 字节)")
    print(f"完成：{len(entries)}段；主要交付 {complete_zip}；独立纯文案 {out/'文案.txt'}；单独SRT {out/'captions.srt'}；逐段台词 {transcript_md}")


def resolve_order(clips: list[Path], order_file: Path|None,
                  reference: Path|None, *, min_score: float=.17) -> tuple[list[Path],str]:
    if not clips:
        raise ValueError("没有找到mp4片段")
    if order_file:
        lines=[x.strip() for x in order_file.read_text(encoding="utf-8-sig").splitlines()
               if x.strip() and not x.lstrip().startswith("#")]
        byname={p.name:p for p in clips}
        if len(lines)!=len(clips) or set(lines)!=set(byname):
            raise ValueError("--order-file 必须逐行完整列出所有片段文件名，各一次")
        return [byname[n] for n in lines],"explicit_order_file"
    numbered=[]
    for f in clips:
        m=re.match(r"^(\d{1,4})[_ .-]",f.name)
        if not m:
            break
        numbered.append((int(m.group(1)),f))
    if len(numbered)==len(clips) and len({n for n,_ in numbered})==len(clips):
        return [p for _,p in sorted(numbered)],"numeric_filename"
    if reference:
        return audio_order(clips,reference,min_score),"audio_match"
    raise ValueError("新视频文件名没有001式序号。请提供 --order-file，或提供 --reference 以便尝试按音频排序；绝不按随机文件名猜顺序。")


def audio_samples(video: Path, rate:int=8000) -> 'object':
    import numpy as np
    raw=subprocess.run(["ffmpeg","-hide_banner","-loglevel","error",
                        "-i",str(video),"-vn","-ac","1","-ar",str(rate),
                        "-f","f32le","-"],capture_output=True)
    if raw.returncode:
        raise RuntimeError(f"提取音频失败: {video.name}; {raw.stderr[-400:]}")
    return np.frombuffer(raw.stdout,dtype="<f4").copy()


def audio_order(clips: list[Path], reference: Path, threshold:float) -> list[Path]:
    """Audio matching for clips retaining the reference speech track.

    If regenerated speech differs, supply a verified order file instead.
    """
    import numpy as np
    from scipy.signal import fftconvolve, resample_poly
    base=audio_samples(reference)
    base=resample_poly(base,1,4)  # 2000 Hz; faster correlation
    if not len(base):
        raise ValueError("对标视频无音频，无法按音频自动排序")
    # remove DC; emphasize variation in speech over background music
    base=base-np.mean(base)
    results=[]
    for path in clips:
        audio=resample_poly(audio_samples(path),1,4)
        if len(audio)<1500:
            raise ValueError(f"片段音频太短，无法自动排序: {path.name}")
        # use central 1–3 s to avoid intro fades and marginal audio differences
        mid=len(audio)//2
        r=audio[max(0,mid-3000):min(len(audio),mid+3000)].copy()
        r-=r.mean()
        n=min(len(r),len(base))
        r=r[:n]
        if np.std(r)<1e-4:
            raise ValueError(f"片段几乎无音频，无法按原声排序: {path.name}")
        corr=fftconvolve(base,r[::-1],mode="valid")
        energy=fftconvolve(base**2,np.ones(len(r)),mode="valid")
        denom=np.sqrt(np.maximum(energy,1e-12)*np.sum(r*r))
        scores=np.abs(corr)/np.maximum(denom,1e-12)
        best=int(np.argmax(scores))
        score=float(scores[best])
        if score<threshold:
            raise ValueError(f"自动音频匹配不可靠（{path.name}: {score:.2f}）；请提供 --order-file")
        offset=(mid-min(3000,mid))/2000
        results.append((best/2000-offset,path,score))
    if len({round(x[0],1) for x in results})<len(results):
        raise ValueError("音频位置匹配冲突；请提供 --order-file 确认顺序")
    for t,path,score in sorted(results):
        print(f"[order] {path.name} -> {t:.2f}s, correlation {score:.3f}")
    return [path for _,path,_ in sorted(results)]


def find_font(style:str) -> str:
    if style == "B":
        return "Noto Serif CJK SC"
    if style == "C":
        return "Noto Sans CJK SC"
    return "Noto Sans CJK SC"


def ass_escape(s:str)->str:
    return s.replace("\\","\\\\").replace("{","\\{").replace("}","\\}").replace("\n","\\N")


def subtitle_chunks(text:str, highlights:list[str])->str:
    # ASS primary white; highlight yellow-green; longest matching keywords first.
    phrases=sorted({v for v in highlights if v},key=len,reverse=True)
    result=[]
    i=0
    while i<len(text):
        match=next((word for word in phrases if text.startswith(word,i)),None)
        if match:
            result.append("{\\c&H47F2CC&}"+ass_escape(match)+"{\\c&HFFFFFF&}")
            i+=len(match)
        else:
            result.append(ass_escape(text[i]));i+=1
    return "".join(result)


def convert_srt_to_ass(captions:list[Caption], filename:Path,info:dict,
                       style:str, subtitles_y:int|None, skip_intervals:list[tuple[float,float]])->None:
    w,h=info["width"],info["height"]
    base=round(84*w/1080) if h>w else round(84*h/1920)
    y=subtitles_y if subtitles_y is not None else round(h*.59)
    fontsize=max(22,base)
    font=find_font(style)
    def asstime(t:float)->str:
        cent=max(0,int(round(t*100)))
        hr,rem=divmod(cent,360000);mi,rem=divmod(rem,6000);sec,cs=divmod(rem,100)
        return f"{hr}:{mi:02d}:{sec:02d}.{cs:02d}"
    script=(f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\n"
            "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Base,{font},{fontsize},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
            f"-1,0,0,0,100,100,3,0,1,6,2,5,25,25,15,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    keywords=["律师","法律","打官司","经济纠纷","合同纠纷","合同","违约","权益","风险","损失","赔偿","刑事","婚姻","解决方案","关注我","评论区","私人法律顾问"]
    for c in captions:
        if any(a < c.end and c.start < b for a,b in skip_intervals):
            # The specified scene already contains baked subtitles; do not double overprint.
            continue
        sz=fontsize
        count=sum(1.0 if ord(ch)>127 else .58 for ch in c.text)
        max_width=w*.90
        if count*sz>max_width:
            sz=max(20,int(max_width/max(count,1)))
        txt=f"{{\\an5\\pos({w//2},{y})\\fs{sz}}}"+subtitle_chunks(c.text,keywords)
        script+=f"Dialogue: 0,{asstime(c.start)},{asstime(c.end)},Base,,0,0,0,,{txt}\n"
    filename.write_text(script,encoding="utf-8-sig")


def remap_captions(captions:list[Caption], reference_segments:list[dict],
                   clips:list[Path])->list[Caption]:
    """Move original SRT times to new untrimmed segment timeline, if available."""
    if len(reference_segments)!=len(clips):
        return captions
    clip_durations=[media_info(f)["duration"] for f in clips]
    offsets=[0.]
    for d in clip_durations:
        offsets.append(offsets[-1]+d)
    def remap(t:float)->float:
        for i,s in enumerate(reference_segments):
            if t<=s["end"] or i==len(reference_segments)-1:
                orig=max(.001,s["end"]-s["start"])
                return offsets[i]+max(0,min(1,(t-s["start"])/orig))*clip_durations[i]
        return t
    return [Caption(remap(c.start),max(remap(c.start)+.04,remap(c.end)),c.text)
            for c in captions]


def concat_file_list(clips:list[Path],path:Path)->None:
    def q(p:Path)->str:
        return str(p.resolve()).replace("'", "'\\''")
    path.write_text("".join("file '"+q(p)+"'\n" for p in clips),encoding="utf-8")


def assemble(args)->None:
    files=[]
    if args.clips_dir:
        files.extend(sorted(args.clips_dir.glob("*.mp4")))
    if args.clips:
        files.extend(args.clips)
    files=[f.resolve() for f in files]
    if not files or len(set(files))!=len(files):
        raise ValueError("请输入包含MP4的 --clips-dir 或 --clips，且不要重复文件")
    for f in files:
        if not f.is_file():
            raise FileNotFoundError(f)
    manifest={}
    if args.manifest:
        manifest=json.loads(args.manifest.read_text(encoding="utf-8"))
    ref=args.reference.resolve() if args.reference else None
    if ref and not ref.is_file():
        raise FileNotFoundError(ref)
    clips,method=resolve_order(files,args.order_file,ref)
    infos=[media_info(f) for f in clips]
    if len({(i['width'],i['height']) for i in infos})!=1:
        raise ValueError("片段分辨率不同。为了不擅自裁剪或缩放，请先统一尺寸。")
    if len({round(i['fps'],3) for i in infos})>1:
        raise ValueError("片段帧率不同。默认不补帧/变速，请先统一原视频帧率。")
    if not args.replace_audio and len({i['has_audio'] for i in infos})>1:
        raise ValueError("部分片段无音频。默认保留各段声音，不能自动补出缺失音轨；请整理音轨或显式指定原声替换。")
    if args.replace_audio and not ref:
        raise ValueError("原声替换必须同时提供 --reference 原视频")
    if args.burn_subtitles and not (args.srt or args.manifest):
        raise ValueError("字幕合成需要 --srt（或 --manifest 自动关联其相邻 captions.srt）")
    target=args.out.resolve()
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and not args.overwrite:
        raise FileExistsError(f"成品已存在: {target}，如需覆盖请添加 --overwrite")
    video_dur=sum(i['duration'] for i in infos)
    if args.replace_audio:
        ref_info=media_info(ref)
        if not ref_info["has_audio"]:
            raise ValueError("对标视频没有可用原声音轨")
        if abs(video_dur-ref_info["duration"])>args.audio_tolerance:
            raise ValueError(f"原声时长 {ref_info['duration']:.2f}s，与拼接画面 {video_dur:.2f}s 差值较大；"
                             "为避免自动截断画面，请核对顺序/时长，或明确提高 --audio-tolerance")
    clips_report=[]
    sumstart=0.0
    for n,(path,info) in enumerate(zip(clips,infos),1):
        clips_report.append({"index":n,"filename":path.name,"start":round(sumstart,3),
                             "duration":round(info['duration'],3)})
        sumstart+=info['duration']
    with tempfile.TemporaryDirectory(prefix="clipflow-") as scratch:
        scratch=Path(scratch)
        concat=scratch/"files.txt"
        concat_file_list(clips,concat)
        filters=[]
        if not args.no_grade:
            # Approximation to the CapCut look, not an invocation of its proprietary filter.
            filters.extend(["eq=contrast=1.08:brightness=0.012:saturation=1.075:gamma=1.02",
                            "unsharp=5:5:0.35:5:5:0.0"])
        if args.burn_subtitles:
            sub_path=args.srt or (args.manifest.parent/"captions.srt")
            if not sub_path.exists():
                raise FileNotFoundError(sub_path)
            captions=load_srt(sub_path)
            if manifest.get("segments"):
                captions=remap_captions(captions,manifest["segments"],clips)
            skip=[]
            for value in args.skip_existing_subs:
                n=int(value)
                if not 1<=n<=len(clips_report):
                    raise ValueError(f"无效已有硬字幕片段序号: {n}")
                start=clips_report[n-1]["start"]
                skip.append((start,start+clips_report[n-1]["duration"]))
            ass=scratch/"subtitles.ass"
            profile_file=args.subtitle_profile
            if profile_file is None and args.manifest:
                profile_file=args.manifest.parent/"subtitle_style_profile.json"
            if profile_file is not None:
                if not profile_file.is_file():
                    raise FileNotFoundError(f"缺少对标字幕样式配置：{profile_file}。请先审阅第一阶段 subtitle_samples/ 截图并填写配置；确认无画面字幕才用后备风格")
                verified_profile=read_style_profile(profile_file)
                if verified_profile is None:
                    print(f"[subtitles] 对标确认为无画面字幕，使用后备方案 {args.subtitle_style}",flush=True)
                    convert_srt_to_ass(captions,ass,infos[0],args.subtitle_style,args.subtitle_y,skip)
                else:
                    print(f"[subtitles] 根据对标视觉核对配置还原字幕：{profile_file}",flush=True)
                    convert_matched_ass(captions,ass,infos[0]['width'],infos[0]['height'],verified_profile,skip)
            else:
                if args.reference:
                    raise ValueError("已提供对标视频，但未提供 --manifest/--subtitle-profile 视觉核对信息；为避免固定套用B字体，请先制作对标样式配置")
                print("[subtitles] 未提供对标：使用后备字幕方案",flush=True)
                convert_srt_to_ass(captions,ass,infos[0],args.subtitle_style,args.subtitle_y,skip)
            filters.append("ass='"+str(ass).replace("'","\\'")+"'")
        argv=["ffmpeg","-hide_banner","-loglevel","error","-y",
              "-f","concat","-safe","0","-i",str(concat)]
        if args.replace_audio:
            argv.extend(["-i",str(ref)])
        argv.extend(["-map","0:v:0"])
        argv.extend(["-map","1:a:0" if args.replace_audio else "0:a:0?"])
        if filters:
            argv.extend(["-vf",",".join(filters)])
        argv.extend(["-c:v","libx264","-preset",args.preset,
                     "-crf",str(args.crf),"-pix_fmt","yuv420p",
                     "-c:a","aac","-b:a","192k", "-movflags","+faststart"])
        if args.replace_audio:
            argv.extend(["-af","apad", "-t",f"{video_dur:.3f}"])
        argv.append(str(target))
        command(argv)
    final=media_info(target)
    if abs(final["duration"]-video_dur)>max(.35, len(clips)*.05):
        raise RuntimeError(f"导出时长异常：预计{video_dur:.2f}s，实际{final['duration']:.2f}s；请检查输入音视频时间戳")
    report={"version":"0.2.0","source_count":len(clips),"order_method":method,
            "clips":clips_report,"target":target.name,"duration":round(final['duration'],3),
            "width":final['width'],"height":final['height'],"fps":final['fps'],
            "color_grade":not args.no_grade,"color_grade_type":"simulated_dehaze",
            "original_audio_replaced":args.replace_audio,"subtitle_burned":args.burn_subtitles,
            "subtitle_style_source":("reference_visual_profile" if args.burn_subtitles and "verified_profile" in locals() and verified_profile else ("confirmed_no_reference_subtitles_fallback" if args.burn_subtitles and "verified_profile" in locals() else ("legacy_fallback_no_reference" if args.burn_subtitles else "not_applied"))),
            "output_sha256":sha256(target)}
    report_path=target.with_suffix(".report.json")
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"完成：{target} ({final['duration']:.2f}s)；报告：{report_path}")


def transcribe_only(args) -> None:
    """Independent local audio-to-text without scene splitting."""
    source = args.input.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()) and not args.overwrite:
        raise FileExistsError(f"输出目录非空: {out}。换目录或指定 --overwrite")
    out.mkdir(parents=True, exist_ok=True)
    recognized = recognize(source, args.model, args.device, args.language,backend=args.asr_backend)
    save_srt([Caption(s.start,s.end,s.text) for s in recognized.captions],out/"captions.srt")
    write_plain_script_txt([Caption(s.start,s.end,s.text) for s in recognized.captions],out/"文案.txt")
    write_whole_transcript(out/"transcript.md",source.name,recognized.captions,
                           args.model,recognized.language,recognized.alignment)
    print(f"完成语音识别：{out/'captions.srt'}；{out/'transcript.md'}")


def doctor() -> None:
    """Never downloads packages or weights; read-only local capability check."""
    import importlib.util
    from . import __version__
    present = importlib.util.find_spec("faster_whisper") is not None
    print(json.dumps({
        "clipflow_version": __version__,
        "active_workflow": "reference_only",
        "legacy_assemble_cli_enabled": False,
        "ffmpeg_installed": shutil.which("ffmpeg") is not None,
        "ffprobe_installed": shutil.which("ffprobe") is not None,
        "asr_backend": "cloud-if-configured-else-local-faster-whisper",
        "cloud_endpoint_configured": bool(os.getenv("CLIPFLOW_ASR_URL")),
        "cloud_api_key_configured": bool(os.getenv("CLIPFLOW_ASR_API_KEY")),
        "asr_dependency_installed": present,
        "asr_model_ready": "not_checked",
        "asr_install_command": "python -m pip install -e '.[asr]'",
        "model_note": "云端URL与密钥都已配置时不需要在客户端安装模型；否则本地首次下载模型需联网。",
    }, ensure_ascii=False, indent=2))


def parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(prog="clipflow",description="当前唯一活动流程：对标视频第一阶段切分、编号、原声ASR、SRT/MD及ZIP外纯文案TXT。历史合成阶段已停用。")
    sub=p.add_subparsers(dest="action",required=True)
    ref=sub.add_parser("reference",help="阶段一：视频 -> 编号片段ZIP + 原声识别SRT + 逐段台词MD")
    ref.add_argument("--input",type=Path,required=True)
    ref.add_argument("--out",type=Path,required=True)
    ref.add_argument("--srt",type=Path,help="用已有SRT；省略则运行本地faster-whisper ASR")
    ref.add_argument("--asr-backend",choices=["auto","cloud","local"],default="auto",help="配置云端地址和密钥时默认使用云端；否则本地")
    ref.add_argument("--model",default="small",help="faster-whisper 模型，默认 small")
    ref.add_argument("--device",default="cpu",help="cpu 或 cuda")
    ref.add_argument("--language",default="zh")
    ref.add_argument("--max-seconds",type=float,default=8.0,
                     help="严格最大8秒；所有分段均必须>3秒")
    ref.add_argument("--scene-step",type=float,default=.23)
    ref.add_argument("--font-file",type=Path)
    ref.add_argument("--crf",type=int,default=19)
    ref.add_argument("--preset",default="veryfast")
    ref.add_argument("--overwrite",action="store_true")
    tr=sub.add_parser("transcribe",help="独立音频识别：视频/音频 -> SRT + 全文MD（无需画面自带字幕）")
    tr.add_argument("--input",type=Path,required=True,help="含人声的视频或音频文件")
    tr.add_argument("--out",type=Path,required=True,help="输出目录")
    tr.add_argument("--asr-backend",choices=["auto","cloud","local"],default="auto",help="配置云端地址和密钥时默认使用云端；否则本地")
    tr.add_argument("--model",default="small",help="Whisper模型名或已下载的本地模型目录")
    tr.add_argument("--device",default="cpu",help="cpu 或 cuda")
    tr.add_argument("--language",default="zh",help="中文zh；自动识别可用auto")
    tr.add_argument("--overwrite",action="store_true")
    sub.add_parser("doctor",help="检查FFmpeg与本地ASR依赖状态，不下载安装")
    ass=sub.add_parser("assemble",help="历史第二阶段（已停用，不执行；保留参数仅为兼容旧脚本诊断）")
    ass.add_argument("--clips-dir",type=Path)
    ass.add_argument("--clips",type=Path,nargs="+")
    ass.add_argument("--out",type=Path,required=True)
    ass.add_argument("--order-file",type=Path,help="每行一个文件名；无001编号时推荐")
    ass.add_argument("--reference",type=Path,help="原视频：可用于音频排序，或在 --replace-audio 时提取原声")
    ass.add_argument("--manifest",type=Path,help="阶段一的 manifest.json，字幕映射使用")
    ass.add_argument("--replace-audio",action="store_true",help="明确要求时才执行")
    ass.add_argument("--burn-subtitles",action="store_true",help="明确要求时才执行")
    ass.add_argument("--srt",type=Path,help="阶段一生成的 captions.srt")
    ass.add_argument("--subtitle-style",choices=["A","B","C"],default="B",
                     help="仅确认对标无字幕（或完全未提供对标）时使用的后备方案")
    ass.add_argument("--subtitle-profile",type=Path,
                     help="对标字幕视觉核验配置 JSON；若给 --manifest 则自动读取其目录下的配置")
    ass.add_argument("--subtitle-y",type=int,help="字幕中心Y坐标，默认画面高度的59%")
    ass.add_argument("--skip-existing-subs",nargs="*",default=[],help="已有硬字幕的片段编号，避免叠加")
    ass.add_argument("--audio-tolerance",type=float,default=.75,help="允许原声和画面总时长差，默认0.75s")
    ass.add_argument("--no-grade",action="store_true",help="仅用户明确要求取消去灰通透时使用")
    ass.add_argument("--crf",type=int,default=19)
    ass.add_argument("--preset",default="veryfast")
    ass.add_argument("--overwrite",action="store_true")
    return p


def main(argv:list[str]|None=None)->int:
    p=parser()
    args=p.parse_args(argv)
    try:
        if args.action=="reference":make_reference(args)
        elif args.action=="assemble":
            raise RuntimeError("当前ClipFlow仅允许第一阶段reference；历史第二阶段assemble已停用，不执行合并。")
        elif args.action=="transcribe":transcribe_only(args)
        elif args.action=="doctor":doctor()
    except (OSError,ValueError,RuntimeError,AssertionError) as exc:
        print(f"错误：{exc}",file=sys.stderr)
        return 2
    return 0


if __name__=="__main__":
    sys.exit(main())
