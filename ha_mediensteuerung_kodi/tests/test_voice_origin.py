import importlib.util,sys,unittest,json,tempfile
from pathlib import Path
root=Path(sys.argv.pop(1));spec=importlib.util.spec_from_file_location('origin_test',root/'__init__.py',submodule_search_locations=[str(root)]);pkg=importlib.util.module_from_spec(spec);sys.modules['origin_test']=pkg;spec.loader.exec_module(pkg)
from origin_test.hmk_voice_origin import player_for_origin
from origin_test.hmk_models import MediaError
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)
  for name,rows,key in [('device',[{'id':'mic','area_id':'bed'}],'devices'),('area',[{'id':'bed','name':'Schlafzimmer','aliases':[]}],'areas')]:
   (self.path/('core.'+name+'_registry')).write_text(json.dumps({'data':{key:rows}}),encoding='utf-8')
  self.players=[{'id':'bed_kodi','room_aliases':['schlafzimmer'],'enabled':True}]
 def resolve(self,**kw):return player_for_origin({'session':'mic|user',**kw},self.players,self.path)
 def test_room(self):self.assertEqual(self.resolve(),'bed_kodi')
 def test_unknown(self):self.assertIsNone(self.resolve(session='unknown|user'))
 def test_dashboard(self):self.assertIsNone(self.resolve(input_origin='dashboard'))
 def test_disabled(self):
  self.players[0]['enabled']=False
  with self.assertRaises(MediaError):self.resolve()
 def test_ambiguous(self):
  self.players.append(dict(self.players[0],id='other'))
  with self.assertRaises(MediaError):self.resolve()
if __name__=='__main__':unittest.main()
