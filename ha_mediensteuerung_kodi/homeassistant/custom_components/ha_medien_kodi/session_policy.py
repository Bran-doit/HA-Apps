"""Shared session selection policy; no persisted SessionId and no fallback device."""
class SessionError(ValueError):
    def __init__(self,code,message):
        self.code=code
        super().__init__(code+': '+message)

TRANSPORT={'PlayPause','Pause','Unpause','Stop','NextTrack','PreviousTrack','Seek'}
GENERAL={'VolumeUp','VolumeDown','Mute','Unmute','ToggleMute','SetVolume','MoveUp','MoveDown','MoveLeft','MoveRight','Select','Back','GoHome','GoToSearch','SendString','DisplayContent'}

def select_session(sessions,device_id,user_id,client_name=''):
    if not device_id:raise SessionError('TARGET_DEVICE_NOT_CONFIGURED','Bitte ein Emby-Wiedergabegerät auswählen.')
    matches=[s for s in sessions if s.get('DeviceId')==device_id and (not client_name or s.get('Client')==client_name)]
    if not matches:raise SessionError('TARGET_SESSION_OFFLINE','Das konfigurierte Emby-Gerät ist momentan nicht verfügbar.')
    if len(matches)!=1:raise SessionError('TARGET_SESSION_OFFLINE','Mehrere Sessions melden dieselbe Gerätekennung; bitte die Emby-App neu verbinden.')
    s=matches[0]
    if not s.get('Id'):raise SessionError('TARGET_SESSION_OFFLINE','Die Emby-Session ist ungültig.')
    if s.get('SupportsRemoteControl') is not True:raise SessionError('REMOTE_CONTROL_NOT_SUPPORTED','Dieser Emby-Client erlaubt keine Fernsteuerung.')
    if s.get('UserId')!=user_id:raise SessionError('AUTHENTICATION_FAILED','Emby-Client und Medienquelle verwenden nicht dasselbe Benutzerprofil.')
    return s

def supported(s,command):
    commands=set(s.get('SupportedCommands') or [])
    if s.get('SupportsRemoteControl') is not True:return False
    if command=='PlayNow':return 'Video' in (s.get('PlayableMediaTypes') or [])
    if command in ('PlayNext','PlayLast'):return command in commands
    if command=='Seek':return s.get('PlayState',{}).get('CanSeek') is True and (command in commands or 'Playstate' in commands)
    if command in TRANSPORT:return command in commands or 'Playstate' in commands
    return command in GENERAL and command in commands

def session_summary(s):
    item=s.get('NowPlayingItem') or {};play=s.get('PlayState') or {}
    return {'session_id':s.get('Id',''),'device_id':s.get('DeviceId',''),'device_name':s.get('DeviceName',''),'client':s.get('Client',''),'user_id':s.get('UserId',''),'user_name':s.get('UserName',''),'last_activity':s.get('LastActivityDate',''),'remote_control':s.get('SupportsRemoteControl') is True,'supported_commands':list(s.get('SupportedCommands') or []),'commands':[c for c in sorted(TRANSPORT|GENERAL|{'PlayNow','PlayNext','PlayLast'}) if supported(s,c)],'title':item.get('Name',''),'item_id':str(item.get('Id','')),'media_type':item.get('Type',''),'position_seconds':(play.get('PositionTicks') or 0)/10000000,'duration_seconds':(item.get('RunTimeTicks') or 0)/10000000,'paused':play.get('IsPaused') is True,'volume':play.get('VolumeLevel'),'muted':play.get('IsMuted'),'state':'paused' if item and play.get('IsPaused') else 'playing' if item else 'idle','has_cover':bool((item.get('ImageTags') or {}).get('Primary'))}
