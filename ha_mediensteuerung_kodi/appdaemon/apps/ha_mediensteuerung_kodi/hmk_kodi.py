"""Adapters translating Kodi-specific responses into the common media API."""
import time
import threading
import urllib.parse
import urllib.request
from .hmk_adapter import KodiSource, KodiPlayer
from .hmk_models import MediaPage, Season, Playing, MediaError

class KodiMediaSource:
    def __init__(self, client):
        self.client = client
        self.source_id = client.source_id
        self.library = KodiSource(client)
        self._catalog = {}
        self._catalog_lock = threading.Lock()

    def search_media(self, query, kind="movie", limit=100):
        result = self.library.listing(kind, query, limit)
        from .hmk_models import Media
        return MediaPage(tuple(Media(**row) for row in result["items"]), result["total"])

    def title_catalog(self, kind):
        """Bounded, paginated snapshot, cached for five minutes; never a partial index."""
        if kind not in ("movie", "series"):
            raise MediaError("Unbekannter Medientyp für die Sprachsuche.")
        with self._catalog_lock:
            cached = self._catalog.get(kind)
            if cached and time.monotonic() - cached[0] < 300:
                return cached[1]
            method, key = ("VideoLibrary.GetMovies", "movies") if kind == "movie" else ("VideoLibrary.GetTVShows", "tvshows")
            rows, seen, total = [], set(), None
            started = time.monotonic()
            while total is None or len(rows) < total:
                if time.monotonic() - started > 20:
                    raise MediaError("Der Titelindex braucht zu lange. Bitte versuche es erneut.")
                start = len(rows)
                result = self.client.rpc(method, {
                    "properties": ["title", "originaltitle", "year", "thumbnail"],
                    "limits": {"start": start, "end": start + 500},
                    "sort": {"method": "title", "order": "ascending"},
                })
                count = result["limits"]["total"]
                if type(count) is not int or count < 0 or count > 20000 or (total is not None and count != total):
                    raise MediaError("Die Bibliothek ist zu groß oder wurde geändert. Bitte erneut suchen.")
                total = count
                batch = result.get(key, [])
                if not batch and start < total:
                    raise MediaError("Der Titelindex ist unvollständig. Bitte erneut suchen.")
                for row in batch:
                    item = self.library.media(row, kind)
                    if item.library_id in seen:
                        raise MediaError("Die Bibliothek wurde während der Suche geändert. Bitte erneut suchen.")
                    seen.add(item.library_id)
                    rows.append(item)
                if len(rows) > total:
                    raise MediaError("Ungültige Größe des Titelindex.")
            items = tuple(rows)
            self._catalog[kind] = (time.monotonic(), items)
            return items

    def metadata_catalog(self, kind="movie", series_id=None, filters=None):
        # Watch state is fetched fresh for every interpretive query.
        if kind == "movie":
            method, key = "VideoLibrary.GetMovies", "movies"
            properties = ["title", "originaltitle", "year", "thumbnail", "genre", "cast", "plot", "set", "runtime", "mpaa", "playcount", "resume"]
        elif kind == "episode":
            method, key = "VideoLibrary.GetEpisodes", "episodes"
            properties = ["title", "season", "episode", "thumbnail", "plot", "playcount", "resume", "firstaired", "showtitle", "dateadded"]
        else:
            raise MediaError("Unbekannter Metadatentyp.")
        if kind == "movie" and filters and "fields" in filters:
            allowed = {"genre", "cast", "plot", "set", "runtime", "mpaa"}
            properties = ["title", "originaltitle", "year", "thumbnail", "playcount", "resume"] + sorted(set(filters["fields"]) & allowed)
        rows, seen, total = [], set(), None
        started = time.monotonic()
        while total is None or len(rows) < total:
            if time.monotonic()-started > 25:
                raise MediaError("Die Metadatensuche dauert zu lange. Bitte erneut versuchen.")
            params = {"properties": properties, "limits": {"start": len(rows), "end": len(rows)+500}, "sort": {"method":"title","order":"ascending"}}
            if kind == "movie" and filters:
                clauses = []
                for actor in filters.get("actors", ()):
                    clauses.append({"field":"actor","operator":"contains","value":actor})
                if filters.get("unseen"):
                    clauses.append({"field":"playcount","operator":"is","value":"0"})
                if filters.get("year_from"):
                    clauses.append({"field":"year","operator":"greaterthan","value":str(filters["year_from"]-1)})
                if filters.get("year_to",9999)<9999:
                    clauses.append({"field":"year","operator":"lessthan","value":str(filters["year_to"]+1)})
                if filters.get("children"):
                    clauses.append({"or":[{"field":"genre","operator":"contains","value":value} for value in ("Famil", "Animation")]})
                if clauses:
                    params["filter"] = {"and":clauses} if len(clauses)>1 else clauses[0]
            if series_id is not None:
                params["tvshowid"] = self.library.valid_id(series_id)
            result = self.client.rpc(method, params)
            count = result["limits"]["total"]
            if type(count) is not int or count<0 or count>20000 or (total is not None and total!=count):
                raise MediaError("Die Bibliothek wurde geändert oder ist zu groß. Bitte erneut suchen.")
            total = count
            batch = result.get(key, [])
            if not batch and len(rows)<total:
                raise MediaError("Die Metadatenliste ist unvollständig.")
            for row in batch:
                media = self.library.media(row, kind)
                if media.library_id in seen:
                    raise MediaError("Doppelte Einträge in der Metadatenliste. Bitte erneut suchen.")
                seen.add(media.library_id); rows.append(media)
            if len(rows)>total:
                raise MediaError("Ungültige Metadatenliste.")
        return tuple(rows)

    def get_movie(self, media_id):
        return self.library.get_movie(media_id)

    def get_series(self, media_id):
        result = self.client.rpc("VideoLibrary.GetTVShowDetails", {"tvshowid": self.library.valid_id(media_id), "properties": ["title", "year", "thumbnail", "file", "art", "uniqueid"]})
        return self.library.media(result["tvshowdetails"], "series")

    def get_episode(self, media_id):
        return self.library.get_episode(media_id)

    def get_seasons(self, series_id):
        result = self.library.get_seasons(series_id)
        return tuple(Season(self.source_id, series_id, row["season"], "Staffel " + str(row["season"]), row.get("episode", 0)) for row in result.get("seasons", []))

    def get_episodes(self, series_id, season=None):
        result = self.library.get_episodes(series_id, season)
        return MediaPage(tuple(self.library.media(row, "episode") for row in result.get("episodes", [])), result["limits"]["total"])

class KodiMediaPlayer:
    def __init__(self, client):
        self.client = client
        self.adapter = KodiPlayer(client)

    def can_play(self, media):
        return media.source == self.client.source_id and media.kind in ("movie", "episode") and type(media.library_id) is int and media.library_id > 0

    def play(self, media):
        return self.adapter.play(media)

    def get_now_playing(self):
        return tuple(Playing(p["item"].get("title", p["item"].get("label", "")), p["item"].get("type", "unknown"), p["item"].get("id"), p["speed"], self.adapter.seconds(p["time"]), self.adapter.seconds(p["totaltime"])) for p in self.adapter.get_now_playing())

    def verify(self, media):
        return self.adapter.verify(media)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class KodiArtwork:
    def __init__(self, client):
        self.client = client

    def fetch(self, reference):
        url = self.client.url.rsplit("/", 1)[0] + "/image/" + urllib.parse.quote(reference, safe="")
        request = urllib.request.Request(url, headers={"Authorization": self.client.auth})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=3) as response:
            content = response.read(4*1024*1024+1)
        if len(content) > 4*1024*1024 or not (content.startswith(bytes.fromhex("ffd8ff")) or content.startswith(bytes.fromhex("89504e470d0a1a0a")) or (content[:4] == b"RIFF" and content[8:12] == b"WEBP")):
            return b""
        return content
