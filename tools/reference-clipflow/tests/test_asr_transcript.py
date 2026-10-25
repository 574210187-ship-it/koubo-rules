"""Offline tests: no Whisper model download or external service required."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import zipfile

import pytest

from clipflow.asr import (TimedText, estimate_character_timing,
                          _captions_from_words, recognize)
from clipflow.transcript import (assign_words_to_segments, write_segment_document,
                                 human_time)
from clipflow.cli import load_srt, main


def _fake_asr(monkeypatch, *, with_words=True):
    fake = ModuleType("faster_whisper")
    track = []

    class WhisperModel:
        def __init__(self, model, device, compute_type):
            track.append(("model", model, device, compute_type))

        def transcribe(self, path, **kwargs):
            assert Path(path).is_file()
            assert kwargs["word_timestamps"] is True
            track.append(("transcribe", kwargs["language"], kwargs["vad_filter"]))
            if with_words:
                spans = [
                    SimpleNamespace(start=0.25,end=0.75,word="大家好，"),
                    SimpleNamespace(start=0.75,end=1.4,word="我是姜律师。"),
                    SimpleNamespace(start=1.45,end=2.25,word="合同纠纷也能咨询。"),
                ]
            else:
                spans = []
            seg = SimpleNamespace(start=0.25,end=2.25,text="大家好，我是姜律师。合同纠纷也能咨询。",words=spans)
            return iter([seg]),SimpleNamespace(language="zh")

    fake.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules,"faster_whisper",fake)
    return track


@pytest.mark.parametrize("part_count",[2,3])
def test_assign_text_exactly_once(part_count):
    spans = [TimedText(0,1,"大家好，"),TimedText(1,2,"我是律师。"),
             TimedText(2,3,"提供法律咨询。")]
    borders = [0,1,2,3] if part_count==3 else [0,1.9,3]
    entries = [dict(index=i+1,file=f"{i+1:03d}.mp4",start=borders[i],end=borders[i+1])
               for i in range(part_count)]
    results = assign_words_to_segments(entries,spans)
    assert "".join(results)=="大家好，我是律师。提供法律咨询。"
    assert len(results)==part_count


def test_srt_character_estimates_split_and_document(tmp_path):
    tokens = estimate_character_timing([TimedText(0,4,"甲乙丙丁")])
    entries = [dict(index=1,file="001_镜头.mp4",start=0,end=2),
               dict(index=2,file="002_镜头.mp4",start=2,end=4)]
    parts = assign_words_to_segments(entries,tokens)
    assert parts==["甲乙","丙丁"]
    dest = tmp_path / "segments_transcript.md"
    write_segment_document(dest,"reference.mp4",4,entries,parts,"supplied_srt","srt_estimated")
    data = dest.read_text("utf-8")
    assert "第001段｜00:00.000—00:02.000｜2.000 秒" in data
    assert "第002段｜00:02.000—00:04.000｜2.000 秒" in data
    assert "**台词：** 甲乙" in data
    assert "**台词：** 丙丁" in data
    assert "非本次自动语音识别" in data
    assert human_time(66.167) == "01:06.167"


def test_phrase_grouped_from_real_word_timestamps():
    cues = _captions_from_words([
        TimedText(0.2,.6,"大家好，"),TimedText(.6,1,"我是律师。"),
        TimedText(2,2.4,"这段再说。")])
    assert [x.text for x in cues] == ["大家好，我是律师。","这段再说。"]
    assert cues[0].start == .2 and cues[0].end == 1


@pytest.mark.skipif(shutil.which("ffmpeg") is None,reason="ffmpeg required")
def test_recognize_word_timestamp_audio_and_no_visible_captions(monkeypatch,tmp_path):
    audio=tmp_path/"speech.wav"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-f","lavfi","-i","sine=frequency=480:duration=2.5",
                    str(audio)],check=True)
    called = _fake_asr(monkeypatch)
    actual = recognize(audio, model="small",device="cpu",language="auto")
    assert actual.alignment == "word_timestamps"
    assert len(actual.words)==3
    assert "".join(x.text for x in actual.words) == "大家好，我是姜律师。合同纠纷也能咨询。"
    assert [x.text for x in actual.captions] == ["大家好，我是姜律师。","合同纠纷也能咨询。"]
    assert ("model","small","cpu","int8") in called
    assert ("transcribe",None,True) in called


@pytest.mark.skipif(shutil.which("ffmpeg") is None,reason="ffmpeg required")
def test_recognize_missing_word_timestamps_explicitly_marks_estimate(monkeypatch,tmp_path):
    audio=tmp_path/"speech.wav"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-f","lavfi","-i","sine=frequency=480:duration=2.5",
                    str(audio)],check=True)
    _fake_asr(monkeypatch,with_words=False)
    actual=recognize(audio)
    assert actual.alignment=="mixed_estimated"
    assert "".join(x.text for x in actual.words) == "大家好，我是姜律师。合同纠纷也能咨询。"


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="ffmpeg/ffprobe required")
def test_reference_with_srt_generates_segment_document_and_archive(tmp_path):
    video=tmp_path/"original.mp4"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-f","lavfi","-i","color=c=navy:s=160x288:r=12:d=2.5",
                    "-f","lavfi","-i","sine=frequency=880:sample_rate=16000:duration=2.5",
                    "-shortest","-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",
                    "-c:a","aac",str(video)],check=True)
    srt=tmp_path/"input.srt"
    srt.write_text("1\n00:00:00,200 --> 00:00:01,100\n法律咨询，\n\n"
                   "2\n00:00:01,300 --> 00:00:02,300\n合同纠纷。\n",encoding="utf-8")
    output=tmp_path/"processed"
    status=main(["reference","--input",str(video),"--out",str(output),
                 "--srt",str(srt),"--max-seconds","2.0","--preset","ultrafast"])
    assert status==0
    assert (output/"captions.srt").is_file()
    assert (output/"segments_transcript.md").is_file()
    manifest=json.loads((output/"manifest.json").read_text())
    assert manifest["version"]=="0.4.1"
    assert manifest["caption_source"]=="supplied_srt"
    assert manifest["transcript_alignment"]=="srt_estimated"
    assert "segments_transcript.md"==manifest["transcript_document"]
    entries=manifest["segments"]
    assert all(x["duration"]<=2.0 for x in entries)
    assert "法律咨询" in "".join(x["transcript"] for x in entries)
    with zipfile.ZipFile(output/"numbered_segments.zip") as z:
        assert len(z.namelist())==len(entries)
    with zipfile.ZipFile(output/"subtitle_reference_stylekit.zip") as z:
        assert "segments_transcript.md" in z.namelist()


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="ffmpeg/ffprobe required")
def test_reference_without_visible_subtitles_uses_fake_asr(monkeypatch,tmp_path):
    video=tmp_path/"bare_video.mp4"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-f","lavfi","-i","color=c=gray:s=160x288:r=12:d=2.5",
                    "-f","lavfi","-i","sine=frequency=880:sample_rate=16000:duration=2.5",
                    "-shortest","-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",
                    "-c:a","aac",str(video)],check=True)
    _fake_asr(monkeypatch)
    output=tmp_path/"processed"
    assert main(["reference","--input",str(video),"--out",str(output),
                 "--max-seconds","2.0","--preset","ultrafast"])==0
    assert "合同纠纷也能咨询" in (output/"segments_transcript.md").read_text("utf-8")
    cues=load_srt(output/"captions.srt")
    assert len(cues)==2
    manifest=json.loads((output/"manifest.json").read_text("utf-8"))
    assert manifest["caption_source"]=="faster_whisper_asr"
    assert manifest["transcript_alignment"]=="word_timestamps"
    assert ''.join(x['transcript'] for x in manifest['segments']) == '大家好，我是姜律师。合同纠纷也能咨询。'
    assert 'reference_has_subtitles' in json.loads((output/"subtitle_style_profile.json").read_text("utf-8"))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_standalone_transcribe_audio(monkeypatch,tmp_path):
    audio=tmp_path/"original_audio.wav"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-f","lavfi","-i","sine=frequency=480:duration=2.5",
                    str(audio)],check=True)
    _fake_asr(monkeypatch)
    assert main(["transcribe","--input",str(audio),"--out",str(tmp_path/"asr")])==0
    assert (tmp_path/"asr/captions.srt").is_file()
    assert "我是姜律师" in (tmp_path/"asr/transcript.md").read_text("utf-8")
