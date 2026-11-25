"""Explicit Kodi or Emby-session backend; Kodi implementation is retained."""
import json
import time
import urllib.request
import urllib.error
from datetime import datetime,timezone
from .hmk_multi import HAMedienMultiDashboard
from .hmk_dashboard import HAMedienDashboard
from .hmk_emby import EmbyClient,EmbyMediaSource,EmbyArtwork
from .hmk_emby_player import EmbySessionPlayer
from .hmk_media import MediaSearch,PlayerManager
from .hmk_voice import VoiceController
from .hmk_models import MediaError

class HAMedienBackends(HAMedienMultiDashboard):
    def output_preferences(self):
        try:
            value=json.loads((self.base/'output_preferences.json').read_text())
            return value if isinstance(value,dict) else {}
        except (OSError,ValueError):return {}

    def kodi_output_available(self):
        return getattr(self,'backend','kodi')=='kodi' and str(getattr(getattr(self,'media',None),'default_source','')).startswith('kodi:')

    def publish(self):
        prefs=self.output_preferences()
        available=self.kodi_output_available()
        self.ui.update(kodi_output_available=available,show_on_kodi=available and prefs.get('show_on_kodi',True) is True,replace_current=prefs.get('replace_current',True) is True)
        super().publish()

    def reload_players(self):
        cfg=json.loads(self.config_path.read_text(encoding='utf-8'))
        backend=cfg.get('backend','kodi')
        if backend=='kodi':
            self.backend='kodi'
            super().reload_players()
            self.ui.update(backend='kodi',emby_status={})
            return
        if cfg['revision']==self.revision and getattr(self,'backend',None)=='emby':return
        c=cfg.get('emby',{})
        self.backend='emby';self.client=EmbyClient(c)
        source=EmbyMediaSource(self.client);self.media=MediaSearch({source.source_id:source},source.source_id)
        self.emby_player=EmbySessionPlayer(self.client,c)
        self.players=PlayerManager({'emby_target':self.emby_player},'emby_target')
        self.player_name=c.get('target_device_name') or 'Kein Emby-Gerät ausgewählt'
        self.artwork=EmbyArtwork(self.client)
        aliases=c.get('target_aliases') or ['familienzimmer','wohnzimmer','fernseher','kodi','google tv']
        self.voice=VoiceController(self.media,self.players,room_aliases=aliases,player_name=self.player_name)
        self.registry={'emby_target':{}};self.active_id=self.default_id='emby_target';self.revision=cfg['revision']
        self.ui.update(backend='emby',player_id='emby_target',source_id=source.source_id,config_revision=self.revision,target_name=self.player_name,items=[],total=0,heading='Noch keine Suche',view='search',voice_text='',voice_speech='',now_playing=[],error='',emby_status={})
    def prepare_kodi(self,data):
        return {'status':'emby_session_backend'} if self.backend=='emby' else super().prepare_kodi(data)
    def diagnostic(self,query):
        if self.backend=='kodi':return super().diagnostic(query)
        info=self.client.get('System/Info');source=self.media.source()
        return {'server_connected':bool(info.get('Id')),'movies':source.items({'IncludeItemTypes':'Movie'},1).to_dict(),'series':source.items({'IncludeItemTypes':'Series'},1).to_dict(),'target':self.emby_player.status(),'sources':[source.source_id],'players':['emby_target']}
    def poll_emby_server(self,force=False):
        # Server availability is independent of the chosen player/backend.
        now=time.monotonic()
        try:
            cfg=json.loads(self.config_path.read_text(encoding='utf-8')).get('emby',{})
            signature=(cfg.get('url'),cfg.get('api_key'),cfg.get('server_id'))
            cached=getattr(self,'_emby_server_probe',None)
            if not force and cached and cached[0]==signature and now-cached[1]<25:
                return
            self._emby_server_probe=(signature,now)
            result={'state':'not_configured','reachable':False,'checked_at':datetime.now(timezone.utc).isoformat(),'message':'Emby ist noch nicht eingerichtet.'}
            if cfg.get('url') and cfg.get('api_key'):
                request=urllib.request.Request(cfg['url'].rstrip('/')+'/emby/System/Info',headers={'X-Emby-Token':cfg['api_key']})
                class NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self,*args,**kwargs):return None
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
                with opener.open(request,timeout=2) as response:
                    data=json.load(response)
                if not isinstance(data,dict) or not data.get('Id') or (cfg.get('server_id') and data['Id']!=cfg['server_id']):
                    result.update(state='invalid_response',message='Emby-Serverantwort passt nicht zur Konfiguration.')
                else:
                    result.update(state='reachable',reachable=True,message='Emby-Server erreichbar',server_name=str(data.get('ServerName','Emby'))[:100])
        except urllib.error.HTTPError as exc:
            result={'state':'authentication_failed' if exc.code in (401,403) else 'unreachable','reachable':False,'checked_at':datetime.now(timezone.utc).isoformat(),'message':'Emby-Anmeldung fehlgeschlagen.' if exc.code in (401,403) else 'Emby-Server nicht erreichbar.'}
        except Exception:
            result={'state':'unreachable','reachable':False,'checked_at':datetime.now(timezone.utc).isoformat(),'message':'Emby-Server nicht erreichbar oder Antwort ungültig.'}
        self.ui['emby_server']=result

    def poll(self,kwargs):
        try:self.ui['show_on_kodi']=json.loads((self.base/'output_preferences.json').read_text()).get('show_on_kodi',True) is True
        except (OSError,ValueError):self.ui['show_on_kodi']=True
        self.poll_emby_server()

        try:self.reload_players()
        except Exception:
            self.ui.update(connected=False,connection_error='Die Backend-Konfiguration konnte nicht geladen werden.');self.publish();return
        if self.backend=='kodi':return super().poll(kwargs)
        try:
            s=self.emby_player.status()
            playing=self.emby_player.get_now_playing() if s['item_id'] else ()
            self.ui.update(connected=True,connection_error='',emby_status=s,now_playing=[p.to_dict() for p in playing])
        except MediaError as exc:
            self.ui.update(connected=False,connection_error=str(exc),emby_status={'state':'unavailable','error_code':str(exc).split(':')[0]},now_playing=[])
        self.ui['checked_at']=datetime.now(timezone.utc).isoformat();self.publish()
    def execute(self,data):
        self.reload_players()
        preference=self.base/'output_preferences.json'
        prefs=self.output_preferences()
        if data.get('action') in ('output_settings','playback_settings'):
            key='show_on_kodi' if data['action']=='output_settings' else 'replace_current'
            if type(data.get(key)) is not bool:
                return self.failed(data,'Ungültige Einstellung.')
            if key=='show_on_kodi' and data[key] and not self.kodi_output_available():
                return self.failed(data,'Die Kodi-Trefferanzeige ist nur mit Kodi und seiner lokalen Bibliothek verfügbar.')
            prefs[key]=data[key]
            temp=preference.with_suffix('.tmp');temp.write_text(json.dumps(prefs));temp.replace(preference)
            self.ui.update(completed_request_id=data.get('request_id',''),busy=False,error='')
            self.publish();return
        data={**data,'show_on_kodi':self.kodi_output_available() and prefs.get('show_on_kodi',True) is True,'replace_current':prefs.get('replace_current',True) is True}
        if data.get('action')=='voice' and data.get('input_origin')=='dashboard':
            import re
            if not re.search(r'\b(?:filme?|staffel|folge|kinderfilme?|familienfilme?)\b',str(data.get('text','')),re.I):
                self.ui.update(last_voice_text=str(data.get('text','')),last_voice_interpretation='Kein Medien-Codewort erkannt',last_voice_response='Bitte Film, Staffel oder Folge nennen, zum Beispiel: Suche den Film Matrix.',last_voice_at=datetime.now(timezone.utc).isoformat(),last_voice_target=self.player_name,last_voice_backend=self.backend)
                return self.failed(data,'Bitte Film, Staffel oder Folge nennen, zum Beispiel: Suche den Film Matrix.')
        if data.get('action')=='server_status':
            self.poll_emby_server(force=True)
            self.ui.update(completed_request_id=data.get('request_id',''),busy=False)
            self.publish()
            return
        if self.backend=='kodi':
            if data.get('backend')=='emby':return self.failed(data,'Die Backend-Auswahl wurde geändert. Bitte erneut suchen.')
            return super().execute(data)
        if data.get('backend') not in (None,'emby') or data.get('player') not in (None,'emby_target') or data.get('source') not in (None,self.media.default_source) or data.get('config_revision') not in (None,self.revision):
            return self.failed(data,'Die Backend-/Zielkonfiguration wurde geändert. Bitte erneut suchen.')
        if data.get('action') in ('emby_control','emby_queue'):
            try:
                self.ui.update(busy=True,error='');self.publish()
                if data['action']=='emby_control':result=self.emby_player.control(data.get('command'),data.get('value'))
                else:
                    if data.get('command') not in ('PlayNext','PlayLast'):raise MediaError('COMMAND_NOT_SUPPORTED: Ungültiger Warteschlangenbefehl.')
                    if data.get('media_type') not in ('movie','episode'):raise MediaError('MEDIA_NOT_FOUND: Bitte Film oder Episode auswählen.')
                    m=self.media.get_movie(data['media_id']) if data['media_type']=='movie' else self.media.get_episode(data['media_id'])
                    result=self.emby_player.play(m,data['command'])
                self.ui.update(last_ok=True,action=data['action'],elapsed_ms=0,busy=False,completed_request_id=data.get('request_id',''))
                self.ui['history']=([{'at':datetime.now(timezone.utc).isoformat(),'action':data.get('command'),'ok':True,'ms':0,'error':''}]+self.ui['history'])[:10]
                self.poll({});return result
            except MediaError as exc:return self.failed(data,str(exc))
        return HAMedienDashboard.execute(self,{**data,'player':'emby_target'})
    def failed(self,data,message):
        self.ui.update(error=message,busy=False,last_ok=False,completed_request_id=data.get('request_id',''));self.publish()
        if data.get('action')=='voice':self.fire_event('ha_mediensteuerung_kodi_voice_result',request_id=data.get('request_id',''),payload=json.dumps({'handled':True,'status':'error','speech':message},ensure_ascii=False))
