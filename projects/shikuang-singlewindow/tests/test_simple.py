"""Synthetic PNGs in this test file are fixtures; production PNGs must come from ImageGen."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from shikuang import WorkflowError,start,analyze,approve00,register_options,select_image,render,open_state,video_info,digest

class FlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.d=Path(cls.temp.name)
        cls.main=cls.d/'main.mp4';cls.reference=cls.d/'reference.mp4'
        def mk(dst,color):
            subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i',f'color=c={color}:s=180x320:r=24',
                '-f','lavfi','-i','sine=frequency=400:sample_rate=48000','-t','1.5','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(dst)],check=True,timeout=50)
        mk(cls.main,'blue');mk(cls.reference,'red')
        cls.images=[]
        for i in range(4):
            p=cls.d/f'option{i}.png'; im=Image.new('RGBA',(180,320),(0,0,0,0))
            ImageDraw.Draw(im).rectangle((15,140+i,170,163+i),fill=(255,255,255,255))
            im.save(p);cls.images.append(str(p))
        cls.analysis=cls.d/'00.json'
        cls.analysis.write_text(json.dumps({'text':'第一行文字\n第二行文字\n第三行文字',
            'layout':'三行左对齐，黑字白纸条，中下方','bbox':[.03,.52,.94,.16]},ensure_ascii=False),encoding='utf-8')
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def newrun(self,name):
        d=self.d/name
        start(d,self.main,self.reference)
        return d
    def prepare(self,name,n=3):
        d=self.newrun(name)
        analyze(d,self.analysis)
        approve00(d)
        register_options(d,self.images[:n],[f'imagegen:fixture-{i}' for i in range(n)])
        return d
    def test_two_clicks_and_three_options(self):
        d=self.newrun('regular3')
        s=analyze(d,self.analysis)
        self.assertEqual(s['stage'],'00_WAIT_CONFIRM')
        with self.assertRaisesRegex(WorkflowError,'STAGE_NOT_01'):register_options(d,self.images[:3],[f'imagegen:f{i}' for i in range(3)])
        approve00(d)
        s=register_options(d,self.images[:3],[f'imagegen:f{i}' for i in range(3)])
        self.assertEqual(s['stage'],'01_WAIT_SELECTION')
        with self.assertRaisesRegex(WorkflowError,'NEED_USER_SELECTED_IMAGE'):render(d)
        select_image(d,self.images[1])
        s=render(d)
        self.assertEqual(s['stage'],'DONE')
        self.assertEqual(len(s['options']),3)
        mp4=Path(s['delivery']['mp4']['path']);z=Path(s['delivery']['zip']['path'])
        self.assertTrue(mp4.exists());self.assertTrue(z.exists())
        import zipfile, hashlib
        with zipfile.ZipFile(z) as a:
            self.assertEqual(a.namelist(),['final_animation.mp4'])
            self.assertEqual(hashlib.sha256(a.read('final_animation.mp4')).hexdigest(),digest(mp4))
        v=video_info(mp4);orig=video_info(self.main)
        self.assertEqual((v['width'],v['height']),(1080,1920))
        self.assertAlmostEqual(v['duration'],orig['duration'],delta=.15)
        self.assertEqual(v['fps'],orig['fps']);self.assertEqual(v['has_audio'],orig['has_audio'])
    def test_four_variants_still_waits_for_user_selection(self):
        d=self.prepare('four_options',4)
        self.assertEqual(open_state(d)[0]['stage'],'01_WAIT_SELECTION')
        with self.assertRaisesRegex(WorkflowError,'NEED_USER_SELECTED_IMAGE'):render(d)
        self.assertEqual(len(open_state(d)[0]['options']),4)
    def test_choose_existing_option_without_reupload(self):
        d=self.prepare('selected_idx')
        s=select_image(d,index=2)
        self.assertEqual(s['selected']['sha256'],digest(self.images[1]))
        self.assertEqual(s['selected']['selected_by'],'USER_SELECTED_IMAGEGEN_OPTION')
        result=render(d)
        self.assertEqual(result['stage'],'DONE')

    def test_invalid_or_missing_selection_stops(self):
        d=self.prepare('invalid_selection')
        with self.assertRaisesRegex(WorkflowError,'OPTION_INDEX_NOT_FOUND'):select_image(d,index=9)
        with self.assertRaisesRegex(WorkflowError,'SELECT_NEEDS_PNG_OR_INDEX'):select_image(d)
        self.assertEqual(open_state(d)[0]['stage'],'01_WAIT_SELECTION')

    def test_single_conversation_mode_no_mode_flag(self):
        d=self.newrun('one_mode')
        self.assertNotIn('mode',open_state(d)[0])
        import subprocess
        r=subprocess.run([sys.executable,str(ROOT/'src/shikuang.py'),'init','--run-dir',str(self.d/'other'),
             '--main',str(self.main),'--reference',str(self.reference),'--mode','LEGACY'],capture_output=True,text=True)
        self.assertNotEqual(r.returncode,0)
        self.assertIn('unrecognized arguments',r.stderr)

    def test_incorrect_option_count_stops(self):
        d=self.newrun('wrong_count');analyze(d,self.analysis);approve00(d)
        for n in (1,2,5):
            with self.assertRaisesRegex(WorkflowError,'NEED_3_OR_4_IMAGEGEN_OPTIONS'):
                register_options(d,(self.images*2)[:n],[f'imagegen:f{i}' for i in range(n)])
    def test_reused_id_rejected(self):
        d=self.newrun('reuse');analyze(d,self.analysis);approve00(d)
        with self.assertRaisesRegex(WorkflowError,'IMAGEGEN_IDS_MUST_BE_UNIQUE'):
            register_options(d,self.images[:3],['imagegen:same']*3)
    def test_selected_invalid_alpha_stops(self):
        d=self.prepare('bad_png');p=self.d/'opaque.png'
        Image.new('RGBA',(180,320),(0,0,0,255)).save(p)
        with self.assertRaisesRegex(WorkflowError,'PNG_MUST_BE_TRANSPARENT'):select_image(d,p)
        self.assertEqual(open_state(d)[0]['stage'],'01_WAIT_SELECTION')
    def test_user_can_reselect_without_restarting(self):
        d=self.prepare('reselect',3)
        select_image(d,self.images[1]);render(d)
        s=select_image(d,self.images[2]);self.assertEqual(s['stage'],'02_READY')
        s=render(d)
        self.assertTrue(Path(s['delivery']['mp4']['path']).name.endswith('002.mp4'))
        self.assertTrue((d/'outputs'/'final_001.mp4').exists())
    def test_changed_source_blocks(self):
        d=self.prepare('tamper')
        olddata=self.main.read_bytes()
        try:
            with self.main.open('ab') as f:f.write(b'alter')
            with self.assertRaisesRegex(WorkflowError,'SOURCE_CHANGED'):select_image(d,self.images[0])
        finally:self.main.write_bytes(olddata)
    def test_analysis_just_text_style_box(self):
        d=self.newrun('bad_analysis')
        p=self.d/'bad.json';p.write_text(json.dumps({'text':'x','layout':'y','bbox':[0,0,1.2,0.4]}))
        with self.assertRaisesRegex(WorkflowError,'00_BBOX_OUT_OF_RANGE'):analyze(d,p)
        self.assertEqual(open_state(d)[0]['stage'],'00_ANALYZE')
    def test_manual_upload_not_required_to_byte_match_option(self):
        d=self.prepare('reuploaded')
        p=self.d/'pasted.png'; im=Image.open(self.images[2]);im.save(p,optimize=True)
        s=select_image(d,p)
        self.assertEqual(s['selected']['path'],str(p))
    def test_no_images_in_package(self):
        self.assertFalse(list(ROOT.rglob('*.mp4')))
        self.assertFalse(list(ROOT.rglob('*.png')))

if __name__=='__main__':unittest.main()