"""Emby session player using a fresh DeviceId resolution for every command."""
import time
from .hmk_models import MediaError,Playing
from .session_policy import select_session,supported,session_summary,SessionError,TRANSPORT,GENERAL

class EmbySessionPlayer:
    def __init__(self,client,config):
        self.client=client;self.config=config;self.sent_session=None
    def session(self):
        try:return select_session(self.client.get('Sessions',{'DeviceId':self.config.get('target_device_id',''),'ControllableByUserId':self.client.user_id}),self.config.get('target_device_id',''),self.client.user_id,self.config.get('target_client',''))
        except SessionError as exc:raise MediaError(str(exc)) from None
    def status(self):return session_summary(self.session())
    def can_play(self,media):return media.source==self.client.source_id and media.kind in ('movie','episode')
    def play(self,media,command='PlayNow'):
        if not self.can_play(media):raise MediaError('MEDIA_NOT_FOUND: Der Eintrag gehört nicht zu dieser Emby-Quelle.')
        s=self.session()
        if not supported(s,command):raise MediaError('COMMAND_NOT_SUPPORTED: Dieser Client bestätigt den Wiedergabebefehl nicht.')
        sid=self.client.identifier(s['Id'])
        params={'ItemIds':self.client.identifier(media.library_id),'PlayCommand':command}
        if media.start_resume:params['StartPositionTicks']=int(media.resume_seconds*10000000)
        self.client.post('Sessions/'+sid+'/Playing',params,{'ControllingUserId':self.client.user_id})
        self.sent_session=sid
        return {'accepted':True,'session_id':sid,'device_id':self.config['target_device_id'],'command':command}
    def get_now_playing(self):
        s=self.status()
        return (Playing(s['title'],s['media_type'].casefold(),s['item_id'],0 if s['paused'] else 1,s['position_seconds'],s['duration_seconds']),) if s['item_id'] else ()
    def verify(self,media):
        previous=None
        for attempt in range(8):
            s=self.status()
            if s['session_id']!=self.sent_session:break
            if s['item_id']==str(media.library_id) and not s['paused']:
                if previous is not None and s['position_seconds']>previous:return {'verified':True,'device_id':s['device_id'],'session_id':s['session_id']}
                previous=s['position_seconds']
            time.sleep(1)
        return {'verified':False,'error_code':'PLAYBACK_COMMAND_FAILED'}
    def control(self,command,value=None):
        s=self.session()
        if not supported(s,command):raise MediaError('COMMAND_NOT_SUPPORTED: Der Client meldet diesen Befehl nicht als unterstützt.')
        sid=self.client.identifier(s['Id'])
        if command in TRANSPORT:
            body={'Command':command,'ControllingUserId':self.client.user_id}
            if command=='Seek':
                if type(value) not in (int,float) or value<0 or value>(s.get('NowPlayingItem',{}).get('RunTimeTicks',0)/10000000):raise MediaError('COMMAND_NOT_SUPPORTED: Ungültige Zielposition.')
                body['SeekPositionTicks']=int(value*10000000)
            self.client.post('Sessions/'+sid+'/Playing/'+command,body=body)
        else:
            arguments={}
            if command=='SetVolume':
                if type(value) is not int or not 0<=value<=100:raise MediaError('COMMAND_NOT_SUPPORTED: Lautstärke muss zwischen 0 und 100 liegen.')
                arguments={'Volume':str(value)}
            elif command=='SendString':
                if not isinstance(value,str) or not 1<=len(value)<=200:raise MediaError('COMMAND_NOT_SUPPORTED: Bitte höchstens 200 Zeichen senden.')
                arguments={'String':value}
            elif command=='DisplayContent':
                arguments={'ItemId':self.client.identifier(value)}
            self.client.post('Sessions/'+sid+'/Command',body={'Name':command,'Arguments':arguments,'ControllingUserId':self.client.user_id})
        return {'accepted':True,'device_id':self.config['target_device_id'],'session_id':sid,'command':command}
