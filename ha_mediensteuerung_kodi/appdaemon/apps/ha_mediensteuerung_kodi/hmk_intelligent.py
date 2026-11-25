"""Library-grounded German metadata queries; no invented facts or external LLM."""
import re
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from .hmk_models import MediaError
from .hmk_matching import folded, exact_title, title_key

GENRES = {
    'science fiction': ('science fiction','sci fi'), 'sci fi': ('science fiction','sci fi'),
    'komödie': ('komoedie','comedy'), 'komoedie': ('komoedie','comedy'),
    'thriller': ('thriller',), 'action': ('action',), 'drama': ('drama',),
    'animation': ('animation',), 'fantasy': ('fantasy',), 'horror': ('horror',),
    'abenteuer': ('abenteuer','adventure'), 'western': ('western',),
    'familien': ('familienfilm','family'),
}
DECADES = {'fünfzigern':1950,'fuenfzigern':1950,'sechzigern':1960,'siebzigern':1970,'achtzigern':1980,'neunzigern':1990,'zweitausendern':2000,'zweitausendzehnern':2010}

@dataclass(frozen=True)
class Query:
    mode: str
    series: str = ''
    topic: str = ''
    actors: tuple = ()
    genre: str = ''
    year_from: int = 0
    year_to: int = 9999
    unseen: bool = False
    children: bool = False
    age: int | None = None
    max_minutes: int | None = None
    collection: str = ''
    search_only: bool = False


def parse_query(text):
    text=text.casefold().strip().rstrip('.!?')
    command=re.match(r'^(spiel(?:e)?|starte|such(?:e)?|finde)\s+(?:mir\s+)?(?:bitte\s+)?(.+)$',text)
    if not command:return None
    body=command[2].strip();search_only=command[1] in ('such','suche','finde')
    body=re.sub(r'^(?:(?:die|alle)\s+)?(filme|kinderfilme|familienfilme)\b',lambda m:m[1][:-1],body)
    latest=re.fullmatch(r'(?:die\s+)?(?:neueste|neuste|zuletzt\s+(?:hinzugefügte|hinzugefuegte))\s+(folge|staffel)\s+(?:von|aus)\s+(?:der\s+serie\s+)?(.+)',body)
    if latest:return Query('latest_season' if latest[1]=='staffel' else 'latest',series=latest[2],search_only=search_only)
    nxt=re.fullmatch(r'(?:die\s+)?n(?:ä|ae)chste(?:\s+(?:(?:noch\s+)?nicht\s+gesehene|ungesehene))?\s+folge\s+(?:von|aus)\s+(.+)',body)
    if nxt:return Query('next',series=nxt[1],unseen=True,search_only=search_only)
    plot=re.fullmatch(r'(?:die\s+)?folge\s+von\s+(.+?)\s+(?:mit|über|ueber)\s+(.+)',body)
    if plot:return Query('plot',series=plot[1],topic=plot[2],search_only=search_only)
    # Leave simple concrete title commands to the existing title parser.
    if not (re.match(r'^(?:einen?|(?:den\s+)?(?:ungesehenen|noch nicht gesehenen))\b',body) or
            re.match(r'^(?:den\s+)?(?:kinderfilm|familienfilm|film\s+(?:mit|aus|für|fuer|unter|bis|ab|ungesehen))\b',body) or
            re.search(r'\b(?:den|einen)\s+.+?[- ]filme?\b',body)):
        return None
    q=Query('movies',search_only=search_only)
    work=re.sub(r'\bfilme\b','film',body.replace('-',' '))
    if re.search(r'\b(?:kinderfilm|familienfilm)\b',work):
        work=re.sub(r'\b(?:kinderfilm|familienfilm)\b','film für kinder',work)
    if re.search(r'\bjames bond film\b',work):
        q=replace(q,collection='james bond');work=work.replace('james bond film','film')
    unseen=r'(?:,?\s*den\s+(?:wir|ich)\s+(?:noch\s+)?nicht\s+gesehen\s+(?:haben|habe)|\b(?:noch\s+)?nicht\s+gesehene[nr]?\b|\bungesehene[nr]?\b|\bungesehen\b)'
    if re.search(unseen,work):q=replace(q,unseen=True);work=re.sub(unseen,' ',work)
    decade=re.search(r'\baus\s+den\s+(\w+)(?:\s+jahren)?\b',work)
    if decade:
        value=decade[1];year=DECADES.get(value)
        if year is None and re.fullmatch(r'\d{4}ern?',value):year=int(value[:4])
        if year is None and re.fullmatch(r'\d{2}ern?',value):year=1900+int(value[:2])
        if year is None or year%10:raise MediaError('Bitte nenne ein Jahrzehnt, zum Beispiel aus den Achtzigern.')
        q=replace(q,year_from=year,year_to=year+9);work=work[:decade.start()]+' '+work[decade.end():]
    yr=re.search(r'\baus\s+dem\s+jahr\s+(\d{4})\b',work)
    if yr:q=replace(q,year_from=int(yr[1]),year_to=int(yr[1]));work=work[:yr.start()]+' '+work[yr.end():]
    age=re.search(r'\b(?:für|fuer)\s+kinder(?:\s+ab\s+(\d+)\s+jahren)?\b',work)
    if age:
        number=int(age[1]) if age[1] else 6
        if number>18:raise MediaError('Bitte ein Kinderalter bis 18 angeben.')
        q=replace(q,children=True,age=number);work=work[:age.start()]+' '+work[age.end():]
    rating=re.search(r'\b(?:bis\s+)?fsk\s+(0|6|12|16|18)\b',work)
    if rating:q=replace(q,age=int(rating[1]));work=work[:rating.start()]+' '+work[rating.end():]
    duration=re.search(r'\b(?:unter|maximal|höchstens|hoechstens)\s+(\d+)\s+minuten\b',work)
    if duration:
        minutes=int(duration[1])
        if not 1<=minutes<=600:raise MediaError('Bitte eine Laufzeit zwischen 1 und 600 Minuten angeben.')
        q=replace(q,max_minutes=minutes);work=work[:duration.start()]+' '+work[duration.end():]
    actor=re.search(r'\bmit\s+(.+)$',work)
    if actor:
        names=tuple(n.strip(' ,') for n in re.split(r'\s+und\s+',actor[1]))
        if not all(names):raise MediaError('Bitte nenne den Schauspieler vollständig.')
        q=replace(q,actors=names);work=work[:actor.start()]
    work=' '.join(work.split()).strip(' ,')
    work=re.sub(r'^(?:einen?|den)\s+','',work)
    prefix=re.fullmatch(r'(.+?)\s+film',work)
    if prefix:
        if prefix[1] not in GENRES:raise MediaError('Dieses Filmgenre erkenne ich noch nicht. Nenne zum Beispiel Science Fiction oder Thriller.')
        q=replace(q,genre=prefix[1]);work='film'
    suffix=re.fullmatch(r'film\s+(?:im\s+genre|vom\s+genre|genre)\s+(.+)',work)
    if suffix:
        if suffix[1] not in GENRES:raise MediaError('Dieses Genre erkenne ich noch nicht.')
        q=replace(q,genre=suffix[1]);work='film'
    if work!='film':raise MediaError('Diese Filterkombination verstehe ich noch nicht vollständig. Nenne zum Beispiel einen ungesehenen Film mit Harrison Ford.')
    if q==Query('movies',search_only=search_only):raise MediaError('Bitte grenze die Filmsuche nach Schauspieler, Genre, Jahr oder gesehen/ungesehen ein.')
    return q


def movie_matches(media,q):
    if q.unseen and media.play_count!=0:return False
    if not q.year_from<=media.year<=q.year_to:return False
    if q.year_from and not media.year:return False
    if q.genre and not any(folded(g) in GENRES[q.genre] for g in media.genres):return False
    if q.actors and not all(any(folded(a)==folded(name) for a in media.actors) for name in q.actors):return False
    if q.collection and folded(q.collection) not in folded(media.collection+' '+media.title):return False
    if q.children and not any(folded(g) in ('familienfilm','family','animation') for g in media.genres):return False
    if q.age is not None:
        match=re.fullmatch(r'FSK\s*(0|6|12|16|18)',media.certification.strip(),re.I)
        if not match or int(match[1])>q.age:return False
    if q.max_minutes is not None and not 0<media.runtime<=q.max_minutes*60:return False
    return True


class IntelligentSearch:
    def __init__(self,media):self.media=media
    def resolve(self,q):
        if q.mode=='movies':
            rows=[replace(m,require_unwatched=q.unseen) for m in self.media.metadata_catalog('movie',filters={'actors':q.actors,'unseen':q.unseen,'year_from':q.year_from,'year_to':q.year_to,'children':q.children,'fields':(["cast"] if q.actors else [])+(["genre"] if q.genre or q.children else [])+(["mpaa"] if q.age is not None else [])+(["runtime"] if q.max_minutes else [])+(["set"] if q.collection else [])}) if movie_matches(m,q)]
            rows.sort(key=lambda m:(title_key(m.title),m.year,str(m.library_id)))
            explanation='Metadatensuche'
            if q.unseen:explanation+='; ungesehen laut aktuellem Kodi-Profil'
            if q.children:explanation+='; Familie/Animation mit FSK bis '+str(q.age)
            return rows,False,explanation
        page=self.media.search_voice(q.series,'series')
        exact=[m for m in page.items if exact_title(m,q.series)]
        if len(exact)>1 and not page.truncated:
            # Only merge identities proved by providers; a shared title is insufficient.
            details=[self.media.get_series(m.library_id) for m in exact]
            identities=[{k:v for k,v in m.provider_ids.items() if k in ('imdb','tmdb','tvdb')} for m in details]
            common=set.intersection(*(set(ids) for ids in identities))
            all_keys=set.union(*(set(ids) for ids in identities))
            same=bool(common) and all(len({ids[k] for ids in identities if k in ids})==1 for k in all_keys)
            if same:
                combined={}
                for show in exact:
                    for episode in self.media.metadata_catalog('episode',show.library_id):
                        combined[(episode.source,episode.library_id)]=episode
                merged_rows=list(combined.values())
                exact=exact[:1]
            else:merged_rows=None
        else:merged_rows=None
        if q.mode in ('next','latest','latest_season'):
            if page.truncated or len(exact)!=1:
                names=', '.join(m.title+(' ('+str(m.year)+')' if m.year else '') for m in page.items[:4])
                raise MediaError('Bitte nenne die Serie eindeutig.'+(' Gefunden: '+names if names else ' Kein passender Serientitel gefunden.'))
            rows=merged_rows if merged_rows is not None else self.media.metadata_catalog('episode',exact[0].library_id)
            regular=[m for m in rows if m.season>0 and m.episode>0 and (not m.first_aired or m.first_aired<=date.today().isoformat())]
            if q.mode in ('latest','latest_season'):
                regular=[m for m in rows if m.season>0 and m.episode>0]
                if not regular:return [],False,'Keine verfügbare reguläre Folge gefunden.'
                def added(m):
                    try:
                        value=datetime.fromisoformat(m.date_added.replace('Z','+00:00'))
                        if value.year<1900:return None
                        return value.replace(tzinfo=timezone.utc).timestamp() if value.tzinfo is None else value.timestamp()
                    except (ValueError,TypeError):return None
                dates=[(m,added(m)) for m in regular]
                if any(d is None for _,d in dates):
                    raise MediaError('Das Hinzufügedatum der Folgen fehlt oder ist unvollständig. Die zuletzt hinzugefügte Folge oder Staffel lässt sich nicht zuverlässig bestimmen.')
                newest=max(d for _,d in dates)
                matches=[m for m,d in dates if d==newest]
                if q.mode=='latest_season':
                    seasons={m.season for m in matches}
                    matches=[m for m in regular if m.season in seasons]
                matches.sort(key=lambda m:(m.season,m.episode,str(m.library_id)))
                if merged_rows is not None:
                    # Kodi may duplicate episodes too. Collapse only the same actual file.
                    unique=[];files=set()
                    for item in matches:
                        detail=self.media.get_episode(item.library_id)
                        file_key=detail.file
                        # Emby-for-Kodi embeds local database IDs in otherwise identical URLs.
                        if file_key.startswith('http://127.0.0.1:57342/tvshows/'):
                            file_key=re.sub(r'/e-\d+-\d+--(?=[0-9A-Fa-f]+/)', '/e--',file_key)
                        key=(item.source,file_key,item.season,item.episode)
                        if not detail.file or key not in files:unique.append(item)
                        if detail.file:files.add(key)
                    matches=unique
                return matches,not q.search_only and q.mode=='latest' and len(matches)==1,('Folgen der zuletzt hinzugefügten Staffel (nach jüngstem Hinzufügedatum ihrer Folgen)' if q.mode=='latest_season' else 'Zuletzt zur Bibliothek hinzugefügte Folge')
            if any(m.play_count is None for m in regular):raise MediaError('Der Gesehen-Status dieser Serie ist unvollständig.')
            pending=sorted((m for m in regular if m.play_count==0),key=lambda m:(m.season,m.episode))
            if not pending:return [],False,'Alle verfügbaren regulären Folgen sind als gesehen markiert.'
            first=pending[0]
            if sum(m.season==first.season and m.episode==first.episode for m in pending)>1:
                raise MediaError('Die nächste Folge ist mehrfach vorhanden. Bitte im Dashboard auswählen.')
            return [replace(first,require_unwatched=True,start_resume=first.resume_seconds>0)],not q.search_only,'Nächste ungesehene Folge laut aktuellem Kodi-Profil'
        # Content search remains tied to actual titles and synopses, never outside lore.
        shows=exact or [m for m in page.items if folded(q.series) in folded(m.title)]
        if page.truncated or len(shows)>10:raise MediaError('Bitte die Serie für die Inhaltssuche genauer eingrenzen.')
        stop={'der','die','das','den','dem','ein','eine','einem','einen','mit','von','und','über','ueber'}
        tokens=[t for t in folded(q.topic).split() if t not in stop and len(t)>=3]
        if not tokens:raise MediaError('Bitte nenne ein konkretes Stichwort für den Episodeninhalt.')
        rows=[]
        started=time.monotonic()
        for show in shows:
            if time.monotonic()-started>25:raise MediaError('Bitte die Serie für die Inhaltssuche genauer eingrenzen.')
            for m in (merged_rows if merged_rows is not None else self.media.metadata_catalog('episode',show.library_id)):
                hay=folded(m.title+' '+m.plot)
                if all(re.search(r'\b'+re.escape(t)+r'\w*\b',hay) for t in tokens):rows.append(m)
        rows.sort(key=lambda m:(m.show_title,m.season,m.episode))
        return rows,False,'Stichworttreffer in Episodentitel oder Inhaltsangabe'