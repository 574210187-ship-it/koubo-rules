import json
from pathlib import Path
import shutil
import subprocess

import pytest

from clipflow.cli import main, media_info
from clipflow.transcript import assign_cues_to_segments, write_segment_document
from clipflow.visual_ocr import VisualCue, subtitles_from_video, check_ocr


def test_each_segment_one_block_and_time(tmp_path):
    entries = [
        {'index':1,'file':'001_镜头.mp4','start':0.0,'end':3.0},
        {'index':2,'file':'002_镜头.mp4','start':3.0,'end':6.0},
        {'index':3,'file':'003_镜头.mp4','start':6.0,'end':8.0},
    ]
    cues = [VisualCue(0,1.5,'有事请找专业律师'),
            VisualCue(1.5,3.15,'有事请找专业律师'),
            VisualCue(3.01,4.4,'维护自己的合法权益'),
            VisualCue(4.4,5.99,'维护自己的合法权益')]
    scripts = assign_cues_to_segments(entries,cues)
    assert scripts == ['有事请找专业律师','维护自己的合法权益','']
    target=tmp_path/'segments_transcript.md'
    write_segment_document(target,'test.mp4',8.0,entries,scripts,'visual_ocr')
    data=target.read_text(encoding='utf-8')
    assert data.count('**台词：**') == 3
    assert data.count('## 第00') == 3
    assert '## 第001段｜00:00—00:03' in data
    assert '## 第002段｜00:03—00:06' in data
    assert '（本段未检测到可识别画面字幕；口播内容未知）' in data
    assert '语音识别' not in data


def test_no_asr_dependency_or_command(capsys):
    assert main(['doctor']) == 0
    report=json.loads(capsys.readouterr().out)
    assert report['speech_to_text_enabled'] is False
    assert report['audio_asr_dependency_required'] is False
    from clipflow.cli import parser
    p=parser()
    assert 'transcribe' not in p.format_help()


def test_tesseract_presence():
    if shutil.which('tesseract'):
        assert check_ocr()['tesseract']


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('tesseract'),
                    reason='requires ffmpeg, tesseract')
def test_visual_ocr_really_reads_burned_chinese_from_frames(tmp_path):
    import subprocess
    # No audio track at all. The test MUST rely on video-frame text, not speech.
    font='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
    if not Path(font).exists():
        pytest.skip('needs test Chinese font')
    source=tmp_path/'video.mp4'
    filt=f"drawtext=fontfile='{font}':text='有事请找专业律师':fontsize=48:fontcolor=white:borderw=4:bordercolor=black:x=(w-text_w)/2:y=695"
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
                    '-f','lavfi','-i','color=c=#1b2230:s=540x960:r=12:d=1.6',
                    '-vf',filt,'-c:v','libx264','-preset','ultrafast',
                    '-pix_fmt','yuv420p',str(source)],check=True)
    cues,audit=subtitles_from_video(source,1.6,step=.42)
    assert audit['speech_audio_used'] is False
    assert audit['confirmed_visible_subtitle_cues'] >= 1
    assert any('专业律师' in x.text for x in cues)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('tesseract'),
                    reason='requires ffmpeg, tesseract')
def test_reference_no_visible_subtitle_still_delivers_md_and_no_fake_srt(tmp_path):
    # A pure-color clip without text has nothing to transcribe visually.
    clip=tmp_path/'clean.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi',
       '-i','color=c=blue:s=256x448:r=12:d=2.4','-c:v','libx264',
       '-preset','ultrafast','-pix_fmt','yuv420p',str(clip)],check=True)
    out=tmp_path/'output'
    assert main(['reference','--input',str(clip),'--out',str(out),
                 '--max-seconds','1.4','--ocr-interval','.55',
                 '--preset','ultrafast'])==0
    md=(out/'segments_transcript.md').read_text(encoding='utf-8')
    assert md.count('**台词：**') == 2
    assert '口播内容未知' in md
    assert not (out/'captions.srt').exists()
    assert (out/'numbered_segments.zip').exists()
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['caption_source']=='none_visible'
    assert manifest['ocr_audit']['speech_audio_used'] is False
    assert all(x['transcript_status']=='no_visible_subtitles' for x in manifest['segments'])
