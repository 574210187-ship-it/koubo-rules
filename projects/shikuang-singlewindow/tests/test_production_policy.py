import json, pathlib, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class TestProductionPolicy(unittest.TestCase):
 def test_duration(self):
  p=json.loads((ROOT/'config/project.json').read_text())
  self.assertLess(p['duration_target_seconds'],p['duration_must_be_less_than'])
 def test_no_motion(self):
  p=json.loads((ROOT/'config/project.json').read_text())
  self.assertEqual(p['text_motion'],'NONE')
  self.assertEqual(p['playback'],'ORIGINAL_SPEED_TRIM')
 def test_imagegen_only(self):
  p=json.loads((ROOT/'config/project.json').read_text())
  self.assertEqual(p['image_generation'],'IMAGEGEN_ONLY')
 def test_no_fake_auto(self):
  p=json.loads((ROOT/'config/project.json').read_text())
  self.assertTrue(p['auto_requires_real_imagegen'])
  self.assertTrue(p['auto_requires_visual_qa'])
 def test_engine_not_auto_approved(self):
  e=json.loads((ROOT/'config/engines.json').read_text())
  self.assertTrue(all(x['status']!='APPROVED' for x in e['engines']))
if __name__=='__main__':unittest.main()