"""Contract tests: synthetic video and synthetic PNG are FIXTURES, never user output.
Production Stage 01 always requires an actual ImageGen artifact and human/agent QA.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import shikuang as w
from short_static_policy import validate_00,validate_overlay_png,video_dimensions_and_duration,verify_short_video
try:
    from PIL import Image,ImageDraw
except ImportError:
    Image=None

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(Image is not None and shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'requires Pillow, ffmpeg, ffprobe')
class ShortStaticPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._t=tempfile.TemporaryDirectory()
        cls.base=Path(cls._t.name)
        cls.video=cls.base/'main.mp4'
        cls.refvideo=cls.base/'reference.mp4'
        cls.refimage=cls.base/'reference.png'
        cls.overlay=cls.base/'overlay.png'
        cls.badalpha=cls.base/'opaque.png'
        # Constant-color video permits bytewise comparison between uncompressed frames.
        cmd=['ffmpeg','-nostdin','-y','-loglevel','error',
             '-f','lavfi','-i','color=c=navy:size=160x284:rate=25',
             '-f','lavfi','-i','sine=frequency=550:sample_rate=44100',
             '-t','4.2','-c:v','libx264','-pix_fmt','yuv420p',
             '-c:a','aac','-shortest',str(cls.video)]
        subprocess.run(cmd,check=True,timeout=45)
        cmd=['ffmpeg','-nostdin','-y','-loglevel','error',
             '-f','lavfi','-i','color=c=red:size=160x284:rate=25',
             '-t','4.2','-c:v','libx264','-pix_fmt','yuv420p',str(cls.refvideo)]
        subprocess.run(cmd,check=True,timeout=45)
        a=Image.new('RGBA',(160,284),(0,0,0,0))
        ImageDraw.Draw(a).rectangle((20,44,145,76), fill=(255,255,255,245))
        a.save(cls.overlay)
        a=Image.new('RGBA',(160,284),(0,0,0,255));a.save(cls.badalpha)
        Image.new('RGB',(160,284),(120,45,45)).save(cls.refimage)

    @classmethod
    def tearDownClass(cls): cls._t.cleanup()

    def facts(self,kind='main_video+reference_image'):
        return {'input_kind':kind, 'main_video_path':str(self.video),
                'reference_path':str(self.refvideo if kind.endswith('video') else self.refimage),
                'reference_text':'原文','final_text':'原文','layout_evidence':'screen reviewed 160x284',
                'reference_layout_kind':'SINGLE_STATIC_LAYOUT','user_edits':[],
                'text_mode':'STATIC_FULL_DURATION','playback':'ORIGINAL_SPEED_TRIM','effects':'NONE',
                'clip_start_seconds':0.35,'clip_duration_seconds':2.9,
                'speed_factor':1.0,'text_start_seconds':0,'audio_policy':'MAIN_ONLY_OR_SILENCE'}

    def validation(self,kind='main_video+reference_image'):
        f=self.facts(kind);r={'facts':f,'evidence':'fixture operator examined screenshot',
                                'source_files':[f['main_video_path'],f['reference_path']]}
        return r

    def test_route_for_both_supported_reference_types(self):
        for kind,route in [('main_video+reference_image','STATIC_REF_IMAGE'),
                           ('main_video+reference_video','STATIC_REF_VIDEO')]:
            with self.subTest(kind=kind):
                record=w.validate_00(self.validation(kind))
                resolved, _=w.routing(ROOT,record['facts'])
                self.assertEqual(resolved['id'],route)

    def test_00_blocks_speed_change_static_effects_and_3s_or_more(self):
        from shikuang import WorkflowError
        changes=[('speed_factor',1.2,'SPEED_FACTOR'),('playback','ACCELERATE','NO_RETIMING'),
                 ('text_mode','SCROLLING','STATIC_TEXT'),('effects','FADE_IN','TEXT_EFFECTS'),
                 ('clip_duration_seconds',3.0,'CLIP_MUST'),('text_start_seconds',0.5,'TEXT_MUST')]
        for key,value,message in changes:
            with self.subTest(key=key):
                r=self.validation();r['facts'][key]=value
                with self.assertRaisesRegex(WorkflowError,message):w.validate_00(r)

    def test_user_edit_changes_must_be_documented(self):
        from shikuang import WorkflowError
        r=self.validation();r['facts']['final_text']='改写后'
        with self.assertRaisesRegex(WorkflowError,'00_TEXT_CHANGE_UNDOCUMENTED'):w.validate_00(r)
        r['facts']['user_edits']=[{'instruction':'原文改成改写后'}]
        w.validate_00(r)

    def test_overlay_requires_real_alpha_and_imagegen_provenance_record(self):
        from shikuang import WorkflowError
        validate_overlay_png(self.overlay,'imagegen:fixture-only',self.video)
        with self.assertRaisesRegex(WorkflowError,'IMAGEGEN_GENERATION_ID_REQUIRED'):
            validate_overlay_png(self.overlay,'program-pil-not-imagegen',self.video)
        with self.assertRaisesRegex(WorkflowError,'PNG_REQUIRES_REAL_TRANSPARENCY'):
            validate_overlay_png(self.badalpha,'imagegen:fixture-only',self.video)

    def _render_engine(self,kind):
        f=self.facts(kind)
        job={'route':'STATIC_REF_IMAGE' if kind.endswith('image') else 'STATIC_REF_VIDEO',
             'analysis_facts':f,'analysis_sources':[
                 {'path':str(self.video),'sha256':w.sha(self.video)},
                 {'path':str(self.refimage if kind.endswith('image') else self.refvideo),
                  'sha256':w.sha(self.refimage if kind.endswith('image') else self.refvideo)}],
             'input_files':{'01_TEXT:text_rgba':{'path':str(self.overlay),'sha256':w.sha(self.overlay)}}}
        work=self.base/('run_'+kind.replace('+','_'))
        work.mkdir(exist_ok=True)
        job_path=work/'job.json';w.jwrite(job_path,job)
        with zipfile.ZipFile(ROOT/'engines'/'static_text_clip_candidate_v0.2.0.zip') as z:z.extract('run.py',work)
        run=subprocess.run([sys.executable,str(work/'run.py'),'--job',str(job_path),
                           '--out',str(work/'output')],capture_output=True,text=True,timeout=90)
        self.assertEqual(run.returncode,0,run.stderr)
        return work/'output'/'final_animation.mp4'

    def test_image_reference_engine_actual_mp4_original_speed_static_text(self):
        output=self._render_engine('main_video+reference_image')
        info=verify_short_video(output,2.9)
        self.assertLess(info['container_duration'],3)
        self.assertGreater(info['video_duration'],2.7)
        # Preserve input 25fps without any setpts scaling, while clip retains 2.9s.
        p=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
                          'stream=r_frame_rate,nb_frames','-of','json',str(output)],
                         capture_output=True,text=True,check=True)
        stream=json.loads(p.stdout)['streams'][0]
        self.assertEqual(stream['r_frame_rate'],'25/1')
        self.assertTrue(70<=int(stream['nb_frames'])<=74,stream)
        # Constant background plus frozen overlay means raw image frame pixels do not change.
        def rawframe(t):
            cmd=['ffmpeg','-loglevel','error','-ss',str(t),'-i',str(output),
                 '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-']
            return subprocess.run(cmd,check=True,capture_output=True,timeout=35).stdout
        self.assertEqual(rawframe(0.2),rawframe(2.2))

    def test_video_reference_is_only_analysis_source_not_a_video_input_to_render(self):
        output=self._render_engine('main_video+reference_video')
        self.assertLess(verify_short_video(output,2.9)['container_duration'],3.0)

    def test_engine_tampered_input_refuses_to_run(self):
        kind='main_video+reference_image';f=self.facts(kind)
        job={'route':'STATIC_REF_IMAGE','analysis_facts':f,
             'analysis_sources':[{'path':str(self.video),'sha256':'0'*64},
                                 {'path':str(self.refimage),'sha256':w.sha(self.refimage)}],
             'input_files':{'01_TEXT:text_rgba':{'path':str(self.overlay),'sha256':w.sha(self.overlay)}}}
        work=self.base/'tamper';work.mkdir(exist_ok=True)
        job_path=work/'job.json';w.jwrite(job_path,job)
        with zipfile.ZipFile(ROOT/'engines'/'static_text_clip_candidate_v0.2.0.zip') as z:z.extract('run.py',work)
        run=subprocess.run([sys.executable,str(work/'run.py'),'--job',str(job_path),'--out',str(work/'out')],
                           capture_output=True,text=True,timeout=90)
        self.assertNotEqual(run.returncode,0)
        self.assertIn('MAIN_SOURCE_NOT_HASH_LOCKED',run.stderr)

    def test_full_state_machine_candidate_remains_blocked_by_default(self):
        # Same package as real deployment: candidate must NOT self-approve.
        r=self.validation();an=self.base/'candidate_00.json';w.jwrite(an,r)
        run=self.base/'candidate_run'
        s=w.init(run,'candidate','REVIEW')
        w.record_00(s,ROOT,an)
        w.approve(s,ROOT,'00','00确认通过')
        w.record_artifact(s,ROOT,'01_TEXT','text_rgba',self.overlay,
                          'test-fixture','synthetic PNG for contract only','imagegen:fixture-only')
        w.report_stage(s,ROOT,'01_TEXT')
        self.assertEqual(s['phase'],'AWAIT_STAGE_APPROVAL')
        w.approve(s,ROOT,'stage','图片通过，继续生视频')
        self.assertEqual(s['phase'],'READY_ENGINE')
        with self.assertRaisesRegex(w.WorkflowError,'ENGINE_NOT_APPROVED'):
            w.render(s,ROOT,run)

    def test_full_state_machine_real_encoder_runs_only_with_test_only_approved_copy(self):
        # Clone registry into ephemeral test environment. This is NOT a production engine approval.
        t=self.base/'test_only_approved'
        (t/'config').mkdir(parents=True,exist_ok=True)
        (t/'engines').mkdir(parents=True,exist_ok=True)
        import shutil as filecopy
        filecopy.copy2(ROOT/'config'/'routes.json',t/'config'/'routes.json')
        e=json.loads((ROOT/'config'/'engines.json').read_text(encoding='utf8'))
        e['engines'][0]['status']='APPROVED'  # test fixture only, never write to shipping config
        w.jwrite(t/'config'/'engines.json',e)
        filecopy.copy2(ROOT/'engines'/'static_text_clip_candidate_v0.2.0.zip',
                       t/'engines'/'static_text_clip_candidate_v0.2.0.zip')
        w.jwrite(t/'config'/'project.json',json.loads((ROOT/'config'/'project.json').read_text(encoding='utf8')))
        r=self.validation('main_video+reference_video');an=t/'00.json';w.jwrite(an,r)
        run=t/'runs'/'001';s=w.init(run,'001','REVIEW')
        w.record_00(s,t,an)
        self.assertEqual(s['route_id'],'STATIC_REF_VIDEO')
        w.approve(s,t,'00','00确认通过')
        w.record_artifact(s,t,'01_TEXT','text_rgba',self.overlay,
                          'fixture-visual-only','fixture PNG NOT generated by ImageGen','imagegen:synthetic-only')
        w.report_stage(s,t,'01_TEXT')
        w.approve(s,t,'stage','图片通过，继续生视频')
        w.render(s,t,run)
        self.assertEqual(s['phase'],'RENDERED')
        f=Path(s['render']['outputs'][0]['path'])
        self.assertTrue(f.is_file())
        self.assertLess(verify_short_video(f,2.9)['container_duration'],3)
        w.accept_delivery(s,t,'fixture-inspection','synthetic video basic timing checked')
        w.approve(s,t,'delivery','测试成片通过')
        self.assertEqual(s['phase'],'COMPLETED')

    def test_00_prepare_generates_unreviewed_draft_only(self):
        work=self.base/'prepare.json'
        c=subprocess.run([sys.executable,str(ROOT/'src'/'prepare_00.py'),
                          '--main',str(self.video),'--reference',str(self.refimage),
                          '--out',str(work),'--edit','把测试字样替换'],capture_output=True,text=True,timeout=45)
        self.assertEqual(c.returncode,0,c.stderr)
        draft=json.loads(work.read_text(encoding='utf8'))
        self.assertEqual(draft['facts']['input_kind'],'main_video+reference_image')
        self.assertEqual(draft['facts']['user_edits'][0]['instruction'],'把测试字样替换')
        self.assertEqual(draft['facts']['reference_text'],'')
        with self.assertRaisesRegex(w.WorkflowError,'00_EVIDENCE_REQUIRED'):
            w.validate_00(draft)


if __name__=='__main__':unittest.main()