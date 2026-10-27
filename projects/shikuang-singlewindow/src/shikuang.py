#!/usr/bin/env python3
"""实况视频单窗口: 00 → three/four ImageGen options → user-selected PNG → MP4+ZIP.
The CLI never generates text graphics or performs OCR. ImageGen and visual reading
run in the ChatGPT host. It verifies artifacts and renders an approved selection.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

VERSION = '1.3.2-conversation-candidate'
SCHEMA = 2

class WorkflowError(Exception):
    pass

def require(condition, code):
    if not condition: raise WorkflowError(code)

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def source(path):
    p = Path(path).expanduser().resolve(strict=True)
    require(p.is_file() and p.stat().st_size > 0, 'FILE_MISSING_OR_EMPTY')
    return p

def json_read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def json_write(path, obj):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)

def probe(path):
    proc=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,timeout=45)
    require(proc.returncode==0,'MEDIA_PROBE_FAILED: '+proc.stderr[-400:])
    return json.loads(proc.stdout)

def video_info(path):
    q=probe(path)
    v=next((x for x in q['streams'] if x['codec_type']=='video'),None)
    require(v is not None,'VIDEO_STREAM_MISSING')
    duration=float(q['format'].get('duration') or v.get('duration') or 0)
    require(math.isfinite(duration) and duration>0,'VIDEO_DURATION_INVALID')
    width,height=int(v['width']),int(v['height'])
    for d in v.get('side_data_list',[]):
        if 'rotation' in d and abs(int(d['rotation']))%180==90: width,height=height,width
    try:
        if abs(int(v.get('tags',{}).get('rotate',0)))%180==90:width,height=height,width
    except ValueError: pass
    return {'width':width,'height':height,'duration':duration,'has_audio':any(x['codec_type']=='audio' for x in q['streams']),
            'fps':v.get('avg_frame_rate','0/0'),'codec':v.get('codec_name')}

def check_png(path, video):
    from PIL import Image
    p=source(path)
    require(p.suffix.lower()=='.png','SELECTED_FILE_MUST_BE_PNG')
    try:
        with Image.open(p) as im:
            require(im.format=='PNG' and im.mode=='RGBA','PNG_MUST_HAVE_RGBA')
            a=im.getchannel('A'); mi,ma=a.getextrema()
            require(mi==0 and ma>0,'PNG_MUST_BE_TRANSPARENT_AND_NONEMPTY')
            w,h=im.size
    except OSError as exc:
        raise WorkflowError('PNG_CANNOT_DECODE: '+str(exc)) from exc
    v=video_info(video)
    require(abs(w/h-v['width']/v['height'])<=0.02,'PNG_VIDEO_ASPECT_RATIO_MISMATCH')
    return {'width':w,'height':h,'sha256':digest(p)}

def state_file(run): return Path(run).resolve()/'state.json'

def open_state(run):
    p=state_file(run)
    require(p.is_file(),'RUN_NOT_FOUND')
    state=json_read(p)
    require(state.get('schema')==SCHEMA,'STATE_SCHEMA_MISMATCH')
    return state,p

def save(state,p): json_write(p,state)

def record_file(p): return {'path':str(p),'sha256':digest(p),'bytes':p.stat().st_size}

def assert_locked(state):
    for key in ('main','reference'):
        old=state['sources'][key]
        cur=source(old['path'])
        require(cur.stat().st_size==old['bytes'] and digest(cur)==old['sha256'],'SOURCE_CHANGED: '+key)

def start(run,main,reference):
    d=Path(run).expanduser().resolve()
    require(not d.exists() or not any(d.iterdir()),'RUN_NOT_EMPTY')
    m=source(main);r=source(reference)
    require(m!=r and digest(m)!=digest(r),'INPUTS_MUST_BE_DISTINCT')
    require(m.suffix.lower() in ('.mp4','.mov','.mkv'),'MAIN_VIDEO_REQUIRED')
    require(r.suffix.lower() in ('.mp4','.mov','.mkv','.png','.jpg','.jpeg','.webp'),'REFERENCE_TYPE_INVALID')
    video_info(m)
    if r.suffix.lower() in ('.mp4','.mov','.mkv'):video_info(r)
    else:
        from PIL import Image
        with Image.open(r) as im: im.verify()
    d.mkdir(parents=True,exist_ok=True)
    s={'schema':SCHEMA,'version':VERSION,'stage':'00_ANALYZE',
       'sources':{'main':record_file(m),'reference':record_file(r)},
       'analysis':None,'options':[],'selected':None,'delivery':None,
       'history':[{'event':'START'}]}
    save(s,state_file(d));return s

def analysis_file_valid(data):
    require(isinstance(data,dict),'ANALYSIS_JSON_REQUIRED')
    text=data.get('text')
    require(isinstance(text,str) and text.strip(),'00_TEXT_REQUIRED')
    require(isinstance(data.get('layout'),str) and data['layout'].strip(),'00_LAYOUT_REQUIRED')
    bbox=data.get('bbox')
    require(isinstance(bbox,list) and len(bbox)==4 and all(isinstance(x,(int,float)) and math.isfinite(x) for x in bbox),
            '00_BBOX_REQUIRED')
    x,y,w,h=bbox
    require(x>=0 and y>=0 and w>0 and h>0 and x+w<=1.001 and y+h<=1.001,'00_BBOX_OUT_OF_RANGE')
    return {'text':text.strip(),'layout':data['layout'].strip(),'bbox':[float(z) for z in bbox],
            'user_edits':str(data.get('user_edits','')).strip()}

def analyze(run,analysis):
    s,p=open_state(run);assert_locked(s)
    require(s['stage']=='00_ANALYZE','STAGE_NOT_00')
    s['analysis']=analysis_file_valid(json_read(analysis))
    s['stage']='00_WAIT_CONFIRM'
    s['history'].append({'event':'00_DONE','manual_confirmation_required':True})
    save(s,p);return s

def approve00(run):
    s,p=open_state(run);assert_locked(s)
    require(s['stage']=='00_WAIT_CONFIRM','NOT_WAITING_00_CONFIRMATION')
    s['stage']='01_NEED_IMAGES';s['history'].append({'event':'00_APPROVED'});save(s,p);return s

def register_options(run,paths,ids):
    s,p=open_state(run);assert_locked(s)
    require(s['stage'] in ('01_NEED_IMAGES','01_WAIT_SELECTION'),'STAGE_NOT_01')
    require(len(paths) in (3,4) and len(ids)==len(paths),'NEED_3_OR_4_IMAGEGEN_OPTIONS')
    require(len(set(ids))==len(ids),'IMAGEGEN_IDS_MUST_BE_UNIQUE')
    allopts=[]
    for i,(path,id_) in enumerate(zip(paths,ids),1):
        require(id_.startswith('imagegen:') and len(id_)>len('imagegen:'),'REAL_IMAGEGEN_GENERATION_ID_REQUIRED')
        x=source(path)
        spec=check_png(x,s['sources']['main']['path'])
        require(all(x!=Path(q['path']) for q in allopts),'DUPLICATE_OPTION_PATH')
        allopts.append({'index':i,'path':str(x),'generation_id':id_,**spec})
    s['options']=allopts;s['selected']=None;s['delivery']=None
    s['stage']='01_WAIT_SELECTION'
    s['history'].append({'event':'01_IMAGES_PRESENTED','count':len(allopts)})
    save(s,p);return s

def select_image(run,path=None,index=None):
    s,p=open_state(run);assert_locked(s)
    require(s['stage'] in ('01_WAIT_SELECTION','02_READY','DONE'),'NO_OPTIONS_TO_SELECT')
    # User re-uploaded selected picture is authoritative, even if chat platform re-encoded
    # bytes; it must nevertheless be a real transparent PNG with the right canvas ratio.
    require((path is None) != (index is None),'SELECT_NEEDS_PNG_OR_INDEX')
    if index is not None:
        require(type(index)==int and 1 <= index <= len(s['options']),'OPTION_INDEX_NOT_FOUND')
        chosen=s['options'][index-1]
        x=source(chosen['path'])
        require(digest(x)==chosen['sha256'],'CHOSEN_OPTION_CHANGED')
        spec=check_png(x,s['sources']['main']['path'])
        selected_by='USER_SELECTED_IMAGEGEN_OPTION'
    else:
        x=source(path);spec=check_png(x,s['sources']['main']['path'])
        selected_by='USER_SELECTED_PNG'
    if s['delivery'] is not None:
        s['history'].append({'event':'PREVIOUS_VIDEO_INVALIDATED','old_output':s['delivery']['mp4']})
    s['selected']={'path':str(x),**spec,'selected_by':selected_by}
    s['delivery']=None;s['stage']='02_READY'
    s['history'].append({'event':'USER_SELECTED_PNG','sha256':spec['sha256']})
    save(s,p);return s

def ffmpeg_render(main,png,mp4):
    v=video_info(main)
    tw,th=(1080,1920) if v['height']>=v['width'] else (1920,1080)
    # Source determines frame timing. No trim, setpts respeed, animation or text drawing.
    base=f'scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1'
    graph=(f'[0:v]format=yuv420p,{base}[main];'
           f'[1:v]format=rgba,scale={tw}:{th}:flags=lanczos[txt];'
           f'[main][txt]overlay=0:0:eof_action=repeat:shortest=0:format=auto,format=yuv420p[v]')
    cmd=['ffmpeg','-nostdin','-y','-loglevel','error','-i',str(main),'-i',str(png),
         '-filter_complex',graph,'-map','[v]']
    if v['has_audio']:cmd+=['-map','0:a:0','-c:a','aac','-b:a','160k']
    else:cmd+=['-an']
    cmd+=['-c:v','libx264','-preset','medium','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(mp4)]
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=900)
    require(result.returncode==0,'RENDER_FAILED: '+result.stderr[-1200:])
    return tw,th

def render(run):
    s,p=open_state(run);assert_locked(s)
    require(s['stage']=='02_READY','NEED_USER_SELECTED_IMAGE')
    sel=s['selected'];img=source(sel['path'])
    require(digest(img)==sel['sha256'],'USER_SELECTED_PNG_CHANGED')
    check_png(img,s['sources']['main']['path'])
    main=source(s['sources']['main']['path']); d=Path(run).resolve()/'outputs'
    d.mkdir(parents=True,exist_ok=True)
    suffix=sum(1 for e in s['history'] if e['event']=='VIDEO_DELIVERED')+1
    # Unique output paths so earlier versions and evidence survive.
    mp4=d/f'final_{suffix:03d}.mp4'; zfile=d/f'final_{suffix:03d}.zip'
    require(not mp4.exists() and not zfile.exists(),'OUTPUT_PATH_ALREADY_EXISTS')
    try:
        tw,th=ffmpeg_render(main,img,mp4)
        v=video_info(main);o=video_info(mp4)
        require((o['width'],o['height'])==(tw,th),'OUTPUT_RESOLUTION_MISMATCH')
        require(abs(v['duration']-o['duration'])<=max(0.15,1/(float(v['fps'].split('/')[0]) or 24)*2),
                'OUTPUT_DURATION_MISMATCH')
        require(v['has_audio']==o['has_audio'],'OUTPUT_AUDIO_MISMATCH')
        dec=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(mp4),'-f','null','-'],
                           capture_output=True,text=True,timeout=900)
        require(dec.returncode==0,'OUTPUT_DECODE_FAILED')
        with zipfile.ZipFile(zfile,'w',zipfile.ZIP_DEFLATED) as z:z.write(mp4,'final_animation.mp4')
        with zipfile.ZipFile(zfile) as z:
            require(z.namelist()==['final_animation.mp4'] and z.testzip() is None,'ZIP_INVALID')
            require(hashlib.sha256(z.read('final_animation.mp4')).hexdigest()==digest(mp4),'ZIP_MP4_SHA_MISMATCH')
        s['delivery']={'mp4':record_file(mp4),'zip':record_file(zfile),
                       'duration_seconds':o['duration'],'resolution':[tw,th],
                       'audio_from_main':v['has_audio']}
        s['stage']='DONE';s['history'].append({'event':'VIDEO_DELIVERED','mp4':str(mp4),'zip':str(zfile)})
        save(s,p)
    except Exception:
        # Do not promote partial outputs, leave user selection intact for retry.
        if mp4.exists():mp4.unlink()
        if zfile.exists():zfile.unlink()
        raise
    return s

def handle():
    a=argparse.ArgumentParser(description='实况: 00分析→3~4图片供选→发选中图生成MP4和ZIP')
    sub=a.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('init');p.add_argument('--run-dir',required=True);p.add_argument('--main',required=True);p.add_argument('--reference',required=True)
    p=sub.add_parser('analyze');p.add_argument('--run-dir',required=True);p.add_argument('--analysis',required=True)
    p=sub.add_parser('approve-00');p.add_argument('--run-dir',required=True)
    p=sub.add_parser('options');p.add_argument('--run-dir',required=True);p.add_argument('--png',action='append',required=True);p.add_argument('--imagegen-id',action='append',required=True)
    p=sub.add_parser('select');p.add_argument('--run-dir',required=True);g=p.add_mutually_exclusive_group(required=True);g.add_argument('--png');g.add_argument('--index',type=int)
    for name in ('render','status'):p=sub.add_parser(name);p.add_argument('--run-dir',required=True)
    args=a.parse_args()
    try:
        if args.cmd=='init':s=start(args.run_dir,args.main,args.reference)
        elif args.cmd=='analyze':s=analyze(args.run_dir,args.analysis)
        elif args.cmd=='approve-00':s=approve00(args.run_dir)
        elif args.cmd=='options':s=register_options(args.run_dir,args.png,args.imagegen_id)
        elif args.cmd=='select':s=select_image(args.run_dir,path=args.png,index=args.index)
        elif args.cmd=='render':s=render(args.run_dir)
        else:s,_=open_state(args.run_dir)
        print(json.dumps({'stage':s['stage'],'options_count':len(s['options']),
                          'selected':s['selected'],'delivery':s['delivery']},ensure_ascii=False,indent=2))
        return 0
    except (WorkflowError,OSError,ValueError,subprocess.TimeoutExpired) as exc:
        print('STOP_CURRENT_STAGE: '+str(exc),file=sys.stderr)
        return 2
if __name__=='__main__':raise SystemExit(handle())