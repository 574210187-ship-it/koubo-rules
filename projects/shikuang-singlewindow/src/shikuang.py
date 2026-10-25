#!/usr/bin/env python3
"""实况视频单窗口 v0.2.0 可执行内核。只读校验素材，原位状态机、
证据链、确定性分流、单项依赖返工、强制门禁、SHA固定引擎执行和交付验收。
不内置任何项目特定业务路由；无真实批准引擎时 fail closed。"""
from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

SCHEMA = 1
PHASES = {'NEED_00', 'WAITING_ROUTE_RULES', 'AWAIT_00_APPROVAL',
          'NEED_STAGE', 'AWAIT_STAGE_APPROVAL', 'READY_ENGINE',
          'RENDERED', 'AWAIT_DELIVERY_APPROVAL', 'COMPLETED', 'BLOCKED'}


class WorkflowError(Exception):
    pass


def require(cond, msg):
    if not cond:
        raise WorkflowError(msg)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def jread(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def jwrite(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # atomic replace; no partial state on failure
    fd, temp = tempfile.mkstemp(prefix='.tmp_', suffix='.json', dir=str(p.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, p)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(obj):
    return hashlib.sha256(canonical(obj).encode('utf-8')).hexdigest()


def config_path(root, filename):
    p = (Path(root) / 'config' / filename).resolve()
    require(p.is_file(), f'CONFIG_NOT_FOUND: {filename}')
    return p


def safe_source_file(path):
    p = Path(path).expanduser().resolve(strict=True)
    require(p.is_file() and p.stat().st_size > 0, f'FILE_MISSING_OR_EMPTY: {path}')
    return p


def valid_run_id(value):
    require(value and len(value) <= 80 and all(c.isalnum() or c in '-_.' for c in value), 'INVALID_RUN_ID')
    return value


def state_path(run_dir):
    return Path(run_dir).resolve() / 'state.json'


def load(run_dir):
    p = state_path(run_dir)
    require(p.is_file(), 'RUN_NOT_FOUND')
    s = jread(p)
    require(s.get('schema_version') == SCHEMA, 'SCHEMA_MISMATCH_NO_IMPLICIT_MIGRATION')
    require(s.get('phase') in PHASES, 'STATE_INVALID_PHASE')
    return s, p


def event(s, name, **facts):
    s['history'].append({'at': now(), 'event': name, **facts})


def write(s, p):
    s['updated_at'] = now()
    jwrite(p, s)


def init(run_dir, run_id, mode):
    valid_run_id(run_id)
    require(mode in ('REVIEW', 'AUTO'), 'INVALID_MODE')
    p = state_path(run_dir)
    require(not p.exists(), 'RUN_EXISTS_NEVER_RESET_OR_OVERWRITE')
    require(not p.parent.exists() or not any(p.parent.iterdir()), 'RUN_DIRECTORY_MUST_BE_EMPTY')
    p.parent.mkdir(parents=True, exist_ok=True)
    s = {'schema_version': SCHEMA, 'run_id': run_id, 'mode': mode,
         'phase': 'NEED_00', 'analysis': None, 'analysis_file_hash': None,
         'route_id': None, 'route_config_sha256': None, 'engine_registry_sha256': None,
         'engine_id': None, 'stages': [], 'analysis_approved': False,
         'current_stage': None, 'render': None, 'delivery': None,
         'manual_review_due_to_rework': False, 'revision_history': [],
         'retired_artifacts': [], 'blocked': None, 'history': []}
    event(s, 'INITIALIZED', mode=mode)
    write(s, p)
    return s


def validate_00(data):
    require(isinstance(data, dict) and isinstance(data.get('facts'), dict), '00_FACTS_REQUIRED')
    require(bool(data['facts']), '00_FACTS_EMPTY')
    require(isinstance(data.get('evidence'), str) and data['evidence'].strip(), '00_EVIDENCE_REQUIRED')
    src = data.get('source_files')
    require(isinstance(src, list) and len(src) > 0, '00_SOURCE_FILES_REQUIRED')
    records = []
    for item in src:
        require(isinstance(item, str), '00_SOURCE_FILE_PATH_INVALID')
        p = safe_source_file(item)
        records.append({'path': str(p), 'sha256': sha(p), 'bytes': p.stat().st_size})
    from short_static_policy import validate_00 as validate_static_00
    validate_static_00(data, records)
    return {'facts': copy.deepcopy(data['facts']), 'evidence': data['evidence'], 'sources': records}


def ensure_sources(s):
    for x in s['analysis']['sources']:
        p = safe_source_file(x['path'])
        require(p.stat().st_size == x['bytes'] and sha(p) == x['sha256'],
                'SOURCE_CHANGED_SINCE_00: ' + x['path'])


def route_structure(rule):
    require(isinstance(rule, dict) and isinstance(rule.get('id'), str) and rule['id'], 'ROUTE_ID_REQUIRED')
    require(isinstance(rule.get('match'), dict) and bool(rule['match']), 'ROUTE_MATCH_REQUIRED')
    stages = rule.get('stages')
    require(isinstance(stages, list) and stages, 'ROUTE_STAGES_REQUIRED')
    stage_ids, artifact_keys = set(), set()
    # all dependencies MUST point to an earlier stage or earlier artifact in the same stage
    for st in stages:
        require(isinstance(st.get('id'), str) and st['id'] and ':' not in st['id'], 'STAGE_ID_INVALID')
        require(st['id'] not in stage_ids, 'DUPLICATE_STAGE_ID')
        stage_ids.add(st['id'])
        artifacts = st.get('artifacts')
        require(isinstance(artifacts, list) and artifacts, 'STAGE_ARTIFACTS_REQUIRED')
        for spec in artifacts:
            n = spec.get('name')
            require(isinstance(n, str) and n and ':' not in n, 'ARTIFACT_NAME_INVALID')
            key = f"{st['id']}:{n}"
            require(key not in artifact_keys, 'DUPLICATE_ARTIFACT_KEY')
            requires = spec.get('depends_on', [])
            require(isinstance(requires, list) and all(isinstance(k, str) and k in artifact_keys for k in requires),
                    'ARTIFACT_DEPENDENCY_NOT_PREVIOUSLY_DEFINED: ' + key)
            require(spec.get('file_type', 'any') in ('any', 'png', 'video', 'audio', 'json'), 'FILE_TYPE_UNSUPPORTED')
            artifact_keys.add(key)
    require(isinstance(rule.get('engine_id'), str) and rule['engine_id'], 'ENGINE_ID_REQUIRED')
    return stages


def routing(root, facts):
    path = config_path(root, 'routes.json')
    cfg = jread(path)
    require(cfg.get('schema_version') == SCHEMA and isinstance(cfg.get('routes'), list), 'ROUTE_CONFIG_INVALID')
    rules = cfg['routes']
    ids = [r.get('id') for r in rules]
    require(len(ids) == len(set(ids)), 'ROUTE_ID_COLLISION')
    for r in rules:
        route_structure(r)
    found = [r for r in rules if all(facts.get(k) == v for k,v in r['match'].items())]
    require(len(found) <= 1, 'ROUTING_AMBIGUOUS_STOP')
    return (found[0] if found else None), sha(path)


def resolve_route(s, root):
    require(s['analysis'] is not None, '00_NOT_RECORDED')
    ensure_sources(s)
    route, fingerprint = routing(root, s['analysis']['facts'])
    if route is None:
        s['phase'] = 'WAITING_ROUTE_RULES'
        s['route_id'] = None
        s['route_config_sha256'] = None
        event(s, 'ROUTING_WAITING_FOR_APPROVED_RULE', facts=s['analysis']['facts'])
        return
    require(not s['stages'] or s['route_id'] == route['id'], 'ROUTE_CHANGE_REQUIRES_NEW_RUN')
    require(not s['stages'] or s['route_config_sha256'] == fingerprint, 'ROUTE_RULES_CHANGED_MID_RUN_STOP')
    engine_fp = sha(config_path(root,'engines.json'))
    if s['stages']:
        require(s['engine_registry_sha256'] == engine_fp, 'ENGINE_REGISTRY_CHANGED_MID_RUN_STOP')
    else:
        s['stages'] = [{'id': st['id'], 'expected': copy.deepcopy(st['artifacts']),
                       'artifacts': {}, 'approved': False, 'approval_sha256': None,
                       'reported_sha256': None, 'needs_manual_approval': False}
                       for st in route['stages']]
    s['route_id'] = route['id']
    s['route_config_sha256'] = fingerprint
    s['engine_registry_sha256'] = engine_fp
    s['engine_id'] = route['engine_id']
    s['phase'] = 'AWAIT_00_APPROVAL' if s['mode'] == 'REVIEW' else 'NEED_STAGE'
    s['current_stage'] = None if s['mode'] == 'REVIEW' else s['stages'][0]['id']
    event(s, 'ROUTED', route=s['route_id'], route_hash=fingerprint)


def record_00(s, root, result):
    require(s['phase'] == 'NEED_00', '00_STAGE_LOCKED')
    p = safe_source_file(result)
    s['analysis'] = validate_00(jread(p))
    s['analysis_file_hash'] = sha(p)
    event(s, '00_RECORDED', source_sha=s['analysis_file_hash'])
    resolve_route(s, root)


def assert_config(s, root):
    if s['route_config_sha256']:
        require(sha(config_path(root,'routes.json')) == s['route_config_sha256'], 'ROUTING_CONFIG_CHANGED_STOP')
        require(sha(config_path(root,'engines.json')) == s['engine_registry_sha256'], 'ENGINE_REGISTRY_CHANGED_STOP')
    if s['analysis']:
        ensure_sources(s)


def stage_by_id(s, name):
    for st in s['stages']:
        if st['id'] == name:
            return st
    raise WorkflowError('UNKNOWN_STAGE: ' + str(name))


def artifact_spec(st, name):
    for spec in st['expected']:
        if spec['name'] == name:
            return spec
    raise WorkflowError('UNDECLARED_ARTIFACT: ' + name)


def check_type(path, file_type):
    if file_type == 'any': return
    ext = {'png':('.png',), 'video':('.mp4','.mov','.mkv'),
           'audio':('.mp3','.wav','.m4a','.aac'), 'json':('.json',)}[file_type]
    require(path.suffix.lower() in ext, f'ARTIFACT_TYPE_MISMATCH: {path}')
    if file_type == 'png':
        with path.open('rb') as f:
            require(f.read(8) == b'\x89PNG\r\n\x1a\n', 'PNG_BAD_SIGNATURE')
    if file_type == 'json':
        require(isinstance(jread(path), (dict,list)), 'JSON_BAD_CONTENT')


def check_record(rec, file_type):
    p = safe_source_file(rec['path'])
    require(p.stat().st_size == rec['bytes'] and sha(p) == rec['sha256'],
            f'ARTIFACT_SHA_CHANGED_STOP: {p}')
    check_type(p, file_type)
    require(rec.get('qa_passed') is True and rec.get('qa_by') and rec.get('qa_note'),
            'QA_EVIDENCE_REQUIRED')


def all_existing_valid(s):
    for st in s['stages']:
        for spec in st['expected']:
            record = st['artifacts'].get(spec['name'])
            if record:
                check_record(record, spec.get('file_type', 'any'))


def artifact_digest(st):
    return digest({spec['name']: st['artifacts'][spec['name']]['sha256'] for spec in st['expected']})


def record_artifact(s, root, stage_id, name, filepath, qa_by, qa_note, source_id):
    assert_config(s, root)
    require(s['phase'] == 'NEED_STAGE' and s['current_stage'] == stage_id, 'CURRENT_STAGE_REQUIRED')
    st = stage_by_id(s,stage_id)
    require(not st['approved'], 'STAGE_ALREADY_APPROVED')
    spec = artifact_spec(st,name)
    require(qa_by.strip() and qa_note.strip() and source_id.strip(), 'QA_OR_PROVENANCE_REQUIRED')
    p = safe_source_file(filepath)
    check_type(p, spec.get('file_type', 'any'))
    from short_static_policy import active, validate_overlay_png
    if active(s['analysis']['facts']):
        require(stage_id=='01_TEXT' and name=='text_rgba','STATIC_ROUTE_ONLY_ACCEPTS_IMAGEGEN_TEXT')
        validate_overlay_png(p,source_id,s['analysis']['facts']['main_video_path'])
    for dep in spec.get('depends_on', []):
        other_stage, other_name = dep.split(':', 1)
        ds = stage_by_id(s, other_stage)
        require(other_name in ds['artifacts'], 'ARTIFACT_DEPENDENCY_MISSING: ' + dep)
        dr = ds['artifacts'][other_name]
        check_record(dr, artifact_spec(ds, other_name).get('file_type','any'))
    previous = st['artifacts'].get(name)
    if previous is not None:
        raise WorkflowError('ARTIFACT_ALREADY_RECORDED_USE_REVISE_FIRST')
    identities = [(a['sha256'], a['source_id'], a['path']) for z in s['stages'] for a in z['artifacts'].values()]
    identities += [(a['sha256'], a['source_id'], a['path']) for a in s['retired_artifacts']]
    require(sha(p) not in {x[0] for x in identities}, 'DUPLICATE_ARTIFACT_BYTES_STOP')
    require(source_id not in {x[1] for x in identities}, 'DUPLICATE_SOURCE_ID_STOP')
    require(str(p) not in {x[2] for x in identities}, 'REUSED_OLD_PATH_STOP')
    rec = {'path': str(p), 'bytes': p.stat().st_size, 'sha256': sha(p),
           'source_id': source_id, 'qa_passed': True,
           'qa_by': qa_by, 'qa_note': qa_note, 'recorded_at': now(),
           'depends_on_hashes': {d: stage_by_id(s,d.split(':',1)[0])['artifacts'][d.split(':',1)[1]]['sha256']
                                 for d in spec.get('depends_on', [])}}
    st['artifacts'][name] = rec
    event(s,'ARTIFACT_RECORDED',stage=stage_id,artifact=name,sha256=rec['sha256'])


def report_stage(s, root, stage_id):
    assert_config(s,root)
    require(s['phase'] == 'NEED_STAGE' and s['current_stage'] == stage_id, 'CURRENT_STAGE_REQUIRED')
    st = stage_by_id(s,stage_id)
    for spec in st['expected']:
        require(spec['name'] in st['artifacts'], 'STAGE_ARTIFACTS_MISSING: ' + spec['name'])
        check_record(st['artifacts'][spec['name']], spec.get('file_type', 'any'))
        for dep, locked_hash in st['artifacts'][spec['name']]['depends_on_hashes'].items():
            prev_stage, prev_name=dep.split(':',1)
            require(stage_by_id(s,prev_stage)['artifacts'][prev_name]['sha256'] == locked_hash,
                    'DEPENDENCY_CHANGED_STOP: ' + dep)
    st['reported_sha256'] = artifact_digest(st)
    if s['mode']=='REVIEW' or st['needs_manual_approval']:
        s['phase']='AWAIT_STAGE_APPROVAL'
    else:
        st['approved']=True
        st['approval_sha256']=st['reported_sha256']
        advance(s)
    event(s,'STAGE_QA_PASSED',stage=stage_id,sha256=st['reported_sha256'])


def advance(s):
    for st in s['stages']:
        if not st['approved']:
            s['current_stage'] = st['id']
            s['phase'] = 'NEED_STAGE'
            return
    s['current_stage'] = None
    s['phase'] = 'READY_ENGINE'


def approve(s, root, gate, confirmation):
    require(isinstance(confirmation,str) and confirmation.strip(), 'EXPLICIT_APPROVAL_TEXT_REQUIRED')
    assert_config(s,root)
    if gate=='00':
        require(s['phase']=='AWAIT_00_APPROVAL', '00_APPROVAL_NOT_EXPECTED')
        s['analysis_approved']=True
        advance(s)
    elif gate=='stage':
        require(s['phase']=='AWAIT_STAGE_APPROVAL', 'STAGE_APPROVAL_NOT_EXPECTED')
        st=stage_by_id(s,s['current_stage'])
        require(st['reported_sha256'] == artifact_digest(st),'STAGE_REPORT_OUTDATED')
        for spec in st['expected']:
            check_record(st['artifacts'][spec['name']], spec.get('file_type','any'))
        st['approved']=True
        st['approval_sha256']=st['reported_sha256']
        st['needs_manual_approval']=False
        advance(s)
    elif gate=='delivery':
        require(s['phase']=='AWAIT_DELIVERY_APPROVAL', 'DELIVERY_APPROVAL_NOT_EXPECTED')
        verify_delivery(s,root)
        s['delivery']['approved']=True
        s['phase']='COMPLETED'
    else:
        raise WorkflowError('UNKNOWN_APPROVAL_GATE')
    event(s,'USER_APPROVED',gate=gate,confirmation=confirmation)


def descendants(s, start_key):
    found = {start_key}
    while True:
        old = len(found)
        for st in s['stages']:
            for spec in st['expected']:
                key = f"{st['id']}:{spec['name']}"
                if set(spec.get('depends_on',[])) & found:
                    found.add(key)
        if len(found)==old: return found


def revise(s, root, stage_id, name, instruction, invalidate_delivery=False):
    assert_config(s,root)
    require(instruction.strip(), 'REVISION_INSTRUCTION_REQUIRED')
    require(s['analysis'] is not None and s['stages'], 'NO_STAGE_TO_REVISE')
    require(s['phase'] not in ('NEED_00','WAITING_ROUTE_RULES','AWAIT_00_APPROVAL'), 'REVISION_NOT_YET_AVAILABLE')
    require(s['phase']!='BLOCKED' or s['blocked']['previous'] not in ('NEED_00','WAITING_ROUTE_RULES'), 'BLOCKED_AT_00')
    if s['phase'] in ('RENDERED','AWAIT_DELIVERY_APPROVAL','COMPLETED'):
        require(invalidate_delivery, 'RENDERED_RESULT_EXISTS_REQUIRE_EXPLICIT_INVALIDATE_DELIVERY')
    st=stage_by_id(s,stage_id)
    artifact_spec(st,name)
    require(name in st['artifacts'], 'REVISION_TARGET_NOT_RECORDED')
    affected=descendants(s, f'{stage_id}:{name}')
    removed=[]
    for st2 in s['stages']:
        for spec in st2['expected']:
            key=f"{st2['id']}:{spec['name']}"
            if key in affected:
                rec=st2['artifacts'].pop(spec['name'], None)
                if rec:
                    removed.append({'key':key,'old_sha256':rec['sha256'],'source_id':rec['source_id']})
                    s['retired_artifacts'].append(rec)
                st2['approved']=False
                st2['reported_sha256']=None
                st2['approval_sha256']=None
                st2['needs_manual_approval']=True
    if s['render'] is not None or s['delivery'] is not None:
        s['revision_history'].append({'at':now(),'invalidated_render':copy.deepcopy(s['render']),
                                      'invalidated_delivery':copy.deepcopy(s['delivery'])})
        s['render']=None
        s['delivery']=None
    s['revision_history'].append({'at':now(),'user_instruction':instruction,'root':f'{stage_id}:{name}',
                                  'invalidated':removed})
    s['manual_review_due_to_rework']=True
    s['blocked']=None
    advance(s)
    event(s,'REVISION_REQUESTED',target=f'{stage_id}:{name}',affected=sorted(affected),
          original_user_instruction=instruction)


def verified_inputs(s, root):
    assert_config(s,root)
    require(s['phase']=='READY_ENGINE','ALL_STAGES_MUST_BE_APPROVED_FIRST')
    all_existing_valid(s)
    files={}
    for st in s['stages']:
        require(st['approved'] and st['approval_sha256'] == artifact_digest(st), 'STAGE_NOT_APPROVED_OR_STALE')
        for spec in st['expected']:
            rec=st['artifacts'][spec['name']]
            for dep, locked_hash in rec['depends_on_hashes'].items():
                ds, dn = dep.split(':', 1)
                require(stage_by_id(s,ds)['artifacts'][dn]['sha256']==locked_hash,'STALE_DEPENDENCY')
            files[f"{st['id']}:{spec['name']}"]={'path':rec['path'],'sha256':rec['sha256']}
    return files


def approved_engine(s, root):
    cfg = jread(config_path(root,'engines.json'))
    require(cfg.get('schema_version')==1 and isinstance(cfg.get('engines'),list),'ENGINE_REGISTRY_INVALID')
    entries=[e for e in cfg['engines'] if e.get('id') == s['engine_id']]
    require(len(entries)==1,'ENGINE_NOT_APPROVED_OR_DUPLICATE')
    e=entries[0]
    require(e.get('status')=='APPROVED', 'ENGINE_NOT_APPROVED')
    require(isinstance(e.get('sha256'),str) and len(e['sha256'])==64,'ENGINE_SHA_REQUIRED')
    path=(Path(root)/e['zip_path']).resolve()
    require(path.is_relative_to(Path(root).resolve()),'ENGINE_PATH_ESCAPE')
    require(path.is_file() and sha(path)==e['sha256'],'ENGINE_ZIP_CHANGED_OR_MISSING')
    require(isinstance(e.get('command'),list) and e['command'] and all(isinstance(t,str) for t in e['command']),
            'ENGINE_COMMAND_INVALID')
    outputs=e.get('outputs')
    require(isinstance(outputs,list) and outputs and all(isinstance(t,dict) and t.get('name') and t.get('file_type','any') in ('any','png','video','audio','json') for t in outputs),'ENGINE_OUTPUTS_INVALID')
    return e,path


def safe_extract_zip(archive, directory):
    # signed ZIP is still treated as potentially unsafe at extraction time
    with zipfile.ZipFile(archive,'r') as z:
        entries=z.infolist()
        require(entries and len(entries) <= 5000, 'ENGINE_ZIP_ENTRY_COUNT_UNSAFE')
        require(sum(x.file_size for x in entries) <= 1_000_000_000, 'ENGINE_ZIP_TOO_LARGE')
        for m in entries:
            rel=PurePosixPath(m.filename)
            require(not rel.is_absolute() and not any(x in ('..','') for x in rel.parts)
                    and not m.filename.startswith(('\\','/')) and ':' not in m.filename,
                    'ENGINE_ZIP_PATH_UNSAFE')
            kind=(m.external_attr>>16) & 0o170000
            require(kind not in (stat.S_IFLNK,stat.S_IFCHR,stat.S_IFBLK,stat.S_IFIFO,stat.S_IFSOCK),
                    'ENGINE_ZIP_SPECIAL_FILE_UNSAFE')
        require(z.testzip() is None,'ENGINE_ZIP_CRC_FAILURE')
        z.extractall(directory)


def render(s, root, run_dir):
    inputs=verified_inputs(s,root)
    engine,arch=approved_engine(s,root)
    attempts_root=Path(run_dir).resolve()/'engine_runs'
    attempts_root.mkdir(exist_ok=True)
    attempt=1
    while (attempts_root/f'attempt-{attempt:04d}').exists():
        attempt+=1
    base=attempts_root/f'attempt-{attempt:04d}'
    base.mkdir()
    workspace=base/'bundle'
    workspace.mkdir()
    safe_extract_zip(arch,workspace)
    out=base/'output'
    out.mkdir()
    job={'project':'实况视频单窗口','run_id':s['run_id'],'route':s['route_id'],
         'engine_id':s['engine_id'],'input_files':inputs,
         'analysis_facts':s['analysis']['facts'],
         'analysis_sources':s['analysis']['sources']}
    jobpath=base/'job.json'
    jwrite(jobpath,job)
    allowed={'{python}':sys.executable,'{job}':str(jobpath),'{out}':str(out)}
    argv=[]
    for token in engine['command']:
        argv.append(allowed.get(token,token))
    require(argv[0] == sys.executable, 'ENGINE_COMMAND_MUST_START_WITH_{python}')
    require(len(argv)>=2 and not argv[1].startswith('-'),'ENGINE_ENTRY_SCRIPT_REQUIRED')
    entry=(workspace/argv[1]).resolve()
    require(entry.is_relative_to(workspace) and entry.is_file(), 'ENGINE_ENTRY_NOT_WITHIN_ZIP')
    argv[1]=str(entry)
    try:
        result=subprocess.run(argv, cwd=workspace, shell=False, capture_output=True, text=True, timeout=900)
    except (OSError,subprocess.TimeoutExpired) as e:
        raise WorkflowError('ENGINE_EXECUTION_FAILED: '+str(e)) from e
    (base/'stdout.log').write_text(result.stdout[-250000:],encoding='utf-8')
    (base/'stderr.log').write_text(result.stderr[-250000:],encoding='utf-8')
    require(result.returncode==0,'ENGINE_RETURNED_NONZERO: '+str(result.returncode))
    output_records=[]
    for spec in engine['outputs']:
        name=spec['name']
        require(isinstance(name,str) and name and Path(name).name==name,'ENGINE_OUTPUT_NAME_INVALID')
        output_path=safe_source_file(out/name)
        check_type(output_path,spec.get('file_type','any'))
        output_records.append({'name':name,'path':str(output_path),
                               'sha256':sha(output_path),'bytes':output_path.stat().st_size,
                               'file_type':spec.get('file_type','any')})
    s['render']={'at':now(),'engine_id':s['engine_id'],'bundle_sha256':sha(arch),
                 'job_sha256':sha(jobpath),'attempt':attempt,'outputs':output_records}
    s['phase']='RENDERED'
    event(s,'ENGINE_RENDERED',engine=s['engine_id'],outputs=[x['sha256'] for x in output_records])


def ffprobe(path):
    try:
        r=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',path],
                         capture_output=True,text=True,timeout=40)
    except (OSError,subprocess.TimeoutExpired) as e:
        raise WorkflowError('FFPROBE_REQUIRED: '+str(e)) from e
    require(r.returncode==0,'MEDIA_PROBE_FAILED: '+str(path))
    m=json.loads(r.stdout)
    require(any(x.get('codec_type')=='video' for x in m.get('streams',[])), 'VIDEO_STREAM_MISSING')
    return m


def verify_delivery(s,root):
    assert_config(s,root)
    require(s['render'] is not None, 'NO_RENDER')
    for x in s['render']['outputs']:
        p=safe_source_file(x['path'])
        require(sha(p)==x['sha256'] and p.stat().st_size==x['bytes'],'RENDERED_FILE_CHANGED_STOP')
        if x['file_type']=='video':
            ffprobe(str(p))
            from short_static_policy import active, verify_short_video
            if active(s['analysis']['facts']):
                verify_short_video(str(p), float(s['analysis']['facts'].get('clip_duration_seconds',2.9)))
    if s['delivery']:
        require(s['delivery']['render_fingerprint']==digest(s['render']),'DELIVERY_STALE')


def accept_delivery(s,root,qa_by,qa_note):
    require(s['phase']=='RENDERED','DELIVERY_QA_STAGE_REQUIRED')
    require(qa_by.strip() and qa_note.strip(),'DELIVERY_VISUAL_QA_EVIDENCE_REQUIRED')
    verify_delivery(s,root)
    s['delivery']={'render_fingerprint':digest(s['render']), 'qa_by':qa_by,
                   'qa_note':qa_note,'approved':False,'at':now()}
    if s['mode']=='REVIEW' or s['manual_review_due_to_rework']:
        s['phase']='AWAIT_DELIVERY_APPROVAL'
    else:
        s['delivery']['approved']=True
        s['phase']='COMPLETED'
    event(s,'DELIVERY_QA_PASSED',qa_by=qa_by)


def block(s, reason):
    require(s['phase'] not in ('COMPLETED','BLOCKED'),'CANNOT_BLOCK_COMPLETED_RUN')
    require(isinstance(reason,str) and reason.strip(),'BLOCK_REASON_REQUIRED')
    s['blocked']={'at':now(),'reason':reason,'previous':s['phase'],
                  'stage':s['current_stage']}
    s['phase']='BLOCKED'
    event(s,'FAILED_IN_CURRENT_STAGE',reason=reason,stage=s['current_stage'])


def resume(s,root,resolution):
    require(s['phase']=='BLOCKED' and s['blocked'], 'NO_BLOCKED_STAGE')
    require(isinstance(resolution,str) and resolution.strip(),'RESOLUTION_REQUIRED')
    assert_config(s,root)
    all_existing_valid(s)
    previous=s['blocked']['previous']
    require(previous in PHASES and previous not in ('BLOCKED','COMPLETED'), 'INVALID_RESUME_TARGET')
    s['phase']=previous
    old=s['blocked']
    s['blocked']=None
    event(s,'RESUMED_SAME_STAGE',blocked_reason=old['reason'],resolution=resolution)


def cli():
    p=argparse.ArgumentParser(description='实况视频单窗口状态/路由/质检/返工/引擎执行')
    p.add_argument('--root',default=str(Path(__file__).resolve().parents[1]),help='启动包根目录')
    sub=p.add_subparsers(dest='action',required=True)
    def add(n):
        a=sub.add_parser(n);a.add_argument('--run-dir',required=True);return a
    a=add('init');a.add_argument('--run-id',required=True);a.add_argument('--mode',choices=['REVIEW','AUTO'],default='REVIEW')
    a=add('record-00');a.add_argument('--result',required=True)
    add('resolve-route')
    a=add('approve');a.add_argument('--gate',choices=['00','stage','delivery'],required=True);a.add_argument('--confirmation',required=True)
    a=add('record-artifact');a.add_argument('--stage',required=True);a.add_argument('--name',required=True);a.add_argument('--file',required=True);a.add_argument('--qa-by',required=True);a.add_argument('--qa-note',required=True);a.add_argument('--source-id',required=True)
    a=add('report-stage');a.add_argument('--stage',required=True)
    a=add('revise');a.add_argument('--stage',required=True);a.add_argument('--name',required=True);a.add_argument('--instruction',required=True);a.add_argument('--invalidate-delivery',action='store_true')
    add('engine-run')
    a=add('accept-delivery');a.add_argument('--qa-by',required=True);a.add_argument('--qa-note',required=True)
    a=add('fail');a.add_argument('--reason',required=True)
    a=add('resume');a.add_argument('--resolution',required=True)
    add('status')
    args=p.parse_args()
    root=Path(args.root).resolve()
    try:
        if args.action=='init':
            s=init(args.run_dir,args.run_id,args.mode);p=state_path(args.run_dir)
        else:
            s,p=load(args.run_dir)
            if args.action=='record-00': record_00(s,root,args.result)
            elif args.action=='resolve-route':
                require(s['phase']=='WAITING_ROUTE_RULES','RESOLVE_ROUTE_NOT_EXPECTED')
                resolve_route(s,root)
            elif args.action=='approve':approve(s,root,args.gate,args.confirmation)
            elif args.action=='record-artifact':record_artifact(s,root,args.stage,args.name,args.file,args.qa_by,args.qa_note,args.source_id)
            elif args.action=='report-stage':report_stage(s,root,args.stage)
            elif args.action=='revise':revise(s,root,args.stage,args.name,args.instruction,args.invalidate_delivery)
            elif args.action=='engine-run':render(s,root,args.run_dir)
            elif args.action=='accept-delivery':accept_delivery(s,root,args.qa_by,args.qa_note)
            elif args.action=='fail':block(s,args.reason)
            elif args.action=='resume':resume(s,root,args.resolution)
            elif args.action=='status':
                print(json.dumps(s,ensure_ascii=False,indent=2));return 0
            write(s,p)
        print(json.dumps({'ok':True,'run_id':s['run_id'],'phase':s['phase'],
                          'route':s['route_id'],'current_stage':s['current_stage']},ensure_ascii=False))
        return 0
    except (WorkflowError,OSError,ValueError,KeyError,zipfile.BadZipFile) as e:
        # A real runtime failure must leave a durable BLOCKED record rather than
        # silently allowing the next stage; status reads do not mutate anything.
        if args.action not in ('init','status','fail','resume'):
            try:
                previous_state, state_file = load(args.run_dir)
                if previous_state['phase'] not in ('COMPLETED','BLOCKED'):
                    block(previous_state, f'{args.action}: {e}')
                    write(previous_state,state_file)
            except (WorkflowError,OSError,ValueError,KeyError):
                pass
        print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(cli())