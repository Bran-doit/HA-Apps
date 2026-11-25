"""Resolve central Emby identities to the selected Kodi library; never reuse IDs."""
import re
import time
from dataclasses import replace
from urllib.parse import urlsplit
from .hmk_models import MediaError


def identities(row, kind):
    ids={str(k).casefold():str(v) for k,v in (row.get('uniqueid') or {}).items() if v and str(k).casefold() in ('imdb','tmdb','tvdb')}
    if re.fullmatch(r'tt\d+',row.get('imdbnumber','') or ''):ids.setdefault('imdb',row['imdbnumber'])
    try:
        url=urlsplit(row.get('file','').split('|',1)[0])
        path=url.path
        local=url.hostname in ('127.0.0.1','localhost') and url.port==57342
        if local or path.startswith('/emby_addon_mode/'):
            match=re.search(r'/(movies|tvshows)/([a-zA-Z0-9_-]+)/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+/([a-zA-Z0-9_-]+)/',path)
            if match and ((kind=='movie' and match[1]=='movies') or (kind=='episode' and match[1]=='tvshows')):
                ids['emby:'+match[2]]=match[3]
    except ValueError:pass
    return ids


def same_identity(original, candidate):
    if original.kind!=candidate.kind:return False
    left,right=original.provider_ids,candidate.provider_ids
    emby_keys=[k for k in left if k.startswith('emby:')]
    for key in emby_keys:
        if key in right:return left[key]==right[key]
    if emby_keys and any(k.startswith('emby:') for k in right):return False
    common=set(left)&set(right)&{'imdb','tmdb','tvdb'}
    return bool(common) and all(left[k]==right[k] for k in common)


class EmbyKodiResolver:
    def __init__(self, source, target):
        self.source=source
        self.target=target
    def decode(self,row,kind):
        return replace(self.target.library.media(row,kind),provider_ids=identities(row,kind))
    def catalog(self,kind):
        method,key=('VideoLibrary.GetMovies','movies') if kind=='movie' else ('VideoLibrary.GetEpisodes','episodes')
        rows=[];seen=set();total=None;started=time.monotonic()
        while total is None or len(rows)<total:
            if time.monotonic()-started>20:raise MediaError('Die Zuordnung zum Ziel-Kodi dauert zu lange.')
            props=['title','file','uniqueid','year'] if kind=='movie' else ['title','file','uniqueid','season','episode','showtitle']
            r=self.target.client.rpc(method,{'properties':props,'limits':{'start':len(rows),'end':len(rows)+500},'sort':{'method':'title','order':'ascending'}})
            count=r['limits']['total'];batch=r.get(key,[])
            if type(count) is not int or count<0 or count>20000 or (total is not None and count!=total) or (not batch and len(rows)<count):raise MediaError('Die Zielbibliothek ist unvollständig oder wurde geändert.')
            total=count
            for row in batch:
                m=self.decode(row,kind)
                if m.library_id in seen:raise MediaError('Doppelte Einträge in der Zielbibliothek.')
                seen.add(m.library_id);rows.append(m)
            if len(rows)>total:raise MediaError('Ungültige Zielbibliothek.')
        return rows
    def __call__(self,media):
        if media.source!=self.source.source_id:raise MediaError('Die Medienquelle passt nicht zur Zuordnung.')
        getter=self.source.get_movie if media.kind=='movie' else self.source.get_episode
        current=getter(media.library_id)
        if not same_identity(media,current):raise MediaError('Der Emby-Eintrag wurde geändert. Bitte erneut suchen.')
        if media.require_unwatched and current.play_count!=0:raise MediaError('Der Emby-Gesehen-Status hat sich geändert. Bitte erneut suchen.')
        candidates=[m for m in self.catalog(media.kind) if same_identity(current,m)]
        if len(candidates)!=1:raise MediaError('Der Emby-Treffer fehlt auf dem Ziel-Kodi oder ist dort mehrfach vorhanden. Bitte die Emby-Synchronisierung prüfen.')
        chosen=candidates[0]
        method,key,idkey=('VideoLibrary.GetMovieDetails','moviedetails','movieid') if media.kind=='movie' else ('VideoLibrary.GetEpisodeDetails','episodedetails','episodeid')
        props=['title','file','uniqueid','playcount','resume']+(['year'] if media.kind=='movie' else ['season','episode','showtitle'])
        fresh=self.decode(self.target.client.rpc(method,{idkey:chosen.library_id,'properties':props})[key],media.kind)
        if not same_identity(current,fresh):raise MediaError('Der Kodi-Eintrag wurde geändert. Bitte erneut suchen.')
        if media.start_resume and abs(current.resume_seconds-fresh.resume_seconds)>5:
            raise MediaError('Emby und Kodi haben unterschiedliche Fortsetzungspunkte. Bitte dasselbe Emby-Profil synchronisieren.')
        return replace(fresh,start_resume=media.start_resume,require_unwatched=False)
