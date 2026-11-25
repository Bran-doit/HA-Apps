"""Deterministic German media commands; no LLM and no arbitrary selection."""
import re
import time
from dataclasses import replace
from .hmk_intelligent import parse_query, IntelligentSearch
from .hmk_models import MediaError, normalized
from .hmk_matching import title_key, exact_title

NUMBERS = {"null":0,"eins":1,"ein":1,"eine":1,"zwei":2,"drei":3,"vier":4,"fuenf":5,"fünf":5,"sechs":6,"sieben":7,"acht":8,"neun":9,"zehn":10,"elf":11,"zwoelf":12,"zwölf":12,"dreizehn":13,"vierzehn":14,"fuenfzehn":15,"fünfzehn":15,"sechzehn":16,"siebzehn":17,"achtzehn":18,"neunzehn":19,"zwanzig":20}
ROOMS = {"wohnzimmer", "familienzimmer", "fernseher", "kodi", "google tv"}

def number(value):
    value=normalized(value)
    if value.isdigit() and len(value)<=3:
        return int(value)
    if value in NUMBERS:
        return NUMBERS[value]
    raise MediaError("Bitte Staffel und Folge als Zahl angeben.")

def normalize_selection(text):
    """Canonicalize explicit media choices without relaxing the LMS keyword boundary."""
    text=text.strip().rstrip(".!?")
    prefix=r"(?:kodi\s+)?(?:nimm|spiel(?:e)?|starte|wähle|waehle)\s+(?:mir\s+)?(?:bitte\s+)?(?:den\s+|die\s+)?"
    ordinal=re.fullmatch(prefix+r"(\d+\.|erste[nr]?|zweite[nr]?|dritte[nr]?|vierte[nr]?|fünfte[nr]?|fuenfte[nr]?|sechste[nr]?|siebte[nr]?|achte[nr]?|neunte[nr]?|zehnte[nr]?)\s+(film|folge)(?:\s+bitte)?",text,re.I)
    if ordinal:
        word=ordinal[1].casefold()
        roots=('erst','zweit','dritt','viert','fünft','sechst','siebt','acht','neunt','zehnt')
        index=int(word[:-1]) if word.endswith('.') else next(i for i,root in enumerate(roots,1) if word.replace('fuenf','fünf').startswith(root))
        return 'Kodi nimm '+ordinal[2]+' Nummer '+str(index)
    numbered=re.fullmatch(prefix+r"(film|folge)\s+(?:nummer\s+)?(\d+|eins|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn)(?:\s+bitte)?",text,re.I)
    if numbered:return 'Kodi nimm '+numbered[1]+' Nummer '+numbered[2]
    year=re.fullmatch(prefix+r"film\s+(?:von|aus dem jahr)\s+(\d{4})(?:\s+bitte)?",text,re.I)
    if year:return 'Kodi nimm Film von '+year[1]
    return text

class VoiceController:
    def __init__(self, media, players, room_aliases=None, player_name="Fernseher"):
        self.media, self.players = media, players
        self.pending = {}
        self.rooms = {normalized(v) for v in (ROOMS if room_aliases is None else room_aliases)}
        self.player_name = player_name
        known = self.rooms | {"wohnzimmer", "familienzimmer", "fernseher", "kodi", "google tv", "schlafzimmer", "kinderzimmer"}
        self.room_pattern = r"\s+(?:im|auf dem|auf)\s+("+"|".join(re.escape(v) for v in sorted(known,key=len,reverse=True))+r")$"

    def answer(self, status, speech, handled=True, **extra):
        return {"handled": handled, "status": status, "speech": speech, "interpretation":getattr(self,"interpretation","Noch nicht vollständig erkannt"), **extra}

    def options(self, candidates, session, kind, season, episode, data=None):
        choices = list(candidates)[:10]
        self.pending = {k:v for k,v in self.pending.items() if time.monotonic()-v[0]<120}
        if session:
            if len(self.pending)>=100:
                self.pending.pop(next(iter(self.pending)))
            self.pending[session]=(time.monotonic(),choices,kind,season,episode,bool((data or {}).get("dry_run")))
        labels=[str(i+1)+": "+(m.show_title+" – " if m.kind=="episode" and m.show_title else "")+m.title+(" · Staffel "+str(m.season)+", Folge "+str(m.episode) if m.kind=="episode" else (" von "+str(m.year) if m.year else "")) for i,m in enumerate(choices[:4])]
        keyword = "Film" if kind == "movie" else "Folge"
        speech="Meinst du "+" oder ".join(labels)+"?"
        if len(choices)>4:
            speech+=" Weitere Treffer stehen im Dashboard."
        speech+=' Sage zum Bestätigen zum Beispiel: Kodi nimm '+keyword+' Nummer eins oder Kodi spiel '+('den ersten Film' if kind=='movie' else 'die erste Folge')+'.'
        if kind == "series":
            speech+=' Die Auswahl gilt für Staffel '+str(season)+', Folge '+str(episode)+'.'
        return self.answer("choose",speech,choices=[m.to_dict() for m in choices])

    def handle(self, data):
        self.interpretation="Noch nicht vollständig erkannt"
        text=data.get("text", "")
        if not isinstance(text,str) or not text.strip() or len(text)>300:
            return self.answer("error","Bitte einen kurzen Film- oder Serienbefehl angeben.")
        text=text.strip().rstrip(".!?")
        text=re.sub(r"^(kodi\s+)?findest\s+du\s+",lambda m:(m[1] or "")+"Finde ",text,flags=re.I)
        if re.match(r"^kodi\s+(?:pruefe|prüfe|teste)\s+", text, re.I):
            data = {**data, "dry_run": True}
            text = re.sub(r"^kodi\s+(?:pruefe|prüfe|teste)\s+", "Kodi spiel ", text, flags=re.I)
        text=normalize_selection(text)
        session=str(data.get("session", ""))[:200]
        explicit=bool(re.match(r"^kodi\b",text,re.I))
        # Require a standalone media keyword before any library lookup or playback.
        routed = bool(re.search(r"\b(?:filme?|staffel|folge|kinderfilme?|familienfilme?)\b", text, re.I))
        guidance = "Bitte sage Film, Staffel oder Folge, zum Beispiel: Spiel den Film Matrix."
        if not routed:
            return self.answer("error", guidance) if explicit else self.answer("unhandled", "", False)
        explicit = True
        try:
            selection=re.fullmatch(r"(?:kodi\s+)?(?:nimm|spiel(?:e)?|starte)\s+(?:(?:den|die)\s+)?(film|folge)\s+nummer\s+(\w+)",text,re.I)
            choice=re.fullmatch(r"kodi\s+(?:nimm\s+)?(?:den\s+)?film\s+(?:von|aus dem jahr)\s+(\d{4})",text,re.I)
            if choice or selection:
                self.interpretation=("Auswahl aus vorherigen Treffern: "+selection[1]+" Nummer "+selection[2]) if selection else "Filmauswahl nach Erscheinungsjahr: "+choice[1]
                pending=self.pending.get(session)
                if not pending or time.monotonic()-pending[0]>120:
                    self.pending.pop(session,None)
                    return self.answer("error","Es gibt keine aktuelle Auswahl. Nenne bitte den vollständigen Befehl erneut.")
                _, candidates,kind,season,episode,dry_run=pending
                if selection:
                    expected="film" if kind=="movie" else "folge"
                    if selection[1].casefold()!=expected:
                        return self.answer("error","Bitte bestätige die aktuelle Auswahl mit dem Codewort "+expected+".")
                    index=number(selection[2])-1
                    matches=candidates[index:index+1] if 0<=index<len(candidates) else []
                else:
                    matches=[m for m in candidates if m.year==int(choice[1])] if kind=="movie" else []
                if len(matches)!=1:
                    return self.answer("choose","Diese Auswahl ist nicht eindeutig oder ungültig. Nenne bitte eine angezeigte Nummer.",choices=[m.to_dict() for m in candidates])
                return self.finish(matches[0],kind,season,episode,{**data,"dry_run":dry_run or data.get("dry_run") is True},session)
            # A new search invalidates old choices, even when it finds nothing.
            self.pending.pop(session,None)
            text=re.sub(r"^kodi\s+", "", text, flags=re.I)
            semantic_text = text
            room_match = re.search(self.room_pattern, text, re.I)
            if room_match:
                if normalized(room_match[1]) not in self.rooms:
                    raise MediaError("Für diesen Raum ist noch kein Kodi-Player eingerichtet.")
                semantic_text=text[:room_match.start()].strip()
            intent = parse_query(semantic_text)
            if intent:
                parts=[{'movies':'Filmsuche nach Eigenschaften','next':'Nächste ungesehene Folge','latest':'Zuletzt hinzugefügte Folge','latest_season':'Zuletzt hinzugefügte Staffel','plot':'Folgensuche nach Inhalt'}[intent.mode]]
                parts.append('Aktion: nur suchen' if intent.search_only else 'Aktion: Auswahl anbieten' if intent.mode in ('movies','plot','latest_season') else 'Aktion: abspielen')
                if intent.series:parts.append('Serie: '+intent.series)
                if intent.topic:parts.append('Stichwort: '+intent.topic)
                if intent.genre:parts.append('Genre: '+intent.genre)
                if intent.actors:parts.append('Schauspieler: '+', '.join(intent.actors))
                if intent.year_from or intent.year_to<9999:parts.append('Jahr: '+str(intent.year_from)+'–'+str(intent.year_to))
                parts.append('Gesehen-Status: nur ungesehen' if intent.unseen else 'Gesehen-Status: beliebig')
                if intent.children:parts.append('Genre-Einschränkung: Familie oder Animation')
                if intent.age is not None:parts.append('FSK: bis '+str(intent.age))
                if intent.max_minutes is not None:parts.append('Laufzeit: maximal '+str(intent.max_minutes)+' Minuten')
                if intent.collection:parts.append('Filmreihe: '+intent.collection)
                if data.get('dry_run'):parts.append('Probelauf ohne Wiedergabe')
                self.interpretation=' · '.join(parts)
                rows, auto, explanation = IntelligentSearch(self.media).resolve(intent)
                if not rows:
                    return self.answer("not_found",explanation.rstrip(".")+". Keine passenden Einträge mit den erforderlichen Metadaten gefunden.")
                if auto:
                    result=self.finish(rows[0],rows[0].kind,None,None,data,session)
                else:
                    result=self.options(rows,session,rows[0].kind,None,None,data)
                    result["total"]=len(rows)
                    result["speech"]=explanation+". "+str(len(rows))+" Treffer. "+result["speech"]
                result["interpretation"]=self.interpretation
                if intent.mode=="movies" and data.get("show_on_kodi",True) and not data.get("dry_run") and hasattr(self,"show_results"):
                    try:
                        display=self.show_results(intent,rows)
                    except Exception:
                        display={"shown":False,"reason":"display_unavailable"}
                    result["tv_results"]=display
                    if display.get("shown"):
                        result["speech"]=str(len(rows))+" Treffer. Die Suchergebnisse sind in Kodi geöffnet."
                    else:
                        result["speech"]+=" Die passende Fernsehliste konnte nicht geöffnet werden; die Auswahl steht im Dashboard."
                return result
            if re.match(r"^(?:such(?:e)?|finde)\s+",text,re.I):
                data={**data,"search_only":True}
                text=re.sub(r"^(?:such(?:e)?|finde)\s+","Spiel ",text,flags=re.I)
            command=re.match(r"^(?:spiel(?:e)?|starte)\s+(?:mir\s+)?(?:bitte\s+)?(.+)$",text,re.I)
            if not command:
                command=re.match(r"^(?:gib|gebe)\s+(?:mir\s+)?(.+?)\s+wieder$",text,re.I)
            if not command:
                return self.answer("error", "Bitte sage zum Beispiel: Spiel den Film Matrix oder Spiel Folge 3 von Staffel 1 von Downton Abbey.")
            query=command[1].strip()
            # Explicit room suffix is removed before title/year matching.
            room=re.search(self.room_pattern,query,re.I)
            if room:
                explicit=True
                if normalized(room[1]) not in self.rooms:
                    return self.answer("error","Für diesen Raum ist noch kein Kodi-Player eingerichtet.")
                query=query[:room.start()].strip()
            film_command = bool(re.match(r"^(?:(?:den|die)\s+)?filme?\s+",query,re.I))
            if film_command:
                explicit=True
                query=re.sub(r"^(?:(?:den|die)\s+)?filme?\s+", "",query,flags=re.I)
            kind,season,episode="movie",None,None
            episode_match=re.fullmatch(r"(?:die\s+)?(?:folge|episode)\s+(\w+)\s+(?:(?:von|aus|in)\s+)?(?:der\s+)?staffel\s+(\w+)\s+(?:von\s+)?(.+)",query,re.I)
            season_match=re.fullmatch(r"(?:die\s+)?staffel\s+(\w+)[,\s]+(?:folge|episode)\s+(\w+)\s+(?:von\s+)?(.+)",query,re.I)
            if not film_command and (episode_match or season_match):
                explicit=True
                kind="series"
                if episode_match:
                    episode,season=number(episode_match[1]),number(episode_match[2])
                    query=episode_match[3]
                else:
                    season,episode=number(season_match[1]),number(season_match[2])
                    query=season_match[3]
                if episode<1:
                    raise MediaError("Die Folgennummer muss mindestens eins sein.")
            elif not film_command and re.match(r"^(?:die\s+)?(?:staffel|folge)\b", query, re.I):
                return self.answer("error", "Bitte nenne Serientitel, Staffel und Folge, zum Beispiel: Spiel Folge 3 von Staffel 1 von Downton Abbey.")
            year=None
            year_match=re.search(r"\s+(?:aus dem jahr|von)\s+(\d{4})$",query,re.I)
            if year_match:
                explicit=True
                year=int(year_match[1]);query=query[:year_match.start()].strip()
            parts=['Titelsuche: '+query,'Medientyp: '+('Film' if kind=='movie' else 'Serie'), 'Aktion: breit suchen' if data.get('search_only') else 'Aktion: eindeutigen Titel abspielen, sonst nachfragen']
            if year is not None:parts.append('Jahr: '+str(year))
            if season is not None:parts.append('Staffel: '+str(season))
            if episode is not None:parts.append('Folge: '+str(episode))
            if data.get('dry_run'):parts.append('Probelauf ohne Wiedergabe')
            self.interpretation=' · '.join(parts)
            # Partial titles never cause playback. They can only produce a question.
            page=self.media.search_voice(query,kind,year) if hasattr(self.media,"search_voice") else self.media.search_media(query,kind)
            if page.truncated:
                return self.answer("choose","Es gibt zu viele Treffer. Nenne bitte den vollständigen Titel und das Jahr.")
            if data.get("search_only") and hasattr(self.media,"search_titles"):
                page=self.media.search_titles(query,kind,year)
                if page.truncated:
                    return self.options(page.items,session,kind,season,episode,data)
            exact=[m for m in page.items if exact_title(m,query) and (year is None or m.year==year)]
            if len(exact)==1 and not data.get("search_only"):
                explicit=True
                return self.finish(exact[0],kind,season,episode,data,session)
            candidates=([m for m in page.items if year is None or m.year==year] if data.get("search_only") else exact or [m for m in page.items if year is None or m.year==year])
            if data.get("search_only") and len(candidates)==1:
                return self.finish(candidates[0],kind,season,episode,data,session)
            if candidates and (explicit or exact):
                return self.options(candidates,session,kind,season,episode,data)
            return self.answer("not_found", "Ich finde "+query+" nicht in der Medienbibliothek." if explicit else "", explicit)
        except MediaError as exc:
            return self.answer("error",str(exc),explicit or bool(data.get("force")))

    def finish(self, media, kind, season, episode, data, session):
        getter = getattr(self.media, {"movie":"get_movie","series":"get_series","episode":"get_episode"}[kind], None)
        if getter:
            current = getter(media.library_id, media.source)
            if title_key(current.title)!=title_key(media.title) or current.year!=media.year:
                raise MediaError("Der Bibliothekseintrag wurde geändert. Bitte suche erneut.")
            if media.require_unwatched and current.play_count!=0:
                raise MediaError("Der Gesehen-Status hat sich geändert. Bitte suche erneut.")
            media = replace(current, require_unwatched=media.require_unwatched, start_resume=media.start_resume and current.resume_seconds>0)
        if kind=="series":
            page=self.media.get_episodes(media.library_id,season,media.source)
            if page.truncated:
                return self.answer("error","Die Episodenliste ist unvollständig. Wähle die Folge bitte im Dashboard.")
            matches=[m for m in page.items if m.season==season and m.episode==episode]
            if len(matches)!=1:
                return self.answer("error", "Diese Folge fehlt oder ist nicht eindeutig. Wähle sie bitte im Dashboard.")
            media=matches[0]
        description=media.title
        if media.kind=="episode":
            description+=" – Staffel "+str(media.season)+", Folge "+str(media.episode)
        elif media.year:
            description+=" von "+str(media.year)
        if media.start_resume:
            description+=" – Fortsetzen ab Minute "+str(int(media.resume_seconds//60))
        if data.get("dry_run") is True or data.get("search_only"):
            return self.answer("ready", "Gefunden: "+description+(". Test ohne Wiedergabe." if data.get("dry_run") is True else "."),selected=media.to_dict())
        if time.time()>float(data.get("expires_at",time.time()+60)):
            return self.answer("error","Der Sprachauftrag ist abgelaufen. Bitte wiederhole ihn.")
        result=self.players.play(media,replace_current=data.get("replace_current",True) is True)
        if not result["verified"]:
            return self.answer("error","Der Start wurde gesendet, aber das Zielgerät bestätigt noch keine laufende Wiedergabe.",playback=result)
        self.pending.pop(session,None)
        return self.answer("playing", "Wiedergabe auf "+self.player_name+": "+description+".",selected=media.to_dict(),playback=result)
