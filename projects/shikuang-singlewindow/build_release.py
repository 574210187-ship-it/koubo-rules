#!/usr/bin/env python3
"""Immutable, deterministic v1.0.1 sync candidate release builder. Never packages user run data.

Usage: python build_release.py /ABS/PATH/实况视频单窗口_启动包_v0.2.0.zip
"""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parent
VERSION='v1.0.1-sync-candidate'
BLACKLIST={'manifest.json','ZIP_SHA256.txt'}

def sha(b):return hashlib.sha256(b).hexdigest()

def build(out):
    out=Path(out).resolve()
    files=[]
    for p in ROOT.rglob('*'):
        if not p.is_file():continue
        rel=p.relative_to(ROOT).as_posix()
        if any(x.startswith('.') or x in ('__pycache__','runs','.pytest_cache') for x in p.relative_to(ROOT).parts):continue
        if p.suffix=='.pyc' or p.name in BLACKLIST or rel.endswith('_启动包_v0.2.0.zip'):continue
        files.append((rel,p.read_bytes()))
    files.sort()
    manifest={'project':'实况视频单窗口','version':VERSION,'parent_zip_sha256':'75ca06e2ec2fae4174ec67f1d3e19e8a6892c74dc8da832e701b6a81c08efe6e',
              'stage':'CANDIDATE_TECHNICALLY_TESTED_AWAITING_USER_MEDIA_AND_ENGINE_APPROVAL',
              'immutable_files':[{'path':k,'bytes':len(data),'sha256':sha(data)} for k,data in files]}
    ROOT.joinpath('manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    files.append(('manifest.json',ROOT.joinpath('manifest.json').read_bytes()))
    out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,data in files:
            info=zipfile.ZipInfo(name,date_time=(2026,10,25,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16
            z.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED)
    print(json.dumps({'release':str(out),'members':len(files),'sha256':sha(out.read_bytes()),
                      'bytes':out.stat().st_size},ensure_ascii=False))

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python build_release.py /ABS/RELEASE.zip')
    build(sys.argv[1])