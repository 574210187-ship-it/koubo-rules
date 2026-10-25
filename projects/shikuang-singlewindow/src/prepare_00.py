#!/usr/bin/env python3
"""00 technical role routing. Visual OCR/layout/revision are the agent's next real steps."""
from pathlib import Path
import argparse,json,sys
from short_static_policy import video_dimensions_and_duration,VIDEO_EXT,IMAGE_EXT
from shikuang import jwrite,sha,safe_source_file,require,WorkflowError


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--main',required=True);p.add_argument('--reference',required=True)
    p.add_argument('--out',required=True);p.add_argument('--clip-start',type=float,default=0)
    p.add_argument('--target-seconds',type=float,default=2.9)
    p.add_argument('--edit',action='append',default=[],help='user native-language request, repeatable')
    a=p.parse_args()
    main=safe_source_file(a.main);ref=safe_source_file(a.reference)
    require(main.suffix.lower() in VIDEO_EXT,'MAIN_VIDEO_REQUIRED')
    if ref.suffix.lower() in IMAGE_EXT:kind='main_video+reference_image'
    elif ref.suffix.lower() in VIDEO_EXT:kind='main_video+reference_video'
    else:raise WorkflowError('REFERENCE_MUST_BE_IMAGE_OR_VIDEO')
    _,_,total=video_dimensions_and_duration(main)
    require(0<=a.clip_start<total,'CLIP_START_INVALID')
    require(0<a.target_seconds<3,'TARGET_NOT_STRICTLY_UNDER_3_SECONDS')
    length=min(a.target_seconds,round(total-a.clip_start-0.001,3))
    require(length>0,'MAIN_TOO_SHORT_TO_CLIP')
    facts={'input_kind':kind,'main_video_path':str(main),'reference_path':str(ref),
           'text_mode':'STATIC_FULL_DURATION','playback':'ORIGINAL_SPEED_TRIM',
           'speed_factor':1.0,'effects':'NONE','text_start_seconds':0,
           'clip_start_seconds':a.clip_start,'clip_duration_seconds':length,
           'audio_policy':'MAIN_ONLY_OR_SILENCE',
           'reference_text':'','final_text':'','layout_evidence':'',
           'reference_layout_kind':'UNREVIEWED',
           'user_edits':[{'instruction':s} for s in a.edit],
           'text_transform_notes':''}
    result={'facts':facts,'evidence':'','source_files':[str(main),str(ref)],
            '_notice':'00 technical draft only. Fill reference_text, final_text, layout_evidence, reference_layout_kind and evidence after actually reviewing reference visuals and applying all user edits. Do not record-00 blank placeholders.'}
    jwrite(a.out,result)
    print(json.dumps({'ok':True,'draft':str(Path(a.out).resolve()),'input_kind':kind,
                      'clip_seconds':length,'visual_analysis':'REQUIRED_BEFORE_RECORD_00'},ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except (WorkflowError,ValueError,OSError) as e:
        print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False),file=sys.stderr)
        sys.exit(2)