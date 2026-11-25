"""Kodi source and player adapters for HA-Mediensteuerung auf Kodi."""
import base64
import json
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass


if __package__:
    from .hmk_models import Media, MediaError, normalized, resolve_unique
else:
    from hmk_models import Media, MediaError, normalized, resolve_unique


class KodiClient:
    def __init__(self, config):
        self.source_id = "kodi:" + config["host"] + ":" + str(config.get("port", 8080))
        self.url = ("https" if config.get("ssl") else "http") + "://" + config["host"] + ":" + str(config.get("port", 8080)) + "/jsonrpc"
        credentials = config.get("username", "") + ":" + config.get("password", "")
        self.auth = "Basic " + base64.b64encode(credentials.encode()).decode()
        self.timeout = 10
        self.timings = []
        self.sequence = 0
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def rpc(self, method, params=None):
        self.sequence += 1
        request_id = self.sequence
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Authorization": self.auth})
        started = time.monotonic()
        ok = False
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                result = json.load(response)
            if result.get("id") != request_id or result.get("jsonrpc") != "2.0":
                raise MediaError("Ungueltige JSON-RPC-Antwort")
            if "error" in result:
                raise MediaError("Kodi JSON-RPC %s: %s" % (method, result["error"].get("code")))
            if "result" not in result:
                raise MediaError("JSON-RPC-Ergebnis fehlt")
            ok = True
            return result["result"]
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise MediaError("Kodi nicht erreichbar oder Antwort ungueltig (%s)" % type(exc).__name__) from None
        finally:
            self.timings.append({"method": method, "ms": round((time.monotonic()-started)*1000, 1), "ok": ok})
            self.timings = self.timings[-200:]


class KodiSource:
    def __init__(self, client):
        self.client = client

    def media(self, row, kind):
        key = {"movie": "movieid", "series": "tvshowid", "episode": "episodeid"}[kind]
        return Media(self.client.source_id, kind, row[key], row.get("title", row.get("label", "")), row.get("year", 0), row.get("art", {}).get("poster", row.get("thumbnail", "")), row.get("file", ""), row.get("season", -1), row.get("episode", -1), tuple(t for t in (row.get("originaltitle"),) if isinstance(t, str) and t.strip()),
            provider_ids={str(k).casefold():str(v) for k,v in (row.get("uniqueid") or {}).items() if v}, genres=tuple(row.get("genre", [])), actors=tuple(c["name"] for c in row.get("cast", []) if c.get("name")),
            plot=row.get("plot", ""), collection=row.get("set", ""), runtime=row.get("runtime", 0),
            certification=row.get("mpaa", ""), play_count=row.get("playcount"),
            resume_seconds=row.get("resume", {}).get("position", 0), date_added=row.get("dateadded", ""), first_aired=row.get("firstaired", ""), show_title=row.get("showtitle", ""))

    def listing(self, kind, query=None, limit=20):
        if kind not in ("movie", "series"):
            raise MediaError("Medientyp muss movie oder series sein")
        method, key = ("VideoLibrary.GetMovies", "movies") if kind == "movie" else ("VideoLibrary.GetTVShows", "tvshows")
        params = {"properties": ["title", "year", "thumbnail", "file", "art"], "limits": {"start": 0, "end": limit}, "sort": {"method": "title", "order": "ascending"}}
        if query is not None:
            if not isinstance(query, str) or not query.strip() or len(query) > 200:
                raise MediaError("Suchtext muss 1 bis 200 Zeichen enthalten")
            params["filter"] = {"field": "title", "operator": "contains", "value": query.strip()}
        result = self.client.rpc(method, params)
        return {"total": result["limits"]["total"], "items": [self.media(row, kind).to_dict() for row in result.get(key, [])]}

    def search_media(self, query, kind="movie"):
        return self.listing(kind, query, 100)

    def get_movie(self, media_id):
        result = self.client.rpc("VideoLibrary.GetMovieDetails", {"movieid": self.valid_id(media_id), "properties": ["title", "year", "thumbnail", "file", "art", "playcount", "resume"]})
        return self.media(result["moviedetails"], "movie")

    def get_episode(self, media_id):
        result = self.client.rpc("VideoLibrary.GetEpisodeDetails", {"episodeid": self.valid_id(media_id), "properties": ["title", "season", "episode", "thumbnail", "file", "playcount", "resume", "showtitle"]})
        return self.media(result["episodedetails"], "episode")

    @staticmethod
    def valid_id(value):
        if type(value) is not int or value < 1:
            raise MediaError("Bibliotheks-ID muss eine positive Ganzzahl sein")
        return value

    def get_seasons(self, series_id):
        return self.client.rpc("VideoLibrary.GetSeasons", {"tvshowid": self.valid_id(series_id), "properties": ["season", "showtitle", "episode"]})

    def get_episodes(self, series_id, season=None):
        params = {"tvshowid": self.valid_id(series_id), "properties": ["title", "season", "episode", "file", "thumbnail", "art"], "limits": {"start": 0, "end": 100}, "sort": {"method": "episode", "order": "ascending"}}
        if season is not None:
            if type(season) is not int or season < 0:
                raise MediaError("Staffel muss eine nichtnegative Ganzzahl sein")
            params["season"] = season
        return self.client.rpc("VideoLibrary.GetEpisodes", params)


class KodiPlayer:
    def __init__(self, client):
        self.client = client

    def play(self, media):
        if media.source != self.client.source_id:
            raise MediaError("Kodi-IDs duerfen nicht auf andere Bibliotheken uebertragen werden")
        if media.kind not in ("movie", "episode"):
            raise MediaError("Bitte einen Film oder eine konkrete Episode auswaehlen")
        key = "movieid" if media.kind == "movie" else "episodeid"
        params = {"item": {key: KodiSource.valid_id(media.library_id)}}
        if media.start_resume:
            params["options"] = {"resume": True}
        return self.client.rpc("Player.Open", params)

    def get_now_playing(self):
        result = []
        for player in self.client.rpc("Player.GetActivePlayers"):
            if player["type"] != "video":
                continue
            pid = player["playerid"]
            item = self.client.rpc("Player.GetItem", {"playerid": pid, "properties": ["title", "file"]})["item"]
            properties = self.client.rpc("Player.GetProperties", {"playerid": pid, "properties": ["speed", "time", "totaltime"]})
            result.append({"playerid": pid, "item": item, **properties})
        return result

    @staticmethod
    def seconds(value):
        return value.get("hours", 0)*3600 + value.get("minutes", 0)*60 + value.get("seconds", 0) + value.get("milliseconds", 0)/1000

    def verify(self, media, timeout=25):
        started = time.monotonic()
        previous = None
        samples = []
        while time.monotonic()-started < timeout:
            time.sleep(2)
            current = self.get_now_playing()
            samples.append(current)
            for state in current:
                if state["item"].get("id") == media.library_id and state["item"].get("type") == media.kind and state["speed"] > 0:
                    seconds = self.seconds(state["time"])
                    if previous is not None and seconds > previous:
                        return {"verified": True, "verification_ms": round((time.monotonic()-started)*1000, 1), "samples": samples}
                    previous = seconds
        return {"verified": False, "verification_ms": round((time.monotonic()-started)*1000, 1), "samples": samples}
