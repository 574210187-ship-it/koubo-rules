#!/usr/bin/env python3
"""Hard production gates for the user-approved sub-3-second, never-retimed, static-text workflow.
This module inspects media; it NEVER creates, modifies or draws text images.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import subprocess
from shikuang import WorkflowError, require, safe_source_file

KINDS = ('main_video+reference_image','main_video+reference_video')
VIDEO_EXT = {'.mp4','.mov','.mkv','.webm'}
IMAGE_EXT = {'.png','.jpeg','.jpg','.webp'}


def active(facts):
    return facts.get('input_kind') in KINDS


def media_info(path):
    try:
        r = subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)],
                           capture_output=True,text=True,timeout=45)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise WorkflowError('FFPROBE_REQUIRED: '+str(e)) from e
    require(r.returncode == 0, 'SOURCE_PROBE_FAILED: '+str(path))
    try:
        return json.loads(r.stdout)
    except ValueError as e:
        raise WorkflowError('SOURCE_PROBE_INVALID_JSON') from e


def video_dimensions_and_duration(path):
    info=media_info(path)
    v=next((s for s in info.get('streams',[]) if s.get('codec_type')=='video'),None)
    require(v is not None,'MAIN_VIDEO_STREAM_REQUIRED')
    dur=float(info.get('format',{}).get('duration') or v.get('duration') or 0)
    require(math.isfinite(dur) and dur>0,'MAIN_VIDEO_DURATION_REQUIRED')
    width,height=int(v.get('width') or 0),int(v.get('height') or 0)
    require(width>0 and height>0,'MAIN_VIDEO_DIMENSIONS_REQUIRED')
    # FFmpeg autorotates smartphone portrait inputs on decode; account for display matrix.
    rot=0
    for s in v.get('side_data_list',[]):
        if 'rotation' in s:
            rot=round(float(s['rotation'])/90)*90
    try:
        rot=int(v.get('tags',{}).get('rotate', rot))
    except (ValueError,TypeError):
        pass
    if rot%180!=0:
        width,height=height,width
    return width,height,dur


def check_reference(path,kind):
    ext=path.suffix.lower()
    if kind=='main_video+reference_video':
        require(ext in VIDEO_EXT,'REFERENCE_VIDEO_REQUIRED')
        require(any(x.get('codec_type')=='video' for x in media_info(path).get('streams',[])),
                'REFERENCE_HAS_NO_VIDEO_STREAM')
    else:
        require(ext in IMAGE_EXT,'REFERENCE_IMAGE_REQUIRED')
        try:
            from PIL import Image
        except ImportError as e:
            raise WorkflowError('PILLOW_REQUIRED_FOR_IMAGE_READONLY_VALIDATION') from e
        try:
            with Image.open(path) as im:
                im.verify()
        except Exception as e:
            raise WorkflowError('REFERENCE_IMAGE_CANNOT_DECODE: '+str(e)) from e


def validate_00(data, sources):
    f=data.get('facts',{})
    if not active(f):
        return
    require(len(sources)==2,'STATIC_WORKFLOW_REQUIRES_EXACTLY_TWO_SOURCES')
    require(f.get('text_mode')=='STATIC_FULL_DURATION','STATIC_TEXT_ALWAYS_FULL_DURATION_REQUIRED')
    require(f.get('playback')=='ORIGINAL_SPEED_TRIM','NO_RETIMING_EVER')
    require(f.get('effects')=='NONE','TEXT_EFFECTS_FORBIDDEN')
    require(f.get('reference_layout_kind') in ('SINGLE_STATIC_LAYOUT','REVIEWED_STATIC_LAYOUT'),
            'REFERENCE_LAYOUT_MUST_BE_REVIEWED_AS_STATIC')
    for key in ('reference_text','final_text','layout_evidence'):
        require(isinstance(f.get(key),str) and f[key].strip(),'00_'+key.upper()+'_REQUIRED')
    require(isinstance(f.get('user_edits',[]),list),'00_USER_EDITS_INVALID')
    for edit in f.get('user_edits',[]):
        require(isinstance(edit,dict) and isinstance(edit.get('instruction'),str)
                and edit['instruction'].strip(),'00_USER_EDIT_INSTRUCTION_REQUIRED')
    if f['reference_text'] != f['final_text']:
        require(f.get('user_edits') or (isinstance(f.get('text_transform_notes'),str)
                and f['text_transform_notes'].strip()),'00_TEXT_CHANGE_UNDOCUMENTED')
    require(f.get('audio_policy','MAIN_ONLY_OR_SILENCE')=='MAIN_ONLY_OR_SILENCE',
            'AUDIO_MUST_NOT_COME_FROM_REFERENCE')
    paths={s['path'] for s in sources}
    main,ref=(safe_source_file(f.get(key,'')) for key in ('main_video_path','reference_path'))
    require(str(main) in paths and str(ref) in paths and main!=ref,'00_SOURCE_ROLE_MISMATCH')
    require(main.suffix.lower() in VIDEO_EXT,'MAIN_VIDEO_TYPE_REQUIRED')
    check_reference(ref,f['input_kind'])
    _,_,available=video_dimensions_and_duration(main)
    start=f.get('clip_start_seconds',0)
    length=f.get('clip_duration_seconds',2.9)
    require(type(start) in (int,float) and type(length) in (int,float), 'CLIP_TIMING_NOT_NUMERIC')
    require(math.isfinite(start) and start>=0 and math.isfinite(length) and 0<length<3,
            'CLIP_MUST_BE_SHORTER_THAN_THREE_SECONDS')
    require(start+length <= available+0.015,'CLIP_OUTSIDE_MAIN_VIDEO_NO_STRETCH_OR_LOOP')
    require(float(f.get('speed_factor',1.0))==1.0,'SPEED_FACTOR_MUST_BE_ONE')
    require(float(f.get('text_start_seconds',0.0))==0.0,'TEXT_MUST_BE_VISIBLE_FROM_FIRST_FRAME')


def validate_overlay_png(p,source_id,main_path):
    require(isinstance(source_id,str) and source_id.lower().startswith('imagegen:'),
            'IMAGEGEN_GENERATION_ID_REQUIRED')
    try:
        from PIL import Image
    except ImportError as e:
        raise WorkflowError('PILLOW_REQUIRED_FOR_READONLY_ALPHA_CHECK') from e
    try:
        with Image.open(p) as im:
            require(im.format=='PNG' and im.mode=='RGBA','TEXT_PNG_MUST_BE_RGBA')
            amin,amax=im.getchannel('A').getextrema()
            require(amin==0 and amax>0,'PNG_REQUIRES_REAL_TRANSPARENCY_AND_VISIBLE_TEXT')
            iw,ih=im.size
            vw,vh,_=video_dimensions_and_duration(main_path)
            require(abs(iw/ih-vw/vh) <= 0.015,'PNG_AND_VIDEO_ASPECT_RATIO_MISMATCH')
    except (OSError,ValueError) as e:
        raise WorkflowError('PNG_ALPHA_CHECK_FAILED: '+str(e)) from e


def verify_short_video(path,expected_seconds):
    info=media_info(path)
    videos=[x for x in info.get('streams',[]) if x.get('codec_type')=='video']
    require(videos,'DELIVERY_VIDEO_MISSING')
    vd=float(videos[0].get('duration') or info.get('format',{}).get('duration') or 0)
    fd=float(info.get('format',{}).get('duration') or vd)
    require(vd>0 and vd<3.0 and fd<3.0,'DELIVERY_DURATION_NOT_STRICTLY_LT_3S')
    require(vd >= max(0.1,expected_seconds-0.16), 'DELIVERY_UNEXPECTEDLY_SHORT')
    return {'video_duration':vd,'container_duration':fd}