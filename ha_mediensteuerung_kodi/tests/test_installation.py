import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
import installer
from entrypoint import prepare_runtime
class InstallTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.bundle=self.root/'bundle';self.ha=self.root/'ha';self.data=self.root/'data';self.legacy=self.root/'legacy'
  for p in (self.bundle/'homeassistant/www',self.ha,self.data,self.legacy/'apps'):p.mkdir(parents=True)
  (self.bundle/'homeassistant/www/card.js').write_text('version one')
 def install(self,replace=False):return installer.install(self.bundle,self.ha,self.data,replace)
 def test_clean_install_and_idempotence(self):
  self.assertEqual(self.install(),1);self.assertEqual(self.install(),0)
  self.assertEqual(json.loads((self.ha/'ha_medien_kodi_private/players.json').read_text())['players'],[])
 def test_upgrade_preserves_private_config_and_backs_up(self):
  self.install();private=self.ha/'ha_medien_kodi_private/players.json';private.write_text('{"private":"TEST"}')
  (self.bundle/'homeassistant/www/card.js').write_text('version two');self.assertEqual(self.install(),1)
  self.assertEqual(private.read_text(),'{"private":"TEST"}')
  self.assertTrue(any(p.read_text()=='version one' for p in (self.data/'backups').rglob('card.js')))
 def test_unknown_files_refuse_without_partial_writes(self):
  (self.ha/'www').mkdir();(self.ha/'www/card.js').write_text('user version')
  with self.assertRaises(installer.SetupError):self.install()
  self.assertFalse((self.ha/'ha_medien_kodi_private').exists())
 def test_explicit_migration_backup(self):
  (self.ha/'www').mkdir();(self.ha/'www/card.js').write_text('old application')
  self.install(True)
  self.assertTrue(any(p.read_text()=='old application' for p in (self.data/'backups').rglob('card.js')))
 def test_partial_failure_restores_previous_files(self):
  self.install();(self.bundle/'homeassistant/www/card.js').write_text('version two')
  (self.bundle/'homeassistant/www/second.js').write_text('second')
  original=installer.atomic
  def fail(path,content):
   if path==self.ha/'www/second.js':raise OSError('simulated full disk')
   original(path,content)
  with patch.object(installer,'atomic',side_effect=fail):
   with self.assertRaises(OSError):self.install()
  self.assertEqual((self.ha/'www/card.js').read_text(),'version one')
 def test_legacy_active_then_disabled(self):
  p=self.legacy/'apps/apps.yaml';p.write_text('media:\n  module: ha_mediensteuerung_kodi.hmk_backends\n')
  self.assertTrue(installer.legacy_active(self.legacy));p.write_text(p.read_text()+'  disable: true\n');self.assertFalse(installer.legacy_active(self.legacy))
 def test_preferences_import_once(self):
  p=self.legacy/'ha_mediensteuerung_kodi';p.mkdir();(p/'output_preferences.json').write_text('{"show_on_kodi":false,"replace_current":true,"private":"ignored"}')
  self.assertTrue(installer.import_preferences(self.legacy,self.data));self.assertFalse(installer.import_preferences(self.legacy,self.data))
  self.assertEqual(json.loads((self.data/'media/output_preferences.json').read_text()),{'show_on_kodi':False,'replace_current':True})
 def test_runtime_never_saves_token(self):
  (self.bundle/'appdaemon/apps/ha_mediensteuerung_kodi').mkdir(parents=True)
  config=prepare_runtime(self.data,self.bundle,'TEST-SECRET-NOT-TO-PERSIST',self.root/'runtimeapps')
  self.assertNotIn('TEST-SECRET',(config/'appdaemon.yaml').read_text())
  self.assertIn('!env_var SUPERVISOR_TOKEN',(config/'appdaemon.yaml').read_text())
 def test_no_write_outside_ha(self):
  with self.assertRaises(installer.SetupError):installer.inside(self.ha,'../outside')
if __name__=='__main__':unittest.main()
