import ast,copy,json,sys,types,unittest
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
import re
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'appdaemon/apps'))
from ha_mediensteuerung_kodi.hmk_models import Media,MediaError
from ha_mediensteuerung_kodi.hmk_emby import EmbyClient,EmbyMediaSource,EmbyArtwork
from ha_mediensteuerung_kodi.hmk_identity import identities,same_identity,EmbyKodiResolver
from ha_mediensteuerung_kodi.hmk_kodi import KodiMediaSource
from ha_mediensteuerung_kodi.hmk_media import PlayerManager

def item(id='10',kind='Movie',**kw):return {'Id':id,'Type':kind,'Name':'Matrix','ProductionYear':1999,'ProviderIds':{'Imdb':'tt0133093'},'UserData':{'Played':False,'PlaybackPositionTicks':120000000},**kw}
class FakeEmby:
 source_id='emby:server:profile';server_id='server';user_id='profile'
 identifier=staticmethod(EmbyClient.identifier)
 def __init__(self,answers):self.answers=iter(answers);self.calls=[]
 def get(self,path,params=None,**kw):self.calls.append((path,params));return next(self.answers)
class SourceTests(unittest.TestCase):
 def test_metadata_profile_status_ticks_and_identity(self):
  s=EmbyMediaSource(FakeEmby([]));m=s.media(item(RunTimeTicks=900000000,Genres=['Science Fiction'],People=[{'Type':'Actor','Name':'Keanu Reeves'}]))
  self.assertEqual(m.play_count,0);self.assertEqual(m.resume_seconds,12);self.assertEqual(m.runtime,90);self.assertEqual(m.actors,('Keanu Reeves',));self.assertEqual(m.provider_ids['emby:server'],'10')
 def test_unknown_watch_status_not_unseen(self):
  self.assertIsNone(EmbyMediaSource(FakeEmby([])).media(item(UserData={})).play_count)
 def test_played_controls_status_not_start_count(self):
  self.assertEqual(EmbyMediaSource(FakeEmby([])).media(item(UserData={'Played':False,'PlayCount':3})).play_count,0)
 def test_pagination_and_profile_scoping(self):
  c=FakeEmby([{'Items':[item('10')],'TotalRecordCount':2},{'Items':[item('11')],'TotalRecordCount':2}]);page=EmbyMediaSource(c).items({'IncludeItemTypes':'Movie'})
  self.assertEqual(len(page.items),2);self.assertEqual(c.calls[1][1]['StartIndex'],1);self.assertIn('Users/profile/Items',c.calls[0][0])
 def test_partial_result_marked_truncated(self):
  c=FakeEmby([{'Items':[item('10')],'TotalRecordCount':2}]);page=EmbyMediaSource(c).search_media('Matrix',limit=1);self.assertTrue(page.truncated)
 def test_duplicate_incomplete_and_changing_total_rejected(self):
  for pages in ([{'Items':[],'TotalRecordCount':1}],[{'Items':[item(),item()],'TotalRecordCount':2}],[{'Items':[item()],'TotalRecordCount':2},{'Items':[item('11')],'TotalRecordCount':3}]):
   with self.assertRaises(MediaError):EmbyMediaSource(FakeEmby(pages)).items({})
 def test_wrong_detail_kind_rejected(self):
  with self.assertRaises(MediaError):EmbyMediaSource(FakeEmby([item(kind='Series')])).get_movie('10')
 def test_seasons_and_episode_order(self):
  rows=[item('1','Episode',ParentIndexNumber=2,IndexNumber=3),item('2','Episode',ParentIndexNumber=1,IndexNumber=1)]
  c=FakeEmby([{'Items':rows,'TotalRecordCount':2}]);page=EmbyMediaSource(c).get_episodes('show',2)
  self.assertEqual(len(page.items),1);self.assertEqual(page.items[0].episode,3);self.assertEqual(c.calls[0][1]['ParentId'],'show')
 def test_no_tokens_or_raw_streams_in_media(self):
  m=EmbyMediaSource(FakeEmby([])).media(item(Path='http://host?api_key=secret',ImageTags={'Primary':'tag'}))
  self.assertNotIn('secret',json.dumps(m.to_dict()));self.assertEqual(m.file,'');self.assertEqual(m.thumbnail,'emby-image:server:10')
 def test_identifier_rejects_path_injection(self):
  for v in ('../Users','a?api_key=x','a/b',''):
   with self.assertRaises(MediaError):EmbyClient.identifier(v)

class ResolverTests(unittest.TestCase):
 def setUp(self):
  self.media=EmbyMediaSource(FakeEmby([])).media(item())
  self.row={'movieid':77,'title':'Matrix','year':1999,'file':'http://127.0.0.1:57342/movies/server/3/0/10/m-77-1/file.mkv','uniqueid':{'imdb':'tt0133093'},'resume':{'position':12},'playcount':0}
  self.calls=[]
  def rpc(method,params):
   self.calls.append((method,params))
   return {'movies':[copy.deepcopy(self.row)],'limits':{'total':1}} if method.endswith('GetMovies') else {'moviedetails':copy.deepcopy(self.row)}
  self.client=types.SimpleNamespace(source_id='kodi:target:8080',rpc=rpc)
  self.source=types.SimpleNamespace(source_id=self.media.source,get_movie=lambda id:self.media)
  self.resolver=EmbyKodiResolver(self.source,KodiMediaSource(self.client))
 def test_emby_id_to_target_kodi_id(self):
  m=self.resolver(self.media);self.assertEqual(m.library_id,77);self.assertEqual(m.source,'kodi:target:8080');self.assertEqual(len(self.calls),2)
 def test_native_identity_extraction_does_not_guess_remote_url(self):
  self.assertEqual(identities({'file':'http://example.com/movies/server/3/0/10/m/file'},'movie'),{})
 def test_missing_target_refused(self):
  self.row['uniqueid']={};self.row['file']='http://127.0.0.1:57342/movies/server/3/0/99/m/file'
  with self.assertRaises(MediaError):self.resolver(self.media)
 def test_duplicate_target_refused(self):
  self.client.rpc=lambda m,p:{'movies':[self.row,{**self.row,'movieid':78}],'limits':{'total':2}}
  with self.assertRaises(MediaError):self.resolver(self.media)
 def test_changed_target_checked_again(self):
  original=self.client.rpc
  def rpc(m,p):
   r=original(m,p)
   if m.endswith('GetMovieDetails'):r['moviedetails']['file']='http://127.0.0.1:57342/movies/server/3/0/99/m/file'
   return r
  self.client.rpc=rpc
  with self.assertRaises(MediaError):self.resolver(self.media)
 def test_resume_mismatch_does_not_start_wrong_position(self):
  self.row['resume']['position']=100
  with self.assertRaises(MediaError):self.resolver(replace(self.media,start_resume=True))
 def test_newly_watched_refused(self):
  self.source.get_movie=lambda id:replace(self.media,play_count=1)
  with self.assertRaises(MediaError):self.resolver(replace(self.media,require_unwatched=True))
 def test_startup_occurs_before_resolve_and_play(self):
  events=[];p=types.SimpleNamespace(can_play=lambda m:False,get_now_playing=lambda:(),play=lambda m:events.append('play'),verify=lambda m:{'verified':True})
  manager=PlayerManager({'target':p},'target');manager.before_play=lambda:events.append('start')
  manager.resolve_media=lambda *args:(events.append('resolve') or self.media)
  manager.play(self.media,replace_current=True);self.assertEqual(events,['start','resolve','play'])

# Validate the configuration helpers without installing HA on Windows.
tree=ast.parse((ROOT/'homeassistant/custom_components/ha_medien_kodi/emby_config.py').read_text(encoding='utf-8'))
subset=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)],type_ignores=[])
ns={'re':re,'urlsplit':urlsplit,'urlunsplit':urlunsplit};exec(compile(subset,'emby_config.py','exec'),ns)
class ConfigTests(unittest.TestCase):
 def test_secret_redacted(self):self.assertNotIn('secret',json.dumps(ns['public_emby']({'api_key':'secret','url':'http://server'})))
 def test_blank_preserves_same_host_only(self):
  prev={'url':'http://server:8096','api_key':'secret'}
  self.assertEqual(ns['validate_emby']({'url':'http://server:8096/emby'},prev)['api_key'],'secret')
  self.assertEqual(ns['validate_emby']({'url':'http://other:8096'},prev)['api_key'],'')
 def test_clear_key(self):self.assertEqual(ns['validate_emby']({'url':'http://server','clear_api_key':True},{'url':'http://server','api_key':'secret'})['api_key'],'')
 def test_activation_requires_profile_and_key(self):
  with self.assertRaises(ValueError):ns['validate_emby']({'url':'http://server','enabled':True},{})
 def test_reject_url_credentials_and_query(self):
  for url in ('http://user:secret@host','http://host?api_key=secret','file:///etc/passwd','http://host:99999'):
   with self.assertRaises(ValueError):ns['validate_emby']({'url':url},{})

# App-level wiring: two independent targets share one Emby source without waking Kodi for searches.
import tempfile
for name in ('appdaemon','appdaemon.plugins','appdaemon.plugins.hass','appdaemon.plugins.hass.hassapi'):
 sys.modules[name]=types.ModuleType(name)
sys.modules['appdaemon.plugins.hass.hassapi'].Hass=object
from ha_mediensteuerung_kodi.hmk_multi import HAMedienMultiDashboard
class WiringTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.config={'revision':1,'default_player':'one','emby':{'enabled':True,'url':'http://emby:8096','api_key':'FAKE-KEY','server_id':'server','user_id':'profile'},'players':[{'id':id,'enabled':True,'name':id,'room_aliases':[id],'connection':{'host':host,'port':8080},'startup':{'enabled':False,'method':'none','bring_to_front':False}} for id,host in [('one','192.0.2.1'),('two','192.0.2.2')]]}
  self.app=HAMedienMultiDashboard();self.app.config_path=Path(self.tmp.name)/'players.json';self.app.config_path.write_text(json.dumps(self.config));self.app.ui={};self.app.revision=-1;self.app.active_id='';self.app.reload_players()
 def test_shared_source_independent_target_clients(self):
  a,b=self.app.registry.values();self.assertEqual(a['media'].default_source,b['media'].default_source);self.assertNotEqual(a['client'].source_id,b['client'].source_id);self.assertIn(('emby:server:profile','two'),b['players'].resolvers)
 def test_central_search_does_not_start_kodi(self):
  self.assertEqual(self.app.prepare_kodi({'action':'search'})['status'],'central_search')
  self.assertEqual(self.app.prepare_kodi({'action':'voice'})['status'],'deferred_until_play')
 def test_result_source_is_central_not_target(self):
  self.app.activate('two');self.assertEqual(self.app.ui['source_id'],'emby:server:profile');self.assertEqual(self.app.ui['player_id'],'two')
 def test_disabled_emby_preserves_kodi_source(self):
  self.config['emby']['enabled']=False;self.config['revision']=2;self.app.config_path.write_text(json.dumps(self.config));self.app.reload_players();self.assertEqual(self.app.media.default_source,'kodi:192.0.2.1:8080')

if __name__=='__main__':unittest.main()
