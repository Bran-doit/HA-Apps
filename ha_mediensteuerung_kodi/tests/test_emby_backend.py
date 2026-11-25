import copy,json,sys,types,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'appdaemon/apps'))
from ha_mediensteuerung_kodi.session_policy import select_session,supported,session_summary,SessionError
from ha_mediensteuerung_kodi.hmk_emby_player import EmbySessionPlayer
from ha_mediensteuerung_kodi.hmk_models import Media,MediaError

def session(id='session1',device='sony',**kw):return {'Id':id,'DeviceId':device,'DeviceName':'TV '+device,'Client':'Emby for Android','UserId':'media','SupportsRemoteControl':True,'PlayableMediaTypes':['Video'],'SupportedCommands':['Playstate','SetVolume','MoveUp','PlayNext'],**kw}
class Client:
 source_id='emby:server:media';user_id='media'
 def __init__(self,rows):self.rows=rows;self.posts=[]
 def get(self,path,params=None):return copy.deepcopy(self.rows)
 def post(self,path,params=None,body=None):self.posts.append((path,params,body))
 def identifier(self,value):return str(value)
class Tests(unittest.TestCase):
 def setUp(self):
  self.client=Client([session(),session('session2','bedroom')]);self.player=EmbySessionPlayer(self.client,{'target_device_id':'sony','target_client':'Emby for Android'});self.media=Media('emby:server:media','movie','8807','Das Boot',1981)
 def test_only_configured_device_receives_play(self):
  self.player.play(self.media);self.assertEqual(len(self.client.posts),1);self.assertEqual(self.client.posts[0][0],'Sessions/session1/Playing');self.assertEqual(self.client.posts[0][1]['ItemIds'],'8807')
 def test_changed_session_id_resolved_for_each_command(self):
  self.player.play(self.media);self.client.rows[0]['Id']='restarted';self.player.control('Pause');self.assertEqual(self.client.posts[-1][0],'Sessions/restarted/Playing/Pause')
 def test_offline_target_never_falls_back(self):
  self.client.rows=self.client.rows[1:]
  with self.assertRaisesRegex(MediaError,'TARGET_SESSION_OFFLINE'):self.player.play(self.media)
  self.assertFalse(self.client.posts)
 def test_unconfigured_device(self):
  self.player.config={}
  with self.assertRaisesRegex(MediaError,'TARGET_DEVICE_NOT_CONFIGURED'):self.player.play(self.media)
 def test_ambiguous_same_device_rejected(self):
  self.client.rows.append(session('duplicate'))
  with self.assertRaisesRegex(MediaError,'TARGET_SESSION_OFFLINE'):self.player.control('Stop')
 def test_wrong_profile_rejected(self):
  self.client.rows[0]['UserId']='other'
  with self.assertRaisesRegex(MediaError,'AUTHENTICATION_FAILED'):self.player.play(self.media)
 def test_remote_disabled_rejected(self):
  self.client.rows[0]['SupportsRemoteControl']=False
  with self.assertRaisesRegex(MediaError,'REMOTE_CONTROL_NOT_SUPPORTED'):self.player.play(self.media)
 def test_unsupported_commands_rejected(self):
  for command in ('PlayLast','Mute','GoHome'):
   with self.assertRaisesRegex(MediaError,'COMMAND_NOT_SUPPORTED'):
    self.player.play(self.media,command) if command=='PlayLast' else self.player.control(command)
  self.assertFalse(self.client.posts)
 def test_general_command_targets_correct_session(self):
  self.player.control('SetVolume',35);self.assertEqual(self.client.posts[0][0],'Sessions/session1/Command');self.assertEqual(self.client.posts[0][2]['Arguments'],{'Volume':'35'})
 def test_seek_requires_can_seek(self):
  with self.assertRaisesRegex(MediaError,'COMMAND_NOT_SUPPORTED'):self.player.control('Seek',10)
  self.client.rows[0].update(PlayState={'CanSeek':True},NowPlayingItem={'RunTimeTicks':300000000});self.player.control('Seek',10);self.assertEqual(self.client.posts[0][2]['SeekPositionTicks'],100000000)
 def test_invalid_volume_rejected(self):
  for value in (-1,101,True,'25'):
   with self.assertRaises(MediaError):self.player.control('SetVolume',value)
 def test_server_failure_not_retried(self):
  def post(*args,**kwargs):self.client.posts.append(args);raise MediaError('PLAYBACK_COMMAND_FAILED')
  self.client.post=post
  with self.assertRaises(MediaError):self.player.play(self.media)
  self.assertEqual(len(self.client.posts),1)
 def test_summary_excludes_stream_auth_and_urls(self):
  s=session(AccessToken='SECRET',NowPlayingItem={'Id':'1','Name':'Film','Path':'http://server?api_key=SECRET'},PlayState={'IsPaused':True,'PositionTicks':50000000,'VolumeLevel':30,'MediaSource':{'DirectStreamUrl':'SECRET'}})
  summary=session_summary(s);self.assertNotIn('SECRET',json.dumps(summary));self.assertEqual(summary['state'],'paused');self.assertEqual(summary['position_seconds'],5)
 def test_wrong_source_refused(self):
  with self.assertRaisesRegex(MediaError,'MEDIA_NOT_FOUND'):self.player.play(Media('kodi:other','movie',8807,'Das Boot'))
 def test_queue_requires_explicit_support_and_uses_playnext(self):
  self.player.play(self.media,'PlayNext');self.assertEqual(self.client.posts[0][1]['PlayCommand'],'PlayNext')
 def test_unadvertised_transport_not_assumed(self):self.assertFalse(supported(session(SupportedCommands=['SetVolume']),'Pause'))
 def test_client_identity_is_part_of_selection(self):
  self.client.rows[0]['Client']='Emby Server DLNA'
  with self.assertRaisesRegex(MediaError,'TARGET_SESSION_OFFLINE'):self.player.play(self.media)

import tempfile
for name in ('appdaemon','appdaemon.plugins','appdaemon.plugins.hass','appdaemon.plugins.hass.hassapi'):sys.modules[name]=types.ModuleType(name)
sys.modules['appdaemon.plugins.hass.hassapi'].Hass=object
from ha_mediensteuerung_kodi.hmk_backends import HAMedienBackends
class BackendTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.app=HAMedienBackends();self.app.base=Path(self.tmp.name);self.app.config_path=Path(self.tmp.name)/'players.json'
  self.config={'revision':1,'backend':'emby','default_player':'kodi_one','players':[{'id':'kodi_one','name':'Kodi','enabled':True,'room_aliases':['wohnzimmer'],'connection':{'host':'192.0.2.1','port':8080},'startup':{'enabled':False}}],'emby':{'url':'http://emby:8096','api_key':'TEST','server_id':'server','user_id':'media','target_device_id':'sony','target_device_name':'Sony','target_client':'Emby for Android'}}
  self.app.config_path.write_text(json.dumps(self.config));self.app.revision=-1;self.app.active_id='';self.app.ui={'history':[],'request_id':''};self.app.publish=lambda:None;self.app.poll=lambda kwargs:None;self.app.reload_players()
  self.client=self.app.client;self.client.get=lambda *args,**kw:[session(),session('other','bedroom')];self.posts=[];self.client.post=lambda *args,**kw:self.posts.append((args,kw))
 def test_explicit_emby_backend_uses_emby_source_and_player(self):
  self.assertEqual(self.app.media.default_source,'emby:server:media');self.assertEqual(self.app.players.default_player,'emby_target');self.assertEqual(self.app.ui['backend'],'emby')
 def test_emby_backend_never_starts_kodi(self):self.assertEqual(self.app.prepare_kodi({'action':'play'}),{'status':'emby_session_backend'})
 def test_control_through_app_addresses_one_session(self):
  self.app.execute({'action':'emby_control','command':'Pause','backend':'emby','config_revision':1});self.assertEqual(len(self.posts),1);self.assertEqual(self.posts[0][0][0],'Sessions/session1/Playing/Pause')
 def test_stale_target_revision_refused(self):
  self.app.execute({'action':'emby_control','command':'Pause','config_revision':0});self.assertFalse(self.posts);self.assertIn('geändert',self.app.ui['error'])
 def test_old_kodi_result_never_sent_to_emby(self):
  self.app.execute({'action':'play','player':'kodi_one','media_id':123});self.assertFalse(self.posts);self.assertIn('geändert',self.app.ui['error'])
 def test_switch_back_preserves_kodi(self):
  self.config['backend']='kodi';self.config['revision']=2;self.app.config_path.write_text(json.dumps(self.config));self.app.reload_players();self.assertEqual(self.app.media.default_source,'kodi:192.0.2.1:8080');self.assertEqual(self.app.players.default_player,'kodi_one')

if __name__=='__main__':unittest.main()
