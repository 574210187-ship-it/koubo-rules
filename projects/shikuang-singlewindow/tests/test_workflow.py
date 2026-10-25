import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import shutil
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import shikuang as w


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'config').mkdir()
        (self.root/'engines').mkdir()
        self.rundir=self.root/'runs'/'t001'
        self.src=self.root/'video.txt'
        self.src.write_text('source video v1',encoding='utf-8')
        self.analysis=self.root/'00.json'
        self.analysis.write_text(json.dumps({'facts':{'kind':'video','pages':1},
            'evidence':'synthetic automated contract fixture, no actual video reviewed',
            'source_files':[str(self.src)]}),encoding='utf-8')
        self.route={'id':'route_a','match':{'kind':'video','pages':1},'engine_id':'STUB_ENGINE',
            'stages':[{'id':'parse','artifacts':[{'name':'raw','file_type':'any'},
                      {'name':'transcript','file_type':'any'}]},
                      {'id':'compose','artifacts':[{'name':'final','file_type':'any',
                         'depends_on':['parse:raw','parse:transcript']}]}]}
        w.jwrite(self.root/'config'/'routes.json',{'schema_version':1,'routes':[self.route]})
        # Real subprocess + ZIP signature, test-only synthetic engine, NOT a video production engine.
        self.engine=self.root/'engines'/'stub.zip'
        code="""import argparse, json\nfrom pathlib import Path\na=argparse.ArgumentParser();a.add_argument('--job');a.add_argument('--out');o=a.parse_args()\nd=json.loads(Path(o.job).read_text());out=Path(o.out);out.mkdir(parents=True,exist_ok=True)\n(out/'result.json').write_text(json.dumps({'engine':'fixture','route':d['route'],'sha':sorted(x['sha256'] for x in d['input_files'].values())}))\n"""
        with zipfile.ZipFile(self.engine,'w') as z:z.writestr('run.py',code)
        self.engines={'schema_version':1,'engines':[{'id':'STUB_ENGINE','status':'APPROVED',
             'zip_path':'engines/stub.zip','sha256':w.sha(self.engine),
             'command':['{python}','run.py','--job','{job}','--out','{out}'],
             'outputs':[{'name':'result.json','file_type':'json'}]}]}
        w.jwrite(self.root/'config'/'engines.json',self.engines)
        self.data={}

    def make(self,name,content):
        p=self.root/name
        p.write_text(content,encoding='utf-8')
        return p

    def new(self,mode='REVIEW'):
        s=w.init(self.rundir,'t001',mode)
        w.record_00(s,self.root,self.analysis)
        return s

    def record(self,s,stage,name,content='value',sid=None):
        sid=sid or f'generate_{stage}_{name}_{len(s["history"])}'
        # 00 is already recorded, local fixture has no media processing or visual automation
        path=self.make(f'{sid}.txt',content)
        w.record_artifact(s,self.root,stage,name,path,'qa-fixture','synthetic evidence fixture only',sid)
        return path

    def stage(self,s,stage):
        w.report_stage(s,self.root,stage)
        if s['phase']=='AWAIT_STAGE_APPROVAL': w.approve(s,self.root,'stage','qa-reviewed')

    def test_root_without_routes_holds_and_resume_when_rules_added(self):
        w.jwrite(self.root/'config'/'routes.json',{'schema_version':1,'routes':[]})
        s=self.new()
        self.assertEqual(s['phase'],'WAITING_ROUTE_RULES')
        self.assertIsNone(s['route_id'])
        w.jwrite(self.root/'config'/'routes.json',{'schema_version':1,'routes':[self.route]})
        w.resolve_route(s,self.root)
        self.assertEqual(s['phase'],'AWAIT_00_APPROVAL')

    def test_full_review_render_is_real_subprocess_with_signed_zip(self):
        s=self.new()
        w.approve(s,self.root,'00','00通过')
        self.record(s,'parse','raw','video source 1')
        self.record(s,'parse','transcript','transcript 1')
        self.stage(s,'parse')
        self.record(s,'compose','final','final output')
        self.stage(s,'compose')
        self.assertEqual(s['phase'],'READY_ENGINE')
        w.render(s,self.root,self.rundir)
        self.assertEqual(s['phase'],'RENDERED')
        self.assertTrue(Path(s['render']['outputs'][0]['path']).is_file())
        w.accept_delivery(s,self.root,'qa-fixture','fixture evidence, not user visual')
        self.assertEqual(s['phase'],'AWAIT_DELIVERY_APPROVAL')
        w.approve(s,self.root,'delivery','交付通过')
        self.assertEqual(s['phase'],'COMPLETED')

    def test_image_revision_invalidates_only_dependencies(self):
        s=self.new();w.approve(s,self.root,'00','pass')
        self.record(s,'parse','raw','original A',sid='a')
        self.record(s,'parse','transcript','original B',sid='b')
        self.stage(s,'parse')
        self.record(s,'compose','final','original C',sid='c')
        self.stage(s,'compose')
        transcript_sha=s['stages'][0]['artifacts']['transcript']['sha256']
        w.revise(s,self.root,'parse','raw','只修改原片，不修改逐字稿')
        self.assertEqual(s['phase'],'NEED_STAGE')
        self.assertEqual(s['current_stage'],'parse')
        self.assertEqual(s['stages'][0]['artifacts']['transcript']['sha256'],transcript_sha)
        self.assertNotIn('raw',s['stages'][0]['artifacts'])
        self.assertNotIn('final',s['stages'][1]['artifacts'])
        with self.assertRaisesRegex(w.WorkflowError,'ALL_STAGES_MUST_BE_APPROVED'):
            w.verified_inputs(s,self.root)
        self.record(s,'parse','raw','reworked A',sid='a2')
        self.stage(s,'parse')
        self.record(s,'compose','final','reworked C',sid='c2')
        self.stage(s,'compose')
        self.assertEqual(s['phase'],'READY_ENGINE')

    def test_auto_mode_rework_forces_manual_approval(self):
        s=self.new('AUTO')
        self.assertEqual(s['phase'],'NEED_STAGE')
        self.record(s,'parse','raw','x',sid='x')
        self.record(s,'parse','transcript','y',sid='y')
        self.stage(s,'parse')
        self.assertEqual(s['current_stage'],'compose')
        self.record(s,'compose','final','z',sid='z')
        self.stage(s,'compose')
        w.revise(s,self.root,'parse','raw','改一下第一步')
        self.record(s,'parse','raw','new x',sid='x2')
        w.report_stage(s,self.root,'parse')
        self.assertEqual(s['phase'],'AWAIT_STAGE_APPROVAL')

    def test_failed_engine_integrity_blocks_execution(self):
        s=self.new();w.approve(s,self.root,'00','ok')
        self.record(s,'parse','raw','q',sid='q')
        self.record(s,'parse','transcript','r',sid='r')
        self.stage(s,'parse')
        self.record(s,'compose','final','s',sid='s')
        self.stage(s,'compose')
        with self.engine.open('ab') as f:f.write(b'tampered')
        with self.assertRaisesRegex(w.WorkflowError,'ENGINE_ZIP_CHANGED'):
            w.approved_engine(s,self.root)

    def test_input_mutation_stops_stage_approval(self):
        s=self.new();w.approve(s,self.root,'00','ok')
        f=self.record(s,'parse','raw','first',sid='first')
        self.record(s,'parse','transcript','second',sid='second')
        w.report_stage(s,self.root,'parse')
        f.write_text('tamper',encoding='utf-8')
        with self.assertRaisesRegex(w.WorkflowError,'ARTIFACT_SHA_CHANGED'):
            w.approve(s,self.root,'stage','批准')

    def test_failed_state_resumes_same_stage_after_correction(self):
        s=self.new();w.approve(s,self.root,'00','ok')
        w.block(s,'input required')
        self.assertEqual(s['phase'],'BLOCKED')
        w.resume(s,self.root,'added input')
        self.assertEqual(s['phase'],'NEED_STAGE')
        self.assertEqual(s['current_stage'],'parse')

    def test_ambiguous_rules_stop(self):
        bad=copy.deepcopy(self.route)
        bad['id']='route_b'
        w.jwrite(self.root/'config'/'routes.json',{'schema_version':1,'routes':[self.route,bad]})
        with self.assertRaisesRegex(w.WorkflowError,'ROUTING_AMBIGUOUS'):
            self.new()

    def test_no_approval_in_review_means_no_video(self):
        s=self.new()
        with self.assertRaisesRegex(w.WorkflowError,'ALL_STAGES_MUST_BE_APPROVED'):
            w.verified_inputs(s,self.root)

    def test_route_policy_change_cannot_silently_switch(self):
        s=self.new();w.approve(s,self.root,'00','ok')
        altered=copy.deepcopy(self.route);altered['match']={'kind':'image'}
        w.jwrite(self.root/'config'/'routes.json',{'schema_version':1,'routes':[altered]})
        with self.assertRaisesRegex(w.WorkflowError,'ROUTING_CONFIG_CHANGED'):
            w.record_artifact(s,self.root,'parse','raw',self.make('a.txt','test'),'qa','test','a1')

    def test_wrong_stage_cannot_be_skipped(self):
        s=self.new();w.approve(s,self.root,'00','ok')
        with self.assertRaisesRegex(w.WorkflowError,'CURRENT_STAGE_REQUIRED'):
            self.record(s,'compose','final','not now')

    def test_rendered_revision_needs_explicit_invalidation(self):
        s=self.new();w.approve(s,self.root,'00','ok')
        self.record(s,'parse','raw','1',sid='r1');self.record(s,'parse','transcript','2',sid='t1');self.stage(s,'parse')
        self.record(s,'compose','final','3',sid='f1');self.stage(s,'compose')
        w.render(s,self.root,self.rundir)
        with self.assertRaisesRegex(w.WorkflowError,'RENDERED_RESULT_EXISTS'):
            w.revise(s,self.root,'parse','raw','重做')
        w.revise(s,self.root,'parse','raw','重做',True)
        self.assertIsNone(s['render'])
        self.assertEqual(s['phase'],'NEED_STAGE')

    def test_rework_cannot_reuse_retired_bytes_id_or_path(self):
        s=self.new();w.approve(s,self.root,'00','ok')
        old=self.record(s,'parse','raw','first',sid='old1')
        self.record(s,'parse','transcript','second',sid='transcript')
        self.stage(s,'parse')
        self.record(s,'compose','final','third',sid='final')
        self.stage(s,'compose')
        w.revise(s,self.root,'parse','raw','重做原片')
        with self.assertRaisesRegex(w.WorkflowError,'DUPLICATE_ARTIFACT_BYTES'):
            w.record_artifact(s,self.root,'parse','raw',old,'vis','visual proof','new_id')
        p=self.make('brand_new_path.txt','changed bytes')
        with self.assertRaisesRegex(w.WorkflowError,'DUPLICATE_SOURCE_ID'):
            w.record_artifact(s,self.root,'parse','raw',p,'vis','visual proof','old1')
        old.write_text('new bytes but old filename')
        with self.assertRaisesRegex(w.WorkflowError,'REUSED_OLD_PATH'):
            w.record_artifact(s,self.root,'parse','raw',old,'vis','visual proof','new_id')

    def test_second_render_attempt_does_not_overwrite_first(self):
        s=self.new();w.approve(s,self.root,'00','ok')
        self.record(s,'parse','raw','1',sid='a');self.record(s,'parse','transcript','2',sid='b');self.stage(s,'parse')
        self.record(s,'compose','final','3',sid='c');self.stage(s,'compose')
        w.render(s,self.root,self.rundir)
        first=Path(s['render']['outputs'][0]['path'])
        w.revise(s,self.root,'parse','raw','redo',True)
        self.record(s,'parse','raw','a-new',sid='a-new');self.stage(s,'parse')
        self.record(s,'compose','final','c-new',sid='c-new');self.stage(s,'compose')
        w.render(s,self.root,self.rundir)
        second=Path(s['render']['outputs'][0]['path'])
        self.assertNotEqual(first,second)
        self.assertTrue(first.is_file() and second.is_file())
        self.assertEqual(s['render']['attempt'],2)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe unavailable')
    def test_video_engine_real_h264_aac_encodes_and_probes_fixture(self):
        # Real FFmpeg encode/decoder + ZIP adapter, but from a synthetic clip.
        input_mp4=self.root/'input.mp4'
        make=subprocess.run(['ffmpeg','-y','-loglevel','error','-f','lavfi','-i',
            'testsrc2=size=160x284:rate=12','-f','lavfi','-i','sine=frequency=440:sample_rate=44100',
            '-t','0.8','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(input_mp4)],
            capture_output=True,text=True)
        self.assertEqual(make.returncode,0,make.stderr)
        program=(
            'import json,subprocess,sys\n'
            'from pathlib import Path\n'
            'j=json.loads(Path(sys.argv[1]).read_text())\n'
            'p=j["input_files"]["parse:raw"]["path"]\n'
            'out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)\n'
            'subprocess.run(["ffmpeg","-y","-loglevel","error","-i",p,"-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac",str(out/"final.mp4")],check=True)\n'
        )
        with zipfile.ZipFile(self.engine,'w') as z:z.writestr('encode.py',program)
        eng=self.engines['engines'][0]
        eng.update(sha256=w.sha(self.engine),command=['{python}','encode.py','{job}','{out}'],
                   outputs=[{'name':'final.mp4','file_type':'video'}])
        w.jwrite(self.root/'config'/'engines.json',self.engines)
        self.route['stages'][0]['artifacts'][0]['file_type']='video'
        w.jwrite(self.root/'config'/'routes.json',{'schema_version':1,'routes':[self.route]})
        s=self.new();w.approve(s,self.root,'00','ok')
        w.record_artifact(s,self.root,'parse','raw',input_mp4,'fixture','actual mp4 probe in integration test','g1')
        self.record(s,'parse','transcript','phrase',sid='text1')
        self.stage(s,'parse')
        self.record(s,'compose','final','manifest-json',sid='fin1')
        self.stage(s,'compose')
        w.render(s,self.root,self.rundir)
        out=Path(s['render']['outputs'][0]['path'])
        self.assertGreater(out.stat().st_size,1000)
        w.accept_delivery(s,self.root,'fixture-review','h264/aac synthetic full technical decode')
        w.approve(s,self.root,'delivery','synthetic only')
        self.assertEqual(s['phase'],'COMPLETED')
        decode=subprocess.run(['ffmpeg','-v','error','-i',str(out),'-f','null','-'],
                              capture_output=True,text=True)
        self.assertEqual(decode.returncode,0,decode.stderr)


if __name__ == '__main__': unittest.main()