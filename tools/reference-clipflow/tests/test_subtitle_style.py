import json
from pathlib import Path
import shutil
import subprocess

import pytest

from clipflow.cli import Caption, main, media_info, save_srt
from clipflow.subtitle_style import (
    ass_color, create_reference_samples, create_style_template,
    read_style_profile, convert_matched_ass,
)


def example_profile():
    return {
        "schema_version":1, "reference_has_subtitles":True,
        "visually_reviewed":True,
        "source_canvas_width":1080,"source_canvas_height":1920,
        "font_family":"Noto Serif CJK SC",
        "font_size_px":82,"emphasis_size_px":96,
        "letter_spacing_px":4,"position_x_ratio":.5,"position_y_ratio":.52,
        "max_width_ratio":.92,
        "primary_color":"#FFFFFF", "emphasis_color":"#EEDD00",
        "outline_color":"#000000","outline_px":8,
        "shadow_color":"#202020","shadow_px":1,
        "bold":True,
        "highlight_terms":[],
        "caption_styles":{
            "1":{"runs":[{"text":"大家好，","color":"#FFFFFF"},
                         {"text":"我是姜律师","color":"#FF00AA","font_size_px":100}]},
            "2":{"position_y_ratio":.6,"highlight_terms":["合同"],
                 "emphasis_color":"#00FF00"}
        },
    }


def test_pending_must_be_reviewed_and_confirmed_absence_fallback(tmp_path):
    p=tmp_path/"style.json"
    create_style_template(p,1080,1920)
    d=json.loads(p.read_text())
    assert d['reference_has_subtitles'] is None
    assert d['visually_reviewed'] is False
    with pytest.raises(ValueError,match="尚未视觉审核"):
        read_style_profile(p)
    d['visually_reviewed']=True;d['reference_has_subtitles']=False
    p.write_text(json.dumps(d))
    assert read_style_profile(p) is None
    d['reference_has_subtitles']=True
    p.write_text(json.dumps(d))
    with pytest.raises(ValueError,match="缺少"):
        read_style_profile(p)


def test_ass_per_cue_multiple_colors_font_size_and_position(tmp_path):
    p=tmp_path/"style.json"
    profile=example_profile()
    p.write_text(json.dumps(profile,ensure_ascii=False),encoding="utf-8")
    valid=read_style_profile(p)
    sub=tmp_path/"render.ass"
    captions=[Caption(.1,1.5,"大家好，我是姜律师"),Caption(1.5,3.4,"合同风险")]
    convert_matched_ass(captions,sub,1080,1920,valid,[])
    s=sub.read_text(encoding="utf-8-sig")
    assert "Noto Serif CJK SC" in s
    assert "\\fsp4" in s
    assert "\\pos(540,998)" in s  # .52*1920=998.4
    assert "\\pos(540,1152)" in s  # second cue .6*1920
    assert "\\fs100" in s
    assert "\\c&HAA00FF" in s  # RGB #FF00AA -> BGR AA00FF
    assert "\\c&H00FF00" in s  # RGB #00FF00
    assert "律师" in s
    assert ass_color("#102030")=="&H00302010"


def test_multicolor_runs_must_match_caption_text(tmp_path):
    profile=example_profile()
    with pytest.raises(ValueError,match="原文完全一致"):
        convert_matched_ass([Caption(0,1,"字幕不对")],tmp_path/"a.ass",1080,1920,profile,[])


@pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg required')
def test_reference_phase_produces_samples_and_pending_profile(tmp_path):
    input_video=tmp_path/'reference.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
                    'color=c=blue:s=160x288:r=12:d=4.2',
                    '-f','lavfi','-i','sine=frequency=520:duration=4.2',
                    '-c:v','libx264','-c:a','aac','-shortest',str(input_video)],
                   check=True)
    captions=tmp_path/'captions.srt'
    save_srt([Caption(0,1,'你好'),Caption(1,2,'我是律师')],captions)
    out=tmp_path/'reference_project'
    assert main(['reference','--input',str(input_video),'--out',str(out),
                 '--srt',str(captions),'--preset','ultrafast'])==0
    assert (out/'subtitle_samples'/'subtitle_reference_contact.jpg').exists()
    assert (out/'subtitle_samples'/'sample_index.json').exists()
    assert (out/'subtitle_style_profile.json').exists()
    assert json.loads((out/'manifest.json').read_text())['subtitle_style_status']=='pending_visual_review'
    assert (out/'numbered_segments.zip').is_file()
    clips=out/'segments'
    target=tmp_path/'output.mp4'
    # Safety: cannot silently fallback to C/B while reference style is pending.
    assert main(['assemble','--clips-dir',str(clips),
                 '--out',str(target),'--manifest',str(out/'manifest.json'),
                 '--burn-subtitles','--preset','ultrafast'])==2
    assert not target.exists()
    d=json.loads((out/'subtitle_style_profile.json').read_text())
    d.update({'visually_reviewed':True,'reference_has_subtitles':False})
    (out/'subtitle_style_profile.json').write_text(json.dumps(d))
    assert main(['assemble','--clips-dir',str(clips),'--out',str(target),
                 '--manifest',str(out/'manifest.json'),
                 '--burn-subtitles','--preset','ultrafast'])==0
    report=json.loads(target.with_suffix('.report.json').read_text())
    assert report['subtitle_style_source']=='confirmed_no_reference_subtitles_fallback'
    assert report['subtitle_burned'] is True
    assert media_info(target)['duration']>=1.99
