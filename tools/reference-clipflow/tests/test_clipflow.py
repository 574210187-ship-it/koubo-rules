import argparse
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from clipflow.cli import (Caption, load_srt, save_srt, clock, seconds,
                          srt_without_terminal_punctuation, validate_srt_export_punctuation,
                          write_plain_script_txt,
                          choose_cuts, subtitle_chunks, drawtext_filter, media_info,
                          resolve_order, convert_srt_to_ass, main)


def test_srt_roundtrip(tmp_path):
    xs=[Caption(0.15,1.83,"大家好，我是姜律师"),Caption(1.83,3.54,"合同风险和经济纠纷")]
    p=tmp_path/"z.srt"
    save_srt(xs,p)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
    assert load_srt(p)==xs
    assert seconds(clock(3701.23))==3701.23


@pytest.mark.parametrize("original, expected", [
    ("大家好，我是姜律师。", "大家好，我是姜律师"),
    ("遇到合同纠纷怎么办？！", "遇到合同纠纷怎么办"),
    ("证据一定要保存!!!  ", "证据一定要保存"),
    ("有疑问？！”", "有疑问"),
    ("今天讲讲合同纠纷……", "今天讲讲合同纠纷"),
    ("这里有3.14万元。", "这里有3.14万元"),
    ("我们可以讨论，先看证据；", "我们可以讨论，先看证据"),
    ("先别着急～", "先别着急"),
    ("证据如下：", "证据如下"),
    ("没问题", "没问题"),
])
def test_srt_terminal_punctuation_normalizer(original, expected):
    assert srt_without_terminal_punctuation(original) == expected


def test_srt_writing_cleans_each_line_and_preserves_timestamps_and_source(tmp_path):
    captions = [
        Caption(.20, 1.10, "第一行保留，逗号。\n第二行去感叹号！！"),
        Caption(1.30, 2.40, "里面保留3.14这个小数，句尾去省略号……"),
    ]
    path = tmp_path / "captions.srt"
    save_srt(captions, path)
    written = path.read_text("utf-8-sig")
    assert "00:00:00,200 --> 00:00:01,100" in written
    assert "00:00:01,300 --> 00:00:02,400" in written
    assert "第一行保留，逗号\n第二行去感叹号" in written
    assert "里面保留3.14这个小数，句尾去省略号" in written
    assert "。" not in written and "！" not in written and "…" not in written
    assert captions[0].text.endswith("！！")  # source text must stay untouched
    validate_srt_export_punctuation(written)


def test_srt_empty_punctuation_only_cues_are_skipped(tmp_path):
    path = tmp_path / "punct.srt"
    save_srt([Caption(0,1,"？！！"), Caption(1,2,"后面有文字。")],path)
    output = path.read_text("utf-8-sig")
    assert output.startswith("1\n00:00:01,000 --> 00:00:02,000\n后面有文字\n")
    assert "2\n" not in output
    with pytest.raises(ValueError,match="没有有效字幕"):
        save_srt([Caption(0,1,"......")],tmp_path/"empty.srt")
    with pytest.raises(RuntimeError,match="字幕行结尾存在标点"):
        validate_srt_export_punctuation("1\n00:00:00,000 --> 00:00:01,000\n不合规。\n")


def test_standalone_plain_txt_contains_spoken_text_only(tmp_path):
    captions = [Caption(0, 1, "大家好，我是姜律师。"),
                Caption(1, 2, "遇到合同纠纷，\n可以来咨询！")]
    txt = tmp_path/"文案.txt"
    write_plain_script_txt(captions, txt)
    data = txt.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    assert data.decode("utf-8") == "大家好，我是姜律师。\n遇到合同纠纷， 可以来咨询！\n"
    assert "00:00" not in data.decode("utf-8")
    assert "第001段" not in data.decode("utf-8")
    assert "台词：" not in data.decode("utf-8")
    with pytest.raises(ValueError, match="没有可信台词"):
        write_plain_script_txt([Caption(0, 1, " ")], tmp_path/"empty.txt")


def test_cut_boundaries_sentence_priority_and_maximum():
    captions=[Caption(0,5.9,"第一句。"),Caption(5.9,12,"第二句。"),
              Caption(12,17.9,"第三句。")]
    cuts=choose_cuts(17.9,[5.5,13.1],captions,8.0)
    assert cuts == [0, 5.9, 12., 17.9]
    assert all(3 < b-a <= 8 for a,b in zip(cuts,cuts[1:]))


def test_choose_cuts_long_speech_must_hold_not_hard_cut():
    from clipflow.cut_planner import NoFeasibleSegmentation
    with pytest.raises(NoFeasibleSegmentation,match="完整句尾与时长限制"):
        choose_cuts(35.6,[],[Caption(0,35.6,"长语句")],maximum=8.0)


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
