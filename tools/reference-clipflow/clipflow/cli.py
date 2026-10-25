"""Reference ClipFlow: deterministic, portable FFmpeg video workflow.

Use `clipflow --help`, `clipflow reference --help`, and
`clipflow assemble --help`. Does not upload user media to any service.
"""
from __future__ import annotations

import argparse
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
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable

from .subtitle_style import (create_reference_samples, create_style_template,
                             read_style_profile, convert_matched_ass)
from .visual_ocr import VisualCue, subtitles_from_video, check_ocr
from .transcript import assign_cues_to_segments, write_segment_document


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


def save_srt(captions: Iterable[Caption], path: Path) -> None:
    captions = list(captions)
    if not captions:
        raise ValueError("没有字幕可写出")
    path.write_text("\n".join(
        f"{i}\n{clock(c.start)} --> {clock(c.end)}\n{c.text}\n"
        for i, c in enumerate(captions, 1)), encoding="utf-8-sig")


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
                maximum: float=9.8, snap_tolerance: float=1.0) -> list[float]:
    """Prefer whole phrases; never return a segment wider than `maximum`."""
    if maximum <= 0 or maximum > 10:
        raise ValueError("--max-seconds 必须 >0 且 <=10")
    sentence_ends = sorted(set(round(c.end,3) for c in captions
                               if .1 <= c.end < duration-.1))
    fixed = [0.0]
    for raw in sorted(shots):
        if raw <= fixed[-1]+.4 or raw >= duration-.15:
            continue
        candidates = [t for t in sentence_ends if abs(t-raw) <= snap_tolerance
                      and t > fixed[-1]+.4]
        cut = min(candidates, key=lambda t: abs(t-raw)) if candidates else raw
        if cut > fixed[-1]+.4:
            fixed.append(cut)
    fixed.append(duration)
    fixed = sorted(set(fixed))
    result = [0.0]
    for boundary in fixed[1:]:
        while boundary-result[-1] > maximum+1e-7:
            limit = result[-1]+maximum
            ends = [x for x in sentence_ends if result[-1]+1.3 <= x <= limit]
            if ends:
                best = max(ends)
            else:
                # A sentence longer than the hard limit must be cut anyway.
                best = limit
            if best <= result[-1]+.2:
                best = limit
            result.append(round(best,3))
        if boundary-result[-1] > .08:
            result.append(round(boundary,3))
        else:
            result[-1] = round(boundary,3)
    if abs(result[-1]-duration) > .01:
        result.append(round(duration,3))
    if any(b-a > maximum+.002 for a,b in zip(result,result[1:])):
        raise AssertionError("超时长段未正确处理")
    return result


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


def make_reference(args) -> None:
    """Export numbered MP4s and one MD with text from VISUAL subtitles only."""
    source = args.input.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    info = media_info(source)
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()) and not args.overwrite:
        raise FileExistsError(f"输出目录非空: {out}。换目录或指定 --overwrite")
    out.mkdir(parents=True,exist_ok=True)
    if args.overwrite:
        for name in ('captions.srt','segments_transcript.md','numbered_segments.zip',
                     'subtitle_reference_stylekit.zip'):
            (out/name).unlink(missing_ok=True)
    if args.srt:
        captions=load_srt(args.srt)
        origin='supplied_srt'
        audit={'mode':'supplied_srt','speech_audio_used':False,
               'status':'provided_captions_not_machine_ocr'}
    else:
        print('[OCR] 只从原视频的可见画面字幕识别文字；完全不读取音轨...',flush=True)
        if not (0 <= args.ocr_region[0] < args.ocr_region[2] <= 1 and
                0 <= args.ocr_region[1] < args.ocr_region[3] <= 1):
            raise ValueError('--ocr-region 应为0到1之间的四个数字 x0 y0 x1 y1')
        cues,audit = subtitles_from_video(
            source,info['duration'],step=args.ocr_interval,
            language=args.ocr_language,region=tuple(args.ocr_region))
        captions=[Caption(c.start,c.end,c.text) for c in cues]
        origin='visual_ocr' if captions else 'none_visible'
    captions=[Caption(max(0,c.start),min(info['duration'],c.end),c.text)
              for c in captions if c.start < info['duration'] and c.end > 0]
    if captions:
        save_srt(captions,out/'captions.srt')
        print(f'[OCR] 发现 {len(captions)} 条可信画面字幕（OCR需人工核验），已生成画面文字SRT',flush=True)
    else:
        print('[OCR] 未发现可信的可识别画面字幕：不会生成伪SRT，逐段MD仍然生成',flush=True)
    reference_samples=create_reference_samples(source,captions,out/'subtitle_samples',
                                                info['width'],info['height'],
                                                duration=info['duration'])
    profile_template=out/'subtitle_style_profile.json'
    create_style_template(profile_template,info['width'],info['height'])
    shots=detect_scenes(source,info['duration'],step=args.scene_step)
    cuts=choose_cuts(info['duration'],shots,captions,maximum=args.max_seconds)
    font=str(args.font_file) if args.font_file else ffmpeg_font()
    clip_dir=out/'segments'
    clip_dir.mkdir(exist_ok=True)
    if args.overwrite:
        for stale in clip_dir.glob('*.mp4'):
            stale.unlink()
    entries=[]
    for i,(start,end) in enumerate(zip(cuts,cuts[1:]),1):
        filename=f'{i:03d}_镜头.mp4'
        target=clip_dir/filename
        export_reference_segment(source,target,start,end,info,i,font,args.crf,args.preset)
        actual=media_info(target)
        if actual['duration'] > 10.02:
            raise RuntimeError(f"片段 {filename} 实际超过10秒: {actual['duration']:.3f}")
        entries.append({'index':i,'file':filename,'start':start,'end':end,
                        'duration':round(end-start,3),
                        'encoded_duration':round(actual['duration'],3),
                        'scene_label':f'镜头{i:03d}','role':'待确认'})
        print(f'[reference] {filename} {start:.2f}–{end:.2f}s',flush=True)
    transcript_parts=assign_cues_to_segments(entries,captions)
    for entry,script in zip(entries,transcript_parts):
        entry['transcript']=script
        entry['transcript_status']='visible_subtitle_ocr_review' if script else 'no_visible_subtitles'
    transcript_md=out/'segments_transcript.md'
    write_segment_document(transcript_md,source.name,info['duration'],
                           entries,transcript_parts,origin)
    manifest={
        'version':'0.5.0-visual-only',
        'reference_filename':source.name,
        'reference_duration':round(info['duration'],3),
        'reference_sha256':sha256(source),
        'original_media':{'width':info['width'],'height':info['height'],'fps':info['fps']},
        'caption_source':origin,
        'caption_status':audit['status'],
        'ocr_audit':audit,
        'transcript_document':'segments_transcript.md',
        'subtitle_style_status':'pending_visual_review',
        'subtitle_style_profile':'subtitle_style_profile.json',
        'subtitle_sample_contact':'subtitle_samples/subtitle_reference_contact.jpg',
        'watermark':{'scheme':'C','text_alpha':0.4,'stroke_alpha':0.8,
                     'landscape_stroke_px_at_1920w':10,
                     'portrait_stroke_px_at_1080w':7},
        'segments':entries, 'scene_detected_at':shots,
        'notes':'仅识别原视频可见字幕，不能从无字幕的画面恢复口播；自动镜头边界和OCR均待复核。'
    }
    (out/'manifest.json').write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    with zipfile.ZipFile(out/'numbered_segments.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            archive.write(clip_dir/entry['file'],arcname=entry['file'])
    with zipfile.ZipFile(out/'subtitle_reference_stylekit.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for name in ('captions.srt','segments_transcript.md','manifest.json','subtitle_style_profile.json'):
            f=out/name
            if f.is_file(): archive.write(f,arcname=name)
        for sample in sorted((out/'subtitle_samples').glob('*')):
            if sample.is_file():
                archive.write(sample,arcname='subtitle_samples/'+sample.name)
    print(f"完成：{len(entries)}段；ZIP {out/'numbered_segments.zip'}；分段台词MD {transcript_md}；"
          f"{'可见画面字幕SRT' if captions else '无可信字幕，不生成SRT'}",flush=True)


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


def doctor() -> None:
    """Read-only check of visual OCR, no ASR installation or model download."""
    from . import __version__
    ocr_ok=True
    try:
        check_ocr('chi_sim+eng')
    except RuntimeError as exc:
        ocr_ok=False
        detail=str(exc)
    else:
        detail='Tesseract中文OCR就绪；不需要Whisper或音频模型'
    print(json.dumps({
        'clipflow_version':__version__,
        'ffmpeg_installed':shutil.which('ffmpeg') is not None,
        'ffprobe_installed':shutil.which('ffprobe') is not None,
        'visual_ocr_available':ocr_ok,
        'ocr_note':detail,
        'speech_to_text_enabled':False,
        'audio_asr_dependency_required':False,
    },ensure_ascii=False,indent=2))


def parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(prog='clipflow',
         description='对标视频镜头拆分＋C水印＋画面字幕OCR＋每段台词MD；新片段拼接调色；不执行ASR。')
    sub=p.add_subparsers(dest='action',required=True)
    ref=sub.add_parser('reference',help='对标原视频 → 编号视频ZIP + 每段台词MD；有可信画面字幕时生成SRT')
    ref.add_argument('--input',type=Path,required=True)
    ref.add_argument('--out',type=Path,required=True)
    ref.add_argument('--srt',type=Path,help='可选：使用已有人工校对的画面字幕SRT，不使用音频识别')
    ref.add_argument('--ocr-language',default='chi_sim+eng',help='Tesseract语言代码')
    ref.add_argument('--ocr-interval',type=float,default=.55,help='每隔多少秒抽取原始画面作OCR，默认0.55秒')
    ref.add_argument('--ocr-region',type=float,nargs=4,default=[.06,.49,.94,.94],
                     metavar=('X0','Y0','X1','Y1'),
                     help='画面字幕区域的宽高相对坐标，默认中央偏下；范围均为0..1')
    ref.add_argument('--max-seconds',type=float,default=9.8)
    ref.add_argument('--scene-step',type=float,default=.23)
    ref.add_argument('--font-file',type=Path)
    ref.add_argument('--crf',type=int,default=19)
    ref.add_argument('--preset',default='veryfast')
    ref.add_argument('--overwrite',action='store_true')
    sub.add_parser('doctor',help='检查FFmpeg和中文画面字幕OCR，不下载任何语音模型')
    ass=sub.add_parser("assemble",help="阶段二：新片段自动排顺序拼接＋去灰通透；原声/字幕仅按显式选项")
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
        elif args.action=="assemble":assemble(args)
        elif args.action=="doctor":doctor()
    except (OSError,ValueError,RuntimeError,AssertionError) as exc:
        print(f"错误：{exc}",file=sys.stderr)
        return 2
    return 0


if __name__=="__main__":
    sys.exit(main())
