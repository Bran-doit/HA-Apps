import ast, asyncio, copy, json, re, sys, tempfile, types, unittest
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT/'homeassistant/custom_components/ha_medien_kodi'
# Exercise pure validation and secret handling without installing HA on this PC.
tree=ast.parse((STAGE/'config_api.py').read_text(encoding='utf-8'))
selected=ast.Module(body=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in ('host','public_player','validate_player','power')],type_ignores=[])
ns={'copy':copy,'re':re,'uuid4':uuid4,'asyncio':asyncio}
exec(compile(selected,'config_api.py','exec'),ns)
valid=ns['validate_player'];public=ns['public_player']
def raw(name='Zimmer',host='192.0.2.1'):
 return {'name':name,'enabled':True,'room_aliases':[name.lower()],'connection':{'host':host,'port':8080,'password':'KODI-SECRET'},'startup':{'method':'sony','enabled':True,'sony':{'host':host,'pin':'SONY-SECRET'}}}
class ConfigTests(unittest.TestCase):
 def test_redaction_and_no_mutation(self):
  p=valid(raw());q=public(p);encoded=json.dumps(q)
  self.assertNotIn('KODI-SECRET',encoded);self.assertNotIn('SONY-SECRET',encoded)
  self.assertTrue(q['connection']['has_password']);self.assertTrue(q['startup']['sony']['has_pin']);self.assertEqual(p['connection']['password'],'KODI-SECRET')
 def test_blank_preserves_and_clear_removes_secrets(self):
  p=valid(raw());q=public(p);q['connection']['password']='';q['startup']['sony']['pin']=''
  v=valid(q,p);self.assertEqual(v['connection']['password'],'KODI-SECRET');self.assertEqual(v['startup']['sony']['pin'],'SONY-SECRET')
  q['connection']['clear_password']=True;q['startup']['sony']['clear_pin']=True
  v=valid(q,p);self.assertEqual(v['connection']['password'],'');self.assertEqual(v['startup']['sony']['pin'],'')
 def test_reject_url_credentials_and_invalid_port(self):
  for host in ('http://foo','user:pass@host','host/path',''):
   with self.assertRaises(ValueError):valid(raw(host=host))
  for port in (0,65536):
   p=raw();p['connection']['port']=port
   with self.assertRaises(ValueError):valid(p)
 def test_require_remote_for_remote_method(self):
  p=raw();p['startup']={'method':'remote'}
  with self.assertRaises(ValueError):valid(p)
 def test_none_never_enables_startup(self):
  p=raw();p['startup']={'method':'none','enabled':True}
  self.assertFalse(valid(p)['startup']['enabled'])
 def test_ids_stable_and_distinct(self):
  p=valid(raw());q=valid(raw('Oben','192.0.2.2'))
  self.assertNotEqual(p['id'],q['id']);self.assertEqual(valid(public(p),p)['id'],p['id'])
 def test_independent_sony_off(self):
  calls=[]
  async def request(hass,url,payload,headers=None):calls.append((url,payload,headers));return {'result':[]}
  ns['request_json']=request
  a=valid(raw());b=valid(raw('Oben','192.0.2.2'))
  asyncio.run(ns['power'](None,b,False))
  self.assertEqual(len(calls),1);self.assertIn('192.0.2.2',calls[0][0]);self.assertFalse(calls[0][1]['params'][0]['status'])
 def test_independent_remote_off(self):
  calls=[]
  async def call(*args,**kw):calls.append(args)
  hass=types.SimpleNamespace(services=types.SimpleNamespace(async_call=call))
  p=raw();p['startup']={'method':'remote','remote_entity':'remote.oben'}
  asyncio.run(ns['power'](hass,valid(p),False))
  self.assertEqual(calls,[('remote','turn_off',{'entity_id':'remote.oben'})])
# Stub AppDaemon only; use real media adapters and routing implementation.
for name in ['appdaemon','appdaemon.plugins','appdaemon.plugins.hass','appdaemon.plugins.hass.hassapi']:
 sys.modules[name]=types.ModuleType(name)
sys.modules['appdaemon.plugins.hass.hassapi'].Hass=object
sys.path.insert(0,str(ROOT/'appdaemon/apps'))
import ha_mediensteuerung_kodi.hmk_dashboard as dashboard
multi_ns={'__name__':'ha_mediensteuerung_kodi.hmk_multi','__package__':'ha_mediensteuerung_kodi'}
exec(compile((ROOT/'appdaemon/apps/ha_mediensteuerung_kodi/hmk_multi.py').read_text(encoding='utf-8'),'hmk_multi.py','exec'),multi_ns)
Multi=multi_ns['HAMedienMultiDashboard']
class RoutingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.a=valid(raw('Unten','192.0.2.1'));self.b=valid(raw('Oben','192.0.2.2'))
  self.app=Multi();self.app.config_path=Path(self.tmp.name)/'players.json';self.app.revision=-1;self.app.active_id='';self.app.ui={};self.app.events=[]
  self.app.publish=lambda:None;self.app.fire_event=lambda name,**data:self.app.events.append((name,data))
  self.save()
  self.original=dashboard.HAMedienDashboard.execute
  dashboard.HAMedienDashboard.execute=lambda app,data: {'player':app.active_id,'data':data,'source':app.client.source_id}
  self.addCleanup(setattr,dashboard.HAMedienDashboard,'execute',self.original)
 def save(self,rev=1):
  self.app.config_path.write_text(json.dumps({'revision':rev,'default_player':self.a['id'] if self.a['enabled'] else '', 'players':[self.a,self.b]}),encoding='utf-8');self.app.reload_players()
 def test_default_and_explicit_player_are_isolated(self):
  self.assertEqual(self.app.execute({'action':'search'})['player'],self.a['id'])
  self.assertEqual(self.app.execute({'action':'search','player':self.b['id']})['player'],self.b['id'])
  self.assertEqual(self.app.execute({'action':'search'})['player'],self.a['id'])
 def test_voice_room_selects_second_kodi(self):
  r=self.app.execute({'action':'voice','text':'Spiel den Film Matrix im Oben'})
  self.assertEqual(r['player'],self.b['id'])
 def test_disabled_room_does_not_fall_back(self):
  self.b['enabled']=False;self.save(2)
  self.assertIsNone(self.app.execute({'action':'voice','text':'Spiel den Film Matrix im Oben','request_id':'disabled'}))
  self.assertIn('deaktiviert',self.app.ui['error']);self.assertEqual(self.app.events[-1][1]['request_id'],'disabled')
 def test_stale_results_rejected(self):
  self.app.execute({'action':'play','config_revision':0});self.assertIn('geändert',self.app.ui['error'])
 def test_cross_source_results_rejected(self):
  self.app.execute({'action':'play','player':self.b['id'],'source':'kodi:192.0.2.1:8080'});self.assertIn('anderen',self.app.ui['error'])
 def test_lms_not_routed_even_all_disabled(self):
  self.a['enabled']=False;self.b['enabled']=False;self.save(2)
  self.app.execute({'action':'voice','text':'Spiel Musik','request_id':'lms'})
  self.assertFalse(json.loads(self.app.events[-1][1]['payload'])['handled'])
 def test_no_enabled_kodi_error(self):
  self.a['enabled']=False;self.b['enabled']=False;self.save(2)
  self.app.execute({'action':'search'});self.assertIn('Kein Kodi',self.app.ui['error'])
 def test_followup_uses_original_player(self):
  self.app.registry[self.b['id']]['voice'].pending['session']=(0,[])
  r=self.app.execute({'action':'voice','text':'Kodi nimm Film Nummer eins','session':'session'})
  self.assertEqual(r['player'],self.b['id'])
if __name__=='__main__':unittest.main()
