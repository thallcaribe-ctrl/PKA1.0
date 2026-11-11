import json,tempfile,unittest
from pathlib import Path
from helper_diagnostics import Journal,safe_state
class DiagnosticTests(unittest.TestCase):
 def test_secrets_are_not_recorded(self):
  state={'config':{'token':'secret'},'url':'secret','frame':{'online':True},'engine':{}}
  self.assertNotIn('secret',json.dumps(safe_state(state)))
 def test_connection_changes_and_ocr_are_deduplicated(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'runtime/tmp')as folder:
   j=Journal(folder);state={'frame':{'online':True},'utc':'one'};j.observe(state);state['utc']='two';j.observe(state);state['frame']['online']=False;j.observe(state)
   j.visible_text('message','one.png');j.visible_text('message','two.png')
   rows=[json.loads(line)for line in j.path.read_text().splitlines()]
   self.assertEqual([r['kind']for r in rows],['state_change','state_change','visible_text_ocr'])
   self.assertTrue(rows[-1]['approximate'])
 def test_storage_limit_does_not_delete_existing_evidence(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'runtime/tmp')as folder:
   j=Journal(folder,budget=100);p=Path(folder)/'evidence.png';p.write_bytes(b'evidence')
   self.assertFalse(j.quota(100));self.assertTrue(p.exists())
 def test_missing_player_is_supported(self):
  self.assertIsNone(safe_state({'frame':{'player':None}})['position'])
if __name__=='__main__':unittest.main()
