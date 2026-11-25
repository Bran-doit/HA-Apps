import importlib.util
import sys
import unittest
from pathlib import Path

root = Path(sys.argv.pop(1))
spec = importlib.util.spec_from_file_location("hmk_test", root / "__init__.py", submodule_search_locations=[str(root)])
package = importlib.util.module_from_spec(spec)
sys.modules["hmk_test"] = package
spec.loader.exec_module(package)
from hmk_test.hmk_models import Media, MediaPage, Season, Playing, MediaError
from hmk_test.hmk_media import MediaSearch, PlayerManager
from hmk_test.hmk_kodi import KodiMediaSource, KodiMediaPlayer

class Source:
    source_id = "test-library"
    def __init__(self):
        self.items = (Media(self.source_id,"movie","opaque-id","Matrix",1999),)
        self.total = 1
    def search_media(self, query, kind, limit):
        return MediaPage(self.items, self.total)
    def get_movie(self, media_id):
        return self.items[0]
    def get_series(self, media_id):
        return Media(self.source_id,"series",media_id,"Series")
    def get_episode(self, media_id):
        return Media(self.source_id,"episode",media_id,"Episode",season=0,episode=1)
    def get_seasons(self, series_id):
        return (Season(self.source_id,series_id,0,"Specials",1),)
    def get_episodes(self, series_id, season):
        return MediaPage((self.get_episode("e1"),),1)

class Player:
    def __init__(self, source="test-library"):
        self.source = source
        self.calls = []
        self.current = ()
        self.verified = True
    def can_play(self, media):
        return media.source == self.source
    def get_now_playing(self):
        return self.current
    def play(self, media):
        self.calls.append(media)
        return "OK"
    def verify(self, media):
        return {"verified": self.verified}

class LayerTests(unittest.TestCase):
    def setUp(self):
        self.source = Source()
        self.search = MediaSearch({"test-library":self.source},"test-library")
        self.player = Player()
        self.manager = PlayerManager({"family":self.player},"family")

    def test_generic_source_supports_opaque_non_kodi_ids(self):
        media=self.search.resolve_media(" MATRIX ",year=1999)
        self.assertEqual(media.library_id,"opaque-id")
        self.assertTrue(self.manager.play(media)["verified"])
        self.assertEqual(len(self.player.calls),1)

    def test_ambiguous_titles_do_not_resolve(self):
        self.source.items += (Media("test-library","movie","second","Matrix",2001),)
        self.source.total=2
        with self.assertRaises(MediaError): self.search.resolve_media("Matrix")
        self.assertEqual(self.search.resolve_media("Matrix",year=1999).library_id,"opaque-id")

    def test_truncated_results_do_not_resolve(self):
        self.source.total=101
        with self.assertRaises(MediaError): self.search.resolve_media("Matrix")

    def test_invalid_source_and_player_do_not_fallback(self):
        with self.assertRaises(MediaError): self.search.search_media("Matrix",source_id="unknown")
        with self.assertRaises(MediaError): self.manager.play(self.source.items[0],"unknown")
        self.assertEqual(self.player.calls,[])

    def test_different_library_needs_resolver(self):
        foreign=Media("emby","movie","123","Matrix",1999)
        with self.assertRaises(MediaError): self.manager.play(foreign)
        self.assertEqual(self.player.calls,[])
        self.manager.register_resolver("emby","family",lambda media:self.source.items[0])
        result=self.manager.play(foreign)
        self.assertEqual(result["selected"]["source"],"emby")
        self.assertEqual(result["resolved"]["source"],"test-library")

    def test_invalid_resolver_result_does_not_play(self):
        self.manager.register_resolver("emby","family",lambda media:media)
        with self.assertRaises(MediaError): self.manager.play(Media("emby","movie","123","Matrix"))
        self.assertEqual(self.player.calls,[])

    def test_running_playback_requires_explicit_boolean(self):
        self.player.current=(Playing("Already playing","movie",5,1,20,100),)
        for replacement in (False,"true",1):
            with self.assertRaises(MediaError): self.manager.play(self.source.items[0],replace_current=replacement)
        self.assertEqual(self.player.calls,[])
        self.manager.play(self.source.items[0],replace_current=True)
        self.assertEqual(len(self.player.calls),1)

    def test_unverified_start_is_not_retried(self):
        self.player.verified=False
        self.assertFalse(self.manager.play(self.source.items[0])["verified"])
        self.assertEqual(len(self.player.calls),1)

    def test_series_is_not_started(self):
        with self.assertRaises(MediaError): self.manager.play(self.search.get_series("s1"))
        self.assertEqual(self.player.calls,[])

    def test_season_zero_is_preserved(self):
        self.assertEqual(self.search.get_seasons("s1")[0].number,0)
        self.assertEqual(self.search.get_episodes("s1",0).items[0].season,0)

    def test_invalid_search_arguments(self):
        for query in (None,"",123,"a"*201):
            with self.assertRaises(MediaError): self.search.search_media(query)
        for limit in (0,101,True):
            with self.assertRaises(MediaError): self.search.search_media("Matrix",limit=limit)
        with self.assertRaises(MediaError): self.search.resolve_media("Matrix",year=True)

class KodiTranslationTests(unittest.TestCase):
    def test_series_and_seasons_are_normalized(self):
        class Client:
            source_id="kodi:test"
            def rpc(self, method, params):
                if method=="VideoLibrary.GetTVShowDetails":
                    return {"tvshowdetails":{"tvshowid":3,"title":"Downton Abbey","year":2010}}
                return {"seasons":[{"season":0,"episode":5}]}
        source=KodiMediaSource(Client())
        self.assertEqual(source.get_series(3).kind,"series")
        self.assertEqual(source.get_seasons(3)[0].number,0)
        self.assertEqual(source.get_seasons(3)[0].episode_count,5)

    def test_kodi_player_rejects_foreign_and_string_ids(self):
        class Client: source_id="kodi:test"
        player=KodiMediaPlayer(Client())
        self.assertTrue(player.can_play(Media("kodi:test","movie",3,"Title")))
        self.assertFalse(player.can_play(Media("kodi:other","movie",3,"Title")))
        self.assertFalse(player.can_play(Media("kodi:test","movie","3","Title")))

if __name__=="__main__": unittest.main()
