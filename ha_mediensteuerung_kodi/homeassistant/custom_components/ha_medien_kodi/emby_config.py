"""Private Emby setup helpers for the admin WebSocket configuration API."""
import asyncio
import re
from urllib.parse import urlsplit, urlunsplit
import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession


def public_emby(value):
    return {k:v for k,v in value.items() if k!='api_key'} | {'has_api_key':bool(value.get('api_key'))}


def validate_emby(raw, previous):
    url=str(raw.get('url','')).strip().rstrip('/')
    if url.endswith('/emby'):url=url[:-5]
    try:
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or (parsed.port is not None and not 1<=parsed.port<=65535):raise ValueError()
    except ValueError:
        raise ValueError('Bitte eine Emby-Serveradresse wie http://server:8096 ohne Zugangsdaten angeben.') from None
    key=raw.get('api_key') or (previous.get('api_key','') if previous.get('url')==url else '')
    if raw.get('clear_api_key') is True:key=''
    user=str(raw.get('user_id','')).strip()
    if user and not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',user):raise ValueError('Ungültige Emby-Benutzerkennung.')
    enabled=raw.get('enabled') is True
    if enabled and (not key or not user):raise ValueError('Bitte zuerst Zugangsschlüssel und Emby-Benutzerprofil einrichten.')
    target={k:previous.get(k) for k in ('target_device_id','target_device_name','target_client','target_aliases') if k in previous} if previous.get('url')==url and previous.get('user_id')==user else {}
    return {**target,'url':url,'api_key':str(key),'user_id':user,'enabled':enabled,'server_id':previous.get('server_id','') if previous.get('url')==url else '', 'user_name':previous.get('user_name','') if previous.get('user_id')==user else ''}


async def emby_get(hass,config,path):
    if not config.get('api_key'):raise ValueError('Bitte einen Emby-Zugangsschlüssel eingeben.')
    try:
        async with async_get_clientsession(hass).get(config['url']+'/emby/'+path,headers={'X-Emby-Token':config['api_key']},timeout=aiohttp.ClientTimeout(total=6),allow_redirects=False) as response:
            
            if response.status in (401,403):raise ValueError('AUTHENTICATION_FAILED: Emby-Anmeldung abgewiesen.')
            response.raise_for_status()
            return await response.json(content_type=None)
    except (aiohttp.ClientError,asyncio.TimeoutError):
        raise ValueError('Emby antwortet nicht oder die Anmeldung wurde abgewiesen. Serveradresse und Zugangsschlüssel prüfen.') from None


async def inspect_emby(hass,config,require_user=True):
    info=await emby_get(hass,config,'System/Info')
    server=str(info.get('Id',''))
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',server):raise ValueError('Emby lieferte keine gültige Serverkennung.')
    config['server_id']=server
    if require_user:
        if not config['user_id']:raise ValueError('Bitte ein Emby-Benutzerprofil auswählen.')
        user=await emby_get(hass,config,'Users/'+config['user_id'])
        if str(user.get('Id'))!=config['user_id']:raise ValueError('Das Emby-Benutzerprofil konnte nicht bestätigt werden.')
        config['user_name']=str(user.get('Name',''))
    return config
