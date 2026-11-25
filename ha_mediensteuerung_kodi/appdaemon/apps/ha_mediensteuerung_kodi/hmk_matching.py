"""Deterministic title matching. Approximate matches are suggestions, never consent."""
import re
import unicodedata
from difflib import SequenceMatcher
from .hmk_models import MediaPage

def title_key(value):
    return " ".join(re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", value).casefold()).split())

def folded(value):
    value = title_key(value).replace("Ã¤", "ae").replace("Ã¶", "oe").replace("Ã¼", "ue")
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))

def names(media):
    return (media.title, *media.aliases)

def exact_title(media, query):
    return any(title_key(name) == title_key(query) for name in names(media))

def similarity(query, title):
    a, b = folded(query), folded(title)
    if not a or not b:
        return 0.0
    if a == b or a.replace(" ", "") == b.replace(" ", ""):
        return 0.99
    if min(len(a.replace(" ", "")), len(b.replace(" ", ""))) < 4:
        return 0.0
    # A recognized sequel number must not be silently changed to another one.
    an, bn = re.findall(r"\b\d+\b", a), re.findall(r"\b\d+\b", b)
    if an and bn and an != bn:
        return 0.0
    if a in b:
        return 0.84 + 0.1 * len(a) / len(b)
    def phonetic(value):
        for old, new in (("ph", "f"), ("ck", "k"), ("x", "ks"), ("th", "t")):
            value = value.replace(old, new)
        return value.replace(" ", "")
    phonetic_score = SequenceMatcher(None, phonetic(a), phonetic(b), autojunk=False).ratio() * 0.94
    direct = SequenceMatcher(None, a, b, autojunk=False).ratio()
    compact = SequenceMatcher(None, a.replace(" ", ""), b.replace(" ", ""), autojunk=False).ratio()
    tokens = SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split())), autojunk=False).ratio()
    return max(direct, compact * 0.98, tokens * 0.95, phonetic_score)

def match_catalog(items, query, year=None, limit=10, broad=False):
    items = [m for m in items if year is None or m.year == year]
    exact = [m for m in items if exact_title(m, query)]
    if exact and not broad:
        return MediaPage(tuple(exact[:limit]), len(exact))
    if broad:
        related=[m for m in items if any(folded(query) in folded(name) for name in names(m))]
        if related:
            related.sort(key=lambda m:(not exact_title(m,query),m.year,title_key(m.title),str(m.library_id)))
            return MediaPage(tuple(related[:limit]),len(related))
    scored = [(max(similarity(query, name) for name in names(m)), m) for m in items]
    threshold = 0.78 if len(folded(query).replace(" ", "")) >= 6 else 0.82
    scored = [(score, m) for score, m in scored if score >= threshold]
    scored.sort(key=lambda pair: (-pair[0], title_key(pair[1].title), pair[1].year, str(pair[1].library_id)))
    return MediaPage(tuple(m for _, m in scored[:limit]), len(scored))
