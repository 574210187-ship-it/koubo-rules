"""Reference-first subtitle styling for Reference ClipFlow.

A video frame can show a font, but not reliably identify its exact installed
family name. Visual assessment must be performed by an operator/vision-capable
assistant. The CLI produces sample frames and a *pending* profile; it never
pretends it automatically extracted an exact font from pixels.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Iterable


def create_reference_samples(video: Path, captions: Iterable, output_dir: Path,
                             canvas_width: int, canvas_height: int,
                             max_samples: int = 12) -> Path:
    """Export original-resolution subtitle samples and a contact sheet.

    The samples come from the original reference, never a watermarked segment.
    They must be reviewed for visible/baked subtitles vs. speech alone.
    """
    import cv2
    import numpy as np

    output_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"无法读取对标视频以制作字幕样张: {video}")
    cues = list(captions)
    if not cues:
        raise ValueError("缺少字幕时间，无法制作参考样张")
    indexes = []
    if len(cues) <= max_samples:
        indexes = list(range(len(cues)))
    else:
        indexes = sorted({int(round(k*(len(cues)-1)/(max_samples-1)))
                          for k in range(max_samples)})
    thumbs = []
    selected = []
    try:
        for idx in indexes:
            cue = cues[idx]
            moment = (float(cue.start) + float(cue.end))/2
            cap.set(cv2.CAP_PROP_POS_MSEC, moment*1000)
            ok, frame = cap.read()
            if not ok:
                continue
            full = output_dir/f"cue_{idx+1:03d}_{moment:07.2f}s.jpg"
            if not cv2.imwrite(str(full), frame, [cv2.IMWRITE_JPEG_QUALITY, 94]):
                continue
            selected.append({"cue_index":idx+1,"sample_time":round(moment,3),
                             "file":full.name})
            scale = min(360/max(frame.shape[1],1), 480/max(frame.shape[0],1))
            tile = cv2.resize(frame, (max(1,round(frame.shape[1]*scale)),
                                      max(1,round(frame.shape[0]*scale))),
                              interpolation=cv2.INTER_AREA)
            cell = np.full((520,380,3),238,np.uint8)
            x=(380-tile.shape[1])//2
            cell[34:34+tile.shape[0],x:x+tile.shape[1]] = tile
            cv2.putText(cell,f"cue {idx+1:03d}   {moment:.2f}s",(14,23),
                        cv2.FONT_HERSHEY_SIMPLEX,.58,(10,10,10),1,cv2.LINE_AA)
            thumbs.append(cell)
    finally:
        cap.release()
    if not thumbs:
        raise RuntimeError("对标视频提取字幕样张失败")
    cols = min(3,len(thumbs))
    rows = (len(thumbs)+cols-1)//cols
    contact = np.full((rows*520,cols*380,3),238,np.uint8)
    for i,tile in enumerate(thumbs):
        y=(i//cols)*520
        x=(i%cols)*380
        contact[y:y+520,x:x+380]=tile
    path=output_dir/"subtitle_reference_contact.jpg"
    cv2.imwrite(str(path),contact,[cv2.IMWRITE_JPEG_QUALITY,90])
    (output_dir/"sample_index.json").write_text(
        json.dumps({"source_canvas":[canvas_width,canvas_height],
                    "samples":selected},ensure_ascii=False,indent=2),encoding="utf-8")
    return path


def create_style_template(path: Path, width:int, height:int)->None:
    """Pending on purpose: unknown is NOT the same as no visible subtitles."""
    template={
        "schema_version":1,
        "reference_has_subtitles":None,
        "visually_reviewed":False,
        "notes":"请查看 subtitle_samples/ 原分辨率截图；确认有/无画面字幕。",
        "source_canvas_width":width,
        "source_canvas_height":height,
        "font_family":None,
        "font_size_px":None,
        "emphasis_size_px":None,
        "letter_spacing_px":None,
        "position_x_ratio":None,
        "position_y_ratio":None,
        "max_width_ratio":0.92,
        "primary_color":None,
        "emphasis_color":None,
        "outline_color":None,
        "outline_px":None,
        "shadow_color":None,
        "shadow_px":None,
        "bold":True,
        "highlight_terms":[],
        "caption_styles":{},
    }
    path.write_text(json.dumps(template,ensure_ascii=False,indent=2),encoding="utf-8")


def read_style_profile(path: Path)->dict | None:
    """Return a visually verified reference style, or None ONLY if confirmed absent.

    A pending profile must be reviewed. This prevents silently imposing the
    former B/C 84px defaults over visible reference subtitles.
    """
    obj=json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj,dict) or obj.get("schema_version")!=1:
        raise ValueError("字幕样式配置必须是 schema_version=1 的 JSON 对象")
    present=obj.get("reference_has_subtitles")
    if not obj.get("visually_reviewed") or present not in (True,False):
        raise ValueError("对标字幕尚未视觉审核：请查看 subtitle_samples/，将 subtitle_style_profile.json 的 reference_has_subtitles 和 visually_reviewed 填写确认后再合成字幕")
    if not present:
        return None
    must=("font_family","font_size_px","letter_spacing_px","position_x_ratio",
          "position_y_ratio","primary_color","outline_color","outline_px")
    missing=[k for k in must if obj.get(k) is None or obj.get(k)==""]
    if missing:
        raise ValueError("对标存在字幕，但样式配置缺少: "+", ".join(missing))
    for name in ("position_x_ratio","position_y_ratio"):
        val=obj[name]
        if not isinstance(val,(float,int)) or not 0<=val<=1:
            raise ValueError(f"{name} 必须在0和1之间")
    if not isinstance(obj.get("caption_styles",{}),dict):
        raise ValueError("caption_styles 必须是按字幕序号索引的对象")
    return obj


def ass_color(hexcolor:str, alpha:float=1.0)->str:
    """Turn #RRGGBB into ASS &HAABBGGRR (ASS alpha is inverted)."""
    if not isinstance(hexcolor,str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",hexcolor):
        raise ValueError(f"无效字幕颜色：{hexcolor!r}，应为 #RRGGBB")
    if not 0<=alpha<=1:
        raise ValueError("透明度应在0..1之间")
    r,g,b=hexcolor[1:3],hexcolor[3:5],hexcolor[5:7]
    return f"&H{round(255*(1-alpha)):02X}{b}{g}{r}".upper()


def escaped(s:str)->str:
    return s.replace("\\","\\\\").replace("{","\\{").replace("}","\\}").replace("\n","\\N")


def inline_color(color:str)->str:
    return ass_color(color)[0:2]+ass_color(color)[4:]  # &HBBGGRR


def asstime(t:float)->str:
    cs=max(0,int(round(t*100)))
    h,rem=divmod(cs,360000)
    m,rem=divmod(rem,6000)
    s,rem=divmod(rem,100)
    return f"{h}:{m:02d}:{s:02d}.{rem:02d}"


def style_runs(text:str, *, plain_color:str, emphasis_color:str,
               text_size:int, emphasis_size:int, terms:list[str],
               runs:list|None=None, scale:float=1.0)->str:
    if runs is not None:
        if not isinstance(runs,list) or "".join(str(x.get("text","")) for x in runs)!=text:
            raise ValueError("单条字幕 runs 各段文字拼接后必须与该条SRT原文完全一致")
        result=[]
        for run in runs:
            color=run.get("color",plain_color)
            size=int(round(float(run.get("font_size_px",text_size/scale))*scale))
            b=run.get("bold")
            attrs=f"\\c{inline_color(color)}\\fs{size}"
            if b is not None:
                attrs+=f"\\b{1 if b else 0}"
            if run.get("font_family"):
                attrs+="\\fn"+str(run["font_family"]).replace("{","").replace("}","")
            result.append("{"+attrs+"}"+escaped(str(run["text"])))
        return "".join(result)
    terms=sorted({v for v in terms if v},key=len,reverse=True)
    pieces=[]
    i=0
    while i<len(text):
        hit=next((word for word in terms if text.startswith(word,i)),None)
        if hit:
            pieces.append("{\\c"+inline_color(emphasis_color)+f"\\fs{emphasis_size}"+"}"+escaped(hit))
            pieces.append("{\\c"+inline_color(plain_color)+f"\\fs{text_size}"+"}")
            i+=len(hit)
        else:
            pieces.append(escaped(text[i])); i+=1
    return "".join(pieces)


def convert_matched_ass(captions: list, filename:Path, width:int,height:int,
                        profile:dict, skip_intervals:list[tuple[float,float]])->None:
    """Build editable ASS appearance mirroring a visually inspected reference.

    Whole-cue and within-cue color/size changes are supported. Exact font face
    is only possible when that licensed font is already installed by the user.
    """
    source_w=float(profile.get("source_canvas_width") or width)
    source_h=float(profile.get("source_canvas_height") or height)
    scale=min(width/source_w,height/source_h)
    font=str(profile["font_family"])
    base_px=max(12,round(float(profile["font_size_px"])*scale))
    space=max(0,round(float(profile["letter_spacing_px"])*scale))
    outline=max(0,round(float(profile["outline_px"])*scale))
    shadow=max(0,round(float(profile.get("shadow_px") or 0)*scale))
    emphasis_px=max(12,round(float(profile.get("emphasis_size_px") or profile["font_size_px"])*scale))
    def chosen_color(value,default):
        return ass_color(value if value else default)
    primary=profile["primary_color"]
    accent=profile.get("emphasis_color") or primary
    border=profile["outline_color"]
    shadow_color=profile.get("shadow_color") or border
    css=('[Script Info]\nScriptType: v4.00+\n'
         f'PlayResX: {width}\nPlayResY: {height}\n'
         'WrapStyle: 2\nScaledBorderAndShadow: yes\n\n'
         '[V4+ Styles]\n'
         'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
         f'Style: Reference,{font},{base_px},{ass_color(primary)},{ass_color(accent)},{ass_color(border)},{ass_color(shadow_color)},'
         f'{-1 if profile.get("bold",True) else 0},0,0,0,100,100,{space},0,1,{outline},{shadow},5,25,25,15,1\n\n'
         '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')
    overrides=profile.get("caption_styles") or {}
    for index,c in enumerate(captions,1):
        if any(a < c.end and c.start < b for a,b in skip_intervals):
            continue
        cue=overrides.get(str(index),{})
        if not isinstance(cue,dict):
            raise ValueError(f"caption_styles[{index}] 必须是对象")
        px=float(cue.get("font_size_px",profile["font_size_px"]))
        size=max(12,round(px*scale))
        accent_px=max(12,round(float(cue.get("emphasis_size_px",profile.get("emphasis_size_px") or px))*scale))
        line_space=max(0,round(float(cue.get("letter_spacing_px",profile["letter_spacing_px"]))*scale))
        x=round(float(cue.get("position_x_ratio",profile["position_x_ratio"]))*width)
        y=round(float(cue.get("position_y_ratio",profile["position_y_ratio"]))*height)
        plain=cue.get("primary_color",primary)
        high=cue.get("emphasis_color",accent)
        maxwidth=width*float(cue.get("max_width_ratio",profile.get("max_width_ratio",.92)))
        textwidth=sum(1 if ord(ch)>127 else .57 for ch in c.text)*size+max(0,len(c.text)-1)*line_space
        if textwidth>maxwidth and textwidth>0:
            k=maxwidth/textwidth
            size=max(12,int(size*k)); accent_px=max(12,int(accent_px*k));line_space=max(0,int(line_space*k))
        inline=f"\\an5\\pos({x},{y})\\fs{size}\\fsp{line_space}"
        if "font_family" in cue:
            inline+="\\fn"+str(cue["font_family"]).replace("{","").replace("}","")
        if "bold" in cue:
            inline+=f"\\b{1 if cue['bold'] else 0}"
        if "outline_px" in cue:
            inline+=f"\\bord{max(0,round(float(cue['outline_px'])*scale))}"
        if "shadow_px" in cue:
            inline+=f"\\shad{max(0,round(float(cue['shadow_px'])*scale))}"
        inline+="\\c"+inline_color(plain)
        if "outline_color" in cue:
            inline+="\\3c"+inline_color(cue["outline_color"])
        if "shadow_color" in cue:
            inline+="\\4c"+inline_color(cue["shadow_color"])
        if cue.get("fade_in_ms") or cue.get("fade_out_ms"):
            inline+=f"\\fad({int(cue.get('fade_in_ms',0))},{int(cue.get('fade_out_ms',0))})"
        terms=cue.get("highlight_terms",profile.get("highlight_terms") or [])
        runlist=cue.get("runs")
        txt="{"+inline+"}"+style_runs(c.text,plain_color=plain,emphasis_color=high,
                         text_size=size,emphasis_size=accent_px,terms=terms,
                         runs=runlist,scale=scale)
        css+=f"Dialogue: 0,{asstime(c.start)},{asstime(c.end)},Reference,,0,0,0,,{txt}\n"
    filename.write_text(css,encoding="utf-8-sig")
