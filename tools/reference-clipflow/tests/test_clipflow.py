import argparse
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from clipflow.cli import (Caption, load_srt, save_srt, clock, seconds,
                          choose_cuts, subtitle_chunks, drawtext_filter, media_info,
                          resolve_order, convert_srt_to_ass, main)


def test_srt_roundtrip(tmp_path):
    xs=[Caption(0.15,1.83,"大家好，我是姜律师"),Caption(1.83,3.54,"合同风险和经济纠纷")]
    p=tmp_path/"z.srt"
    save_srt(xs,p)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
    assert load_srt(p)==xs
    assert seconds(clock(3701.23))==3701.23


def test_cut_boundaries_sentence_priority_and_maximum():
    captions=[Caption(0,5.9,"第一句。"),Caption(5.9,12,"第二句。"),Caption(12,17.9,"第三句。")]
    cuts=choose_cuts(17.9,[5.5,13.1],captions,9.8)
    assert cuts[0]==0 and cuts[-1]==17.9
    assert 5.9 in cuts
    assert all(0<b-a<=9.8 for a,b in zip(cuts,cuts[1:]))


def test_choose_cuts_long_speech_hard_limit():
    cuts=choose_cuts(35.6,[],[Caption(0,35.6,"长语句")],maximum=9.8)
    assert cuts==[0,9.8,19.6,29.4,35.6]


def test_drawtext_scheme_c():
    p=drawtext_filter(12,{"width":1920,"height":1080},"/tmp/font.ttf")
    assert "text='012'" in p
    assert "fontsize=260" in p
    assert "fontcolor=white@0.40" in p
    assert "bordercolor=black@0.80:borderw=10" in p
    q=drawtext_filter(8,{"width":1080,"height":1920},"/tmp/font.ttf")
    assert "borderw=7" in q


def test_order_never_guess(tmp_path):
    a=tmp_path/"randomY.mp4"; b=tmp_path/"randomX.mp4"
    a.touch(); b.touch()
    with pytest.raises(ValueError,match="order-file"):
        resolve_order([a,b],None,None)
    p=tmp_path/"order.txt";p.write_text("randomY.mp4\nrandomX.mp4\n")
    ordered,m=resolve_order([b,a],p,None)
    assert ordered==[a,b] and m=="explicit_order_file"
    numbered=[tmp_path/"002_X.mp4",tmp_path/"001_X.mp4"]
    ordered,m=resolve_order(numbered,None,None)
    assert [x.name for x in ordered]==["001_X.mp4","002_X.mp4"]


def test_ass_generation_not_normal_srt_style(tmp_path):
    f=tmp_path/"sub.ass"
    convert_srt_to_ass([Caption(0,1,"律师可以分析合同纠纷")],f,
                       {"width":1080,"height":1920},"B",None,[])
    s=f.read_text(encoding="utf-8-sig")
    assert "Noto Serif CJK SC" in s
    assert "&H47F2CC&" in s
    assert "\\pos(540,1133)" in s


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="ffmpeg/ffprobe required")
def test_end_to_end_default_assemble_no_optional_actions(tmp_path):
    clipdir=tmp_path/"clips";clipdir.mkdir()
    for n in (1,2):
        subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
             "-f","lavfi","-i",f"color=c={'blue' if n==1 else 'green'}:s=160x288:r=12:d=1.2",
             "-f","lavfi","-i","sine=frequency=800:sample_rate=16000:duration=1.2",
             "-shortest","-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",
             "-c:a","aac",str(clipdir/f"{n:03d}_test.mp4")],check=True)
    target=tmp_path/"joined.mp4"
    assert main(["assemble","--clips-dir",str(clipdir),"--out",str(target),
                 "--preset","ultrafast"])==0
    report=json.loads(target.with_suffix(".report.json").read_text())
    assert report["original_audio_replaced"] is False
    assert report["subtitle_burned"] is False
    assert report["color_grade"] is True
    assert report["source_count"]==2
    assert 2.4<=media_info(target)["duration"]<2.6
