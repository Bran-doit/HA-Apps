"""Media search and player routing, independent of Kodi, HA and AppDaemon."""
from typing import Protocol, Callable
from .hmk_models import Media, MediaPage, Season, Playing, MediaError, resolve_unique

class MediaSource(Protocol):
    source_id: str
    def search_media(self, query: str, kind: str, limit: int) -> MediaPage: ...
    def get_movie(self, media_id: int | str) -> Media: ...
    def get_series(self, media_id: int | str) -> Media: ...
    def get_episode(self, media_id: int | str) -> Media: ...
    def get_seasons(self, series_id: int | str) -> tuple[Season, ...]: ...
    def get_episodes(self, series_id: int | str, season: int | None) -> MediaPage: ...

class MediaPlayer(Protocol):
    def can_play(self, media: Media) -> bool: ...
    def play(self, media: Media): ...
    def get_now_playing(self) -> tuple[Playing, ...]: ...
    def verify(self, media: Media) -> dict: ...

class MediaSearch:
    def __init__(self, sources: dict[str, MediaSource], default_source: str):
        self.sources = dict(sources)
        self.default_source = default_source
        self.source(default_source)

    def source(self, source_id=None):
        key = self.default_source if source_id is None else source_id
        if not isinstance(key, str) or key not in self.sources:
            raise MediaError("Unbekannte Medienquelle.")
        return self.sources[key]

    def search_media(self, query, media_type="movie", source_id=None, limit=100):
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            raise MediaError("Suchtext muss 1 bis 200 Zeichen enthalten.")
        if media_type not in ("movie", "series", "all"):
            raise MediaError("Bitte Film, Serie oder Alle auswaehlen.")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise MediaError("Ungueltige Trefferbegrenzung.")
        source = self.source(source_id)
        kinds = ("movie", "series") if media_type == "all" else (media_type,)
        pages = [source.search_media(query.strip(), kind, limit) for kind in kinds]
        return MediaPage(tuple(item for page in pages for item in page.items), sum(p.total for p in pages))

    def search_voice(self, query, media_type="movie", year=None, source_id=None):
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            raise MediaError("Suchtext muss 1 bis 200 Zeichen enthalten.")
        if media_type not in ("movie", "series"):
            raise MediaError("Die Sprachsuche unterstützt Film und Serie.")
        if year is not None and (type(year) is not int or not 1 <= year <= 9999):
            raise MediaError("Ungültiges Erscheinungsjahr.")
        source = self.source(source_id)
        if not hasattr(source, "title_catalog"):
            return self.search_media(query, media_type, source_id)
        from .hmk_matching import match_catalog
        return match_catalog(source.title_catalog(media_type), query.strip(), year)

    def search_titles(self, query, media_type="movie", year=None):
        # Reuse validation, then retain related titles even when an exact title exists.
        page=self.search_voice(query,media_type,year)
        source=self.source()
        if not hasattr(source,"title_catalog"):
            return page
        from .hmk_matching import match_catalog
        return match_catalog(source.title_catalog(media_type),query.strip(),year,broad=True)

    def metadata_catalog(self, kind="movie", series_id=None, source_id=None, filters=None):
        source = self.source(source_id)
        if not hasattr(source, "metadata_catalog"):
            raise MediaError("Diese Quelle unterstützt noch keine Metadatenabfragen.")
        return source.metadata_catalog(kind, series_id, filters)

    def get_movie(self, media_id, source_id=None):
        return self.source(source_id).get_movie(media_id)

    def get_series(self, media_id, source_id=None):
        return self.source(source_id).get_series(media_id)

    def get_episode(self, media_id, source_id=None):
        return self.source(source_id).get_episode(media_id)

    def get_seasons(self, series_id, source_id=None):
        return self.source(source_id).get_seasons(series_id)

    def get_episodes(self, series_id, season=None, source_id=None):
        return self.source(source_id).get_episodes(series_id, season)

    def resolve_media(self, query, media_type="movie", year=None, source_id=None):
        page = self.search_media(query, media_type, source_id)
        if page.truncated:
            raise MediaError("Zu viele Treffer; Suche bitte eingrenzen.")
        return resolve_unique(page.items, query, year)

class PlayerManager:
    def __init__(self, players: dict[str, MediaPlayer], default_player: str):
        self.players = dict(players)
        self.default_player = default_player
        self.resolvers: dict[tuple[str, str], Callable[[Media], Media]] = {}
        self.player(default_player)

    def player(self, player_id=None):
        key = self.default_player if player_id is None else player_id
        if not isinstance(key, str) or key not in self.players:
            raise MediaError("Unbekanntes Wiedergabegeraet.")
        return self.players[key]

    def register_resolver(self, source_id, player_id, resolver):
        self.player(player_id)
        if not callable(resolver):
            raise MediaError("Ungueltiger Medienresolver.")
        self.resolvers[(source_id, player_id)] = resolver

    def resolve_media(self, media, player_id=None):
        key = self.default_player if player_id is None else player_id
        player = self.player(key)
        if media.kind not in ("movie", "episode"):
            raise MediaError("Bitte einen Film oder eine konkrete Episode auswaehlen.")
        if player.can_play(media):
            return media
        resolver = self.resolvers.get((media.source, key))
        if resolver is None:
            raise MediaError("Fuer diese Medienquelle und diesen Player fehlt eine Zuordnung.")
        resolved = resolver(media)
        if not isinstance(resolved, Media) or resolved.kind not in ("movie", "episode") or not player.can_play(resolved):
            raise MediaError("Medienzuordnung lieferte keinen abspielbaren Eintrag.")
        return resolved

    def get_now_playing(self, player_id=None):
        return self.player(player_id).get_now_playing()

    def play(self, media, player_id=None, replace_current=False):
        player = self.player(player_id)
        before_play = getattr(self, "before_play", None)
        if before_play:
            before_play()
        resolved = self.resolve_media(media, player_id)
        if player.get_now_playing() and replace_current is not True:
            raise MediaError("Wiedergabe laeuft bereits; explizit replace_current: true erforderlich")
        result = {"selected": media.to_dict(), "resolved": resolved.to_dict(),
                  "player": self.default_player if player_id is None else player_id,
                  "open_result": player.play(resolved)}
        result.update(player.verify(resolved))
        return result
