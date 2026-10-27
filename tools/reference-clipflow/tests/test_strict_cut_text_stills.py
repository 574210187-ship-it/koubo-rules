"""User-accepted v0.5.0 hard cutting and first-10-frame minimum text rules."""
import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from clipflow.cli import Caption, main
from clipflow.asr import TimedText
from clipflow.cut_planner import (
    plan_sentence_cuts, verified_sentence_ends, NoFeasibleSegmentation,
    is_sentence_complete,
)
from clipflow.stills import select_opening_frame, export_segment_still
from clipflow.still_text import count_visible_text, ocr_language
from clipflow.cli import drawtext_filter, ffmpeg_font


def caps(ends):
    before=0
    for i,end in enumerate(ends):
        yield Caption(before+0.05,end,f'第{i+1}句完成。')
        before=end


def test_strict_global_planner_prefers_actual_scene_near_full_sentence():
    ends=list(caps([4.2,6.8,10.8,14.5]))
    cuts=plan_sentence_cuts(18,[7.05,14.6],ends)
    assert cuts == [0.0,6.8,14.5,18]
    assert all(3 < b-a <= 8 for a,b in zip(cuts,cuts[1:]))


def test_sentence_cue_midphrase_is_not_boundary_and_long_pause_alone_not_proof():
    entries=[Caption(0,4.2,'如果我们接下来，'),Caption(4.2,8.1,'还没有讲完的一句话'),
             Caption(8.1,14,'现在终于讲完了。')]
    assert verified_sentence_ends(entries,None,14)==[]
    with pytest.raises(NoFeasibleSegmentation):
        plan_sentence_cuts(14,[4.2,8.1],entries)
    assert not is_sentence_complete('前半句话，')
    assert not is_sentence_complete('还有下文；')
    assert is_sentence_complete('终于说完了！”')
    assert is_sentence_complete('That is all.')


def test_short_tail_must_be_solved_globally_not_locally():
    c=list(caps([4.2,8.2,11.9]))
    cuts=plan_sentence_cuts(15,[4.25,11.85],c)
    assert cuts == [0.0,4.2,11.9,15] or cuts == [0.0,8.2,15]
    assert all(3 < b-a <= 8 for a,b in zip(cuts,cuts[1:]))


@pytest.mark.parametrize('duration,candidate,why',[
    (3.,[], '3-second source'),
    (12.,[8.9], 'sentence longer than 8'),
    (11.,[8.], '3-second tail forbidden'),
    (17.,[4.,8.], 'no feasible late sentence end'),
])
def test_impossible_constraints_fail_and_do_not_hard_cut(duration,candidate,why):
    c=list(caps(candidate))
    with pytest.raises(NoFeasibleSegmentation) as ex:
        plan_sentence_cuts(duration,[3.,6.,9.,13.],c)
    assert ex.value.diagnostic()['code']=='NO_FEASIBLE_SENTENCE_CUTS',why


def test_exactly_eight_seconds_allowed_and_three_seconds_disallowed():
    assert plan_sentence_cuts(8,[],[])==[0.,8]
    with pytest.raises(NoFeasibleSegmentation):plan_sentence_cuts(3,[],[])
    assert plan_sentence_cuts(3.5,[],[])==[0.,3.5]
    with pytest.raises(ValueError):plan_sentence_cuts(12,[],[],maximum=9)


def test_words_overlapping_marker_prevent_mid_word_cut():
    c=[Caption(0,6.2,'说完了。'),Caption(6.2,12.4,'第二句。')]
    w=[TimedText(5.8,6.5,'完了。')]
    assert verified_sentence_ends(c,w,12.4)==[]
    with pytest.raises(NoFeasibleSegmentation):plan_sentence_cuts(12.4,[6.2],c,w)


@pytest.mark.skipif(not shutil.which('tesseract'),reason='Tesseract required')
def test_text_detector_counts_actual_letters_and_blank(monkeypatch):
    assert ocr_language().startswith(('chi_sim','HanS'))
    blank=np.full((288,512,3),175,np.uint8)
    one=blank.copy();cv2.putText(one,'TEXT NOTICE',(15,70),cv2.FONT_HERSHEY_SIMPLEX,1.2,(8,8,8),2)
    many=one.copy();cv2.putText(many,'IMPORTANT TERMS',(15,140),cv2.FONT_HERSHEY_SIMPLEX,1.0,(8,8,8),2)
    assert count_visible_text(blank)[0]==0
    assert count_visible_text(many)[0] > count_visible_text(one)[0] > 0


@pytest.mark.skipif(not shutil.which('tesseract'),reason='Tesseract required')
def test_only_first_ten_frames_choose_least_text_then_stamp_number(tmp_path):
    filename=tmp_path/'dynamic_text.mp4'
    writer=cv2.VideoWriter(str(filename),cv2.VideoWriter_fourcc(*'mp4v'),12,(512,288))
    assert writer.isOpened()
    for i in range(25):
        frame=np.full((288,512,3),170,np.uint8)
        if i==0:frame[:]=0
        elif i==1:frame[:]=255
        elif i<9:
            cv2.putText(frame,'TEXT NOTICE',(20,72),cv2.FONT_HERSHEY_SIMPLEX,1.1,(0,0,0),2,cv2.LINE_AA)
            cv2.putText(frame,'IMPORTANT TERMS',(20,144),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,0),2,cv2.LINE_AA)
        elif i==9:pass  # first valid no-text frame in allowed 10
        else:pass # no-text outside first ten must not be selected
        writer.write(frame)
    writer.release()
    pixels,stamp,offset,index,meta=select_opening_frame(filename,0,2,include_details=True)
    assert 2 <= index <= 9
    assert index==9, f'selected {index}, selection {meta}'
    assert meta['visible_text_characters']==0
    assert meta['frames_examined']==10
    assert meta['usable_frames']==8
    img=tmp_path/'001_镜头.jpg'
    detail=export_segment_still(filename,0,2,img,number=1,
                         watermark_filter=drawtext_filter(1,{'width':512,'height':288},ffmpeg_font()))
    assert detail['still_offset_frame_index']==9
    assert detail['still_ocr_language'].startswith(('chi_sim','HanS'))
    assert detail['still_selection_policy'].startswith('fewest_OCR_characters')
    assert img.is_file() and cv2.imread(str(img)).shape[:2]==(288,512)


def test_no_chinese_ocr_must_fail_not_mislabel_as_least_text(monkeypatch,tmp_path):
    import clipflow.stills as stills
    path=tmp_path/"no_ocr.mp4"
    w=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"mp4v"),12,(256,144))
    assert w.isOpened()
    for _ in range(24):w.write(np.full((144,256,3),166,np.uint8))
    w.release()
    monkeypatch.setattr(stills,"ocr_language",lambda: (_ for _ in ()).throw(RuntimeError("需要中文OCR")))
    with pytest.raises(RuntimeError,match="需要中文OCR"):
        stills.select_opening_frame(path,0,2)



@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='ffmpeg required')
def test_full_cli_no_feasible_cuts_writes_conflict_but_no_zip(tmp_path):
    video=tmp_path/'test.mp4';srt=tmp_path/'in.srt';out=tmp_path/'out'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
                    'color=c=gray:s=160x288:r=12:d=12',
                    '-f','lavfi','-i','sine=frequency=400:duration=12',
                    '-shortest','-c:v','libx264','-c:a','aac',str(video)],check=True)
    srt.write_text('1\n00:00:00,000 --> 00:00:09,000\n我还没有讲完这句话\n',encoding='utf-8')
    assert main(['reference','--input',str(video),'--out',str(out),'--srt',str(srt),
                 '--preset','ultrafast'])==2
    conflict=json.loads((out/'cut_conflict.json').read_text())
    assert conflict['code']=='NO_FEASIBLE_SENTENCE_CUTS'
    assert not (out/'ClipFlow_完整交付.zip').exists()
