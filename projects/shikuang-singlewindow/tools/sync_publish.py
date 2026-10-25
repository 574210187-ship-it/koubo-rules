#!/usr/bin/env python3
"""Explicit multi-target release from a trusted local host; no implicit background syncing.

Prerequisites: valid GitHub token and/or independent COS credentials in environment.
Do not publish to the COS expression library. Performs binary readback + SHA-256 validation.
No ChatGPT Library API is emulated; update that independently via ChatGPT Files.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, os, pathlib, sys, urllib.request, urllib.error
from datetime import datetime, timezone

def digest(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def github_api(method,api_path,token,payload=None,raw=False):
    url='https://api.github.com'+api_path
    data=json.dumps(payload).encode() if payload is not None else None
    headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'shikuang-sync-publisher'}
    if data is not None:headers['Content-Type']='application/json'
    req=urllib.request.Request(url, data=data, method=method,headers=headers)
    with urllib.request.urlopen(req,timeout=90) as resp:
        value=resp.read()
    return value if raw else json.loads(value)
def gh_sync(blob, repo,branch,path,token,base='main'):
    repo_path='/repos/'+repo
    try:github_api('GET',repo_path+'/git/ref/heads/'+branch,token)
    except urllib.error.HTTPError as e:
        if e.code!=404:raise
        base_ref=github_api('GET',repo_path+'/git/ref/heads/'+base,token)
        github_api('POST',repo_path+'/git/refs',token,{'ref':'refs/heads/'+branch,'sha':base_ref['object']['sha']})
    existing=None
    try: existing=github_api('GET',repo_path+'/contents/'+path+'?ref='+branch,token)
    except urllib.error.HTTPError as e:
        if e.code!=404:raise
    args={'message':'Publish shikuang immutable release '+path,'content':base64.b64encode(blob).decode(),'branch':branch}
    if existing:args['sha']=existing['sha']
    put=github_api('PUT',repo_path+'/contents/'+path,token,args)
    back=github_api('GET',repo_path+'/contents/'+path+'?ref='+branch,token)
    if back.get('encoding')!='base64' or not back.get('content'):
        raise RuntimeError('GITHUB_READBACK_UNAVAILABLE')
    received=base64.b64decode(back['content'])
    if digest(received)!=digest(blob):raise RuntimeError('GITHUB_SHA256_READBACK_MISMATCH')
    return {'state':'READBACK_PASS','sha256':digest(received),'blob_sha':back.get('sha'),'commit':put['commit']['sha'],'url':back.get('html_url')}
def cos_sync(blob,bucket,region,prefix,version):
    # Generic COS: this is NOT the connected expression-image-only COS MCP.
    try:from qcloud_cos import CosConfig,CosS3Client
    except ImportError:raise RuntimeError('COS_SDK_REQUIRED: pip install cos-python-sdk-v5')
    sid=os.getenv('COS_SECRET_ID') or os.getenv('TENCENTCLOUD_SECRET_ID')
    sk=os.getenv('COS_SECRET_KEY') or os.getenv('TENCENTCLOUD_SECRET_KEY')
    if not sid or not sk:raise RuntimeError('COS_CREDENTIALS_UNAVAILABLE')
    client=CosS3Client(CosConfig(Region=region,SecretId=sid,SecretKey=sk,Scheme='https'))
    key=prefix.strip('/')+'/'+version+'.zip'
    # Unique version key, never overwrite an existing different artifact.
    try:
        old=client.get_object(Bucket=bucket,Key=key)
        data=old['Body'].get_raw_stream().read()
        if digest(data)!=digest(blob):raise RuntimeError('COS_KEY_EXISTS_DIFFERENT_CONTENT')
        return {'state':'READBACK_PASS','sha256':digest(data),'bucket':bucket,'region':region,'key':key,'idempotent':True}
    except Exception as e:
        if 'NoSuchKey' not in str(e) and '404' not in str(e):raise
    import io
    client.put_object(Bucket=bucket,Key=key,Body=io.BytesIO(blob),ContentLength=len(blob),ContentType='application/zip')
    obj=client.get_object(Bucket=bucket,Key=key)
    back=obj['Body'].get_raw_stream().read()
    if digest(back)!=digest(blob):raise RuntimeError('COS_SHA256_READBACK_MISMATCH')
    return {'state':'READBACK_PASS','sha256':digest(back),'bucket':bucket,'region':region,'key':key}
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--zip',required=True);p.add_argument('--version',required=True)
    p.add_argument('--github-repo');p.add_argument('--github-branch');p.add_argument('--github-path')
    p.add_argument('--cos-bucket');p.add_argument('--cos-region');p.add_argument('--cos-prefix')
    p.add_argument('--receipt',required=True);a=p.parse_args()
    blob=pathlib.Path(a.zip).read_bytes()
    out={'version':a.version,'source_sha256':digest(blob),'bytes':len(blob),'created_at':datetime.now(timezone.utc).isoformat(),'github':{'state':'NOT_REQUESTED'},'cos':{'state':'NOT_REQUESTED'},'library':{'state':'EXTERNAL_TOOL_REQUIRED'}}
    if a.github_repo:
        try:
            t=os.getenv('GITHUB_TOKEN') or os.getenv('GH_TOKEN')
            if not t:raise RuntimeError('GITHUB_TOKEN_UNAVAILABLE')
            out['github']=gh_sync(blob,a.github_repo,a.github_branch,a.github_path,t)
        except Exception as e:out['github']={'state':'BLOCKED','reason':str(e)}
    if a.cos_bucket:
        try:out['cos']=cos_sync(blob,a.cos_bucket,a.cos_region,a.cos_prefix,a.version)
        except Exception as e:out['cos']={'state':'BLOCKED','reason':str(e)}
    pathlib.Path(a.receipt).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if all(out[k]['state'] in ('READBACK_PASS','NOT_REQUESTED') for k in ('github','cos')) else 3
if __name__=='__main__':raise SystemExit(main())