"""Emby library adapter. Tokens never occur in returned media or URLs."""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from .hmk_models import Media, MediaPage, Season, MediaError
from .hmk_kodi import NoRedirect

FIELDS = 'DateCreated,OriginalTitle,Genres,People,Overview,ProviderIds,UserData,ChildCount,ProductionYear,RunTimeTicks,OfficialRating,PremiereDate,ParentIndexNumber,IndexNumber,SeriesName'
TYPES = {'movie':'Movie','series':'Series','episode':'Episode'}

class EmbyClient:
    def __init__(self, config):
        self.origin = config['url'].rstrip('/')
        self.timings = []
        self.token = config['api_key']
        self.user_id = self.identifier(config['user_id'])
        self.server_id = self.identifier(config['server_id'])
        self.source_id = 'emby:'+self.server_id+':'+self.user_id
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    @staticmethod
    def identifier(value):
        value = str(value)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
            raise MediaError('Ungültige Emby-Kennung.')
        return value
    def get(self, path, params=None, binary=False):
        url=self.origin+'/emby/'+path.lstrip('/')
        if params:url+='?'+urllib.parse.urlencode(params)
        request=urllib.request.Request(url,headers={'X-Emby-Token':self.token,'Accept':'application/json'})
        try:
            with self.opener.open(request,timeout=8) as response:
                if binary:
                    content=response.read(4*1024*1024+1)
                    return content if len(content)<=4*1024*1024 and (content.startswith(bytes.fromhex('ffd8ff')) or content.startswith(bytes.fromhex('89504e470d0a1a0a')) or (content[:4]==b'RIFF' and content[8:12]==b'WEBP')) else b''
                return json.load(response)
        except urllib.error.HTTPError as exc:
            code='AUTHENTICATION_FAILED' if exc.code in (401,403) else 'MEDIA_NOT_FOUND' if exc.code==404 else 'EMBY_SERVER_UNAVAILABLE'
            raise MediaError(code+': Emby-Anfrage abgewiesen.') from None
        except (urllib.error.URLError,TimeoutError,OSError,ValueError):
            raise MediaError('EMBY_SERVER_UNAVAILABLE: Emby nicht erreichbar oder Anmeldung abgewiesen. Bitte die Medienquelle prüfen.') from None

    def post(self,path,params=None,body=None):
        url=self.origin+'/emby/'+path
        if params:url+='?'+urllib.parse.urlencode(params)
        request=urllib.request.Request(url,data=json.dumps(body or {}).encode(),headers={'X-Emby-Token':self.token,'Content-Type':'application/json'},method='POST')
        try:
            with self.opener.open(request,timeout=8) as response:response.read(1024)
        except urllib.error.HTTPError as exc:
            code='AUTHENTICATION_FAILED' if exc.code in (401,403) else 'TARGET_SESSION_OFFLINE' if exc.code==404 else 'PLAYBACK_COMMAND_FAILED'
            raise MediaError(code+': Emby-Steuerbefehl wurde abgewiesen.') from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise MediaError('PLAYBACK_COMMAND_FAILED: Keine Bestätigung vom Server; Befehl wird nicht automatisch wiederholt.') from None

class EmbyMediaSource:
    def __init__(self, client):
        self.client=client
        self.source_id=client.source_id
    def media(self, row):
        kind={v:k for k,v in TYPES.items()}.get(row.get('Type'))
        if kind is None:raise MediaError('Emby lieferte einen unerwarteten Medientyp.')
        item_id=self.client.identifier(row['Id'])
        user=row.get('UserData') or {}
        played=user.get('Played')
        # Played, not merely a start counter, determines watched status.
        play_count=1 if played is True else 0 if played is False else None
        identities={str(k).casefold():str(v) for k,v in (row.get('ProviderIds') or {}).items() if v}
        identities['emby:'+self.client.server_id]=item_id
        return Media(source=self.source_id,kind=kind,library_id=item_id,title=row.get('Name',''),year=row.get('ProductionYear') or 0,
            thumbnail='emby-image:'+self.client.server_id+':'+item_id if (row.get('ImageTags') or {}).get('Primary') else '',
            season=row.get('ParentIndexNumber',-1),episode=row.get('IndexNumber',-1),aliases=tuple([row['OriginalTitle']] if row.get('OriginalTitle') else []),
            genres=tuple(row.get('Genres') or []),actors=tuple(p['Name'] for p in row.get('People',[]) if p.get('Type')=='Actor' and p.get('Name')),
            plot=row.get('Overview',''),runtime=int((row.get('RunTimeTicks') or 0)/10_000_000),certification=row.get('OfficialRating',''),
            play_count=play_count,resume_seconds=(user.get('PlaybackPositionTicks') or 0)/10_000_000,
            date_added=row.get('DateCreated') or '',first_aired=(row.get('PremiereDate') or '')[:10],show_title=row.get('SeriesName',''),provider_ids=identities)
    def items(self, params, limit=None):
        rows=[];seen=set();total=None;started=time.monotonic()
        while total is None or len(rows)<total:
            if time.monotonic()-started>25:raise MediaError('Die Emby-Suche dauert zu lange. Bitte eingrenzen.')
            count=min(250,limit-len(rows)) if limit is not None else 250
            if count<=0:break
            result=self.client.get('Users/'+self.client.user_id+'/Items',{'Recursive':'true','Fields':FIELDS,'EnableUserData':'true','SortBy':'SortName','SortOrder':'Ascending',**params,'StartIndex':len(rows),'Limit':count})
            found=result.get('TotalRecordCount')
            if type(found) is not int or found<0 or found>20000 or (total is not None and total!=found):raise MediaError('Die Emby-Bibliothek wurde geändert oder ist zu groß.')
            total=found;batch=result.get('Items',[])
            if not batch and len(rows)<total:raise MediaError('Emby lieferte eine unvollständige Trefferliste.')
            for row in batch:
                media=self.media(row)
                if media.library_id in seen:raise MediaError('Doppelte Emby-Treffer. Bitte erneut suchen.')
                seen.add(media.library_id);rows.append(media)
            if len(rows)>total:raise MediaError('Ungültige Emby-Trefferanzahl.')
        return MediaPage(tuple(rows),total or 0)
    def search_media(self,query,kind='movie',limit=100):
        return self.items({'IncludeItemTypes':TYPES[kind],'SearchTerm':query},limit)
    def title_catalog(self,kind):
        return self.items({'IncludeItemTypes':TYPES[kind]}).items
    def metadata_catalog(self,kind='movie',series_id=None,filters=None):
        params={'IncludeItemTypes':TYPES[kind]}
        if series_id is not None:params['ParentId']=self.client.identifier(series_id)
        return self.items(params).items
    def detail(self,item_id,kind):
        row=self.client.get('Users/'+self.client.user_id+'/Items/'+self.client.identifier(item_id))
        media=self.media(row)
        if media.kind!=kind:raise MediaError('Der Emby-Eintrag hat einen anderen Medientyp.')
        return media
    def get_movie(self,item_id):return self.detail(item_id,'movie')
    def get_series(self,item_id):return self.detail(item_id,'series')
    def get_episode(self,item_id):return self.detail(item_id,'episode')
    def get_episodes(self,series_id,season=None):
        rows=self.metadata_catalog('episode',series_id)
        if season is not None:rows=tuple(r for r in rows if r.season==season)
        return MediaPage(tuple(sorted(rows,key=lambda r:(r.season,r.episode))),len(rows))
    def get_seasons(self,series_id):
        rows=self.get_episodes(series_id).items
        return tuple(Season(self.source_id,series_id,n,'Staffel '+str(n),sum(r.season==n for r in rows)) for n in sorted({r.season for r in rows if r.season>=0}))

class EmbyArtwork:
    def __init__(self,client):self.client=client
    def fetch(self,reference):
        prefix='emby-image:'+self.client.server_id+':'
        if not reference.startswith(prefix):return b''
        item_id=self.client.identifier(reference[len(prefix):])
        return self.client.get('Items/'+item_id+'/Images/Primary',{'MaxWidth':160,'Quality':80},binary=True)
