import json,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class TestPublicRelease(unittest.TestCase):
 def test_public_registry(self):
  p=json.loads((ROOT/'distribution/TARGETS.json').read_text())
  self.assertEqual(p['github']['visibility'],'public')
  self.assertIn('raw.githubusercontent.com/',p['github']['startup_url'])
 def test_media_excluded(self):
  self.assertFalse(list(ROOT.rglob('*.mp4')))
  self.assertFalse(list(ROOT.rglob('*.mov')))
 def test_mode_guard(self):
  p=json.loads((ROOT/'config/project.json').read_text())
  self.assertTrue(p['auto_requires_real_imagegen'])
  self.assertTrue(p['auto_requires_visual_qa'])
 def test_static_video(self):
  p=json.loads((ROOT/'config/project.json').read_text())
  self.assertEqual(p['text_motion'],'NONE')
  self.assertEqual(p['playback'],'ORIGINAL_SPEED_TRIM')
if __name__=='__main__':unittest.main()