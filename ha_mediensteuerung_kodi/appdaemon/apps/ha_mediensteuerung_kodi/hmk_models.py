"""Source-neutral models. Library IDs are opaque outside their owning adapter."""
from dataclasses import asdict, dataclass, field
import unicodedata

class MediaError(Exception):
    pass

@dataclass(frozen=True)
class Media:
    source: str
    kind: str
    library_id: int | str
    title: str
    year: int = 0
    thumbnail: str = ""
    file: str = ""
    season: int = -1
    episode: int = -1
    aliases: tuple[str, ...] = ()
    genres: tuple[str, ...] = ()
    actors: tuple[str, ...] = ()
    plot: str = ""
    collection: str = ""
    runtime: int = 0
    certification: str = ""
    play_count: int | None = None
    resume_seconds: float = 0
    first_aired: str = ""
    show_title: str = ""
    require_unwatched: bool = False
    start_resume: bool = False
    date_added: str = ""
    provider_ids: dict[str, str] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

@dataclass(frozen=True)
class MediaPage:
    items: tuple[Media, ...]
    total: int

    @property
    def truncated(self):
        return self.total > len(self.items)

    def to_dict(self):
        return {"items": [m.to_dict() for m in self.items], "total": self.total, "truncated": self.truncated}

@dataclass(frozen=True)
class Season:
    source: str
    series_id: int | str
    number: int
    title: str
    episode_count: int

    def to_dict(self):
        return asdict(self)

@dataclass(frozen=True)
class Playing:
    title: str
    kind: str
    media_id: int | str | None
    speed: int
    position_seconds: float
    duration_seconds: float

    def to_dict(self):
        return asdict(self)


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def resolve_unique(results, query, year=None):
    if not isinstance(query, str) or not query.strip():
        raise MediaError("Bitte einen Titel angeben.")
    if year is not None and (type(year) is not int or year < 1):
        raise MediaError("Das Jahr muss eine positive Ganzzahl sein.")
    matches = [m for m in results if normalized(m.title) == normalized(query)
               and (year is None or m.year == year)]
    if len(matches) != 1:
        raise MediaError("Kein eindeutiger exakter Treffer; bitte Titel/Jahr oder ID waehlen.")
    return matches[0]
