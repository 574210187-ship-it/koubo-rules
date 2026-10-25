#!/usr/bin/env python3
"""Read-only material probe for Stage 00. Never guesses semantic scene/roles.
Reads real source bytes, checks ffprobe media streams and PNG basic dimensions;
outputs technical evidence, NOT an approved 00 classification.
"""
from __future__ import annotations
import argparse
import datetime
import json
from pathlib import Path
import struct
import subprocess
import sys
from shikuang import sha, safe_source_file, jwrite, WorkflowError


def probe(path):
    p=safe_source_file(path)
    result={'source_path':str(p),'sha256':sha(p),'size_bytes':p.stat().st_size,
            'suffix':p.suffix.lower(),'kind':'unknown'}
    with p.open('rb') as f:
        prefix=f.read(26)
    if prefix[:8]==b'\x89PNG\r\n\x1a\n' and len(prefix)>=26:
        w,h=struct.unpack('>II', prefix[16:24]);ct=prefix[25]
        result.update(kind='image',image={'format':'png','width':w,'height':h,
                       'png_color_type':ct, 'has_native_alpha_channel': ct in (4,6)})
        return result
    if p.suffix.lower() in ('.jpg','.jpeg','.webp'):
        try:
            from PIL import Image
        except ImportError as e:
            raise WorkflowError('PILLOW_REQUIRED_FOR_IMAGE_PROBE') from e
        try:
            with Image.open(p) as im:
                result.update(kind='image',image={'format':im.format,'width':im.width,
                              'height':im.height,'has_native_alpha_channel': 'A' in im.getbands()})
                im.verify()
        except Exception as e:
            raise WorkflowError('IMAGE_DECODE_FAILED: '+str(e)) from e
        return result
    if p.suffix.lower() in ('.mp4','.mov','.mkv','.webm','.mp3','.m4a','.wav','.aac'):
        try:
            r=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(p)],
                             capture_output=True,text=True,timeout=40)
        except (FileNotFoundError,subprocess.TimeoutExpired) as e:
            raise WorkflowError('MEDIA_PROBE_UNAVAILABLE: '+str(e)) from e
        if r.returncode:
            raise WorkflowError('MEDIA_PROBE_FAILED: '+str(p)+' '+r.stderr[-800:])
        info=json.loads(r.stdout)
        streams=info.get('streams',[])
        videos=[x for x in streams if x.get('codec_type')=='video']
        audios=[x for x in streams if x.get('codec_type')=='audio']
        result['kind']='video' if videos else ('audio' if audios else 'unknown')
        result['media']={'duration_seconds':info.get('format',{}).get('duration'),
                         'video_streams':[{'codec':x.get('codec_name'),'width':x.get('width'),
                                           'height':x.get('height'),'frame_rate':x.get('r_frame_rate')}
                                          for x in videos],
                         'audio_streams':[{'codec':x.get('codec_name'),'sample_rate':x.get('sample_rate')}
                                          for x in audios]}
    return result


def main():
    parser=argparse.ArgumentParser(description='实况单窗口素材00只读技术预检')
    parser.add_argument('sources',nargs='+')
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    try:
        data={'schema_version':1,'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'semantic_classification':'NOT_PERFORMED_REQUIRES_REAL_VISUAL_ANALYSIS',
              'sources':[probe(p) for p in args.sources]}
        jwrite(args.out,data)
        print(json.dumps({'ok':True,'probe_path':args.out,'count':len(data['sources'])},ensure_ascii=False))
    except (WorkflowError,OSError,ValueError) as e:
        print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False),file=sys.stderr)
        return 2
    return 0


if __name__=='__main__':sys.exit(main())