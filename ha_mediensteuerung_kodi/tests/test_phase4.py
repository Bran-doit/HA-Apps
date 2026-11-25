import importlib.util
import sys
import time
import unittest
from pathlib import Path
root=Path(sys.argv.pop(1));live=root.parents[1]/"apps"/"ha_mediensteuerung_kodi" if root.name=="phase4-stage" else root
spec=importlib.util.spec_from_file_location("voice_test",live/"__init__.py",submodule_search_locations=[str(root),str(live)])
package=importlib.util.module_from_spec(spec);sys.modules["voice_test"]=package;spec.loader.exec_module(package)
from voice_test.hmk_models import Media,MediaPage,MediaError
from voice_test.hmk_voice import VoiceController, number

class Library:
    def __init__(self):
        self.items=[Media("kodi:test","movie",1,"Matrix",1999),Media("kodi:test","movie",2,"Matrix Reloaded",2003),Media("kodi:test","movie",3,"Dune",1984),Media("kodi:test","movie",4,"Dune",2021),Media("kodi:test","series",5,"Andor",2022)]
    def search_media(self,query,kind):
        rows=tuple(m for m in self.items if query.casefold() in m.title.casefold() and m.kind==kind)
        return MediaPage(rows,len(rows))
    def get_episodes(self,media_id,season,source):
        return MediaPage((Media(source,"episode",33,"Episode Three",season=2,episode=3),),1)
class Players:
    def __init__(self):self.calls=[]
    def play(self,media,replace_current=False):
        self.calls.append((media,replace_current));return {"verified":True}
class VoiceTests(unittest.TestCase):
    def setUp(self):self.library=Library();self.players=Players();self.voice=VoiceController(self.library,self.players)
    def run_voice(self,text,**kw):return self.voice.handle({"text":text,"session":"device-a",**kw})
    def test_bare_exact_movie_replaces(self):
        r=self.run_voice("Spiel den Film Matrix")
        self.assertEqual(r["status"],"playing");self.assertEqual(self.players.calls[0][0].library_id,1);self.assertIs(self.players.calls[0][1],True)
    def test_explicit_room(self):
        r=self.run_voice("Spiele den Film Matrix im Wohnzimmer",dry_run=True)
        self.assertEqual(r["selected"]["library_id"],1);self.assertEqual(self.players.calls,[])
    def test_unknown_room(self):
        self.assertEqual(self.run_voice("Spiel den Film Matrix im Schlafzimmer")["status"],"error");self.assertEqual(self.players.calls,[])
    def test_episode_numbers(self):
        for text in ("Spiel Folge 3 von Staffel 2 von Andor","Kodi spiele Folge drei aus Staffel zwei von Andor"):
            self.assertEqual(self.run_voice(text,dry_run=True)["selected"]["library_id"],33)
    def test_missing_episode(self):
        self.assertEqual(self.run_voice("Spiel Folge 4 von Staffel 2 von Andor")["status"],"error");self.assertEqual(self.players.calls,[])
    def test_ambiguous_never_plays(self):
        r=self.run_voice("Spiel den Film Dune");self.assertEqual(r["status"],"choose");self.assertIn("1984",r["speech"]);self.assertIn("2021",r["speech"]);self.assertEqual(self.players.calls,[])
    def test_year_resolves(self):
        self.assertEqual(self.run_voice("Spiel den Film Dune aus dem Jahr 2021",dry_run=True)["selected"]["library_id"],4)
    def test_followup_scoped_and_expires(self):
        self.run_voice("Spiel den Film Dune")
        other=self.voice.handle({"text":"Kodi den Film von 1984","session":"device-b"})
        self.assertEqual(other["status"],"error")
        self.assertEqual(self.run_voice("Kodi den Film von 1984",dry_run=True)["selected"]["library_id"],3)
        pending=self.voice.pending['device-a'];self.voice.pending['device-a']=(time.monotonic()-121,*pending[1:])
        self.assertEqual(self.run_voice("Kodi den Film von 1984")["status"],"error")
    def test_music_falls_through(self):
        self.assertFalse(self.run_voice("Spiel ABBA")["handled"])
        self.assertFalse(self.run_voice("Spiel Mat")["handled"])
    def test_explicit_missing_does_not_fall_through(self):
        self.assertTrue(self.run_voice("Spiel den Film Unbekannt")["handled"])
    def test_partial_is_question(self):
        self.assertEqual(self.run_voice("Kodi spiel Film Mat")["status"],"choose");self.assertEqual(self.players.calls,[])
    def test_expired_does_not_play(self):
        self.assertEqual(self.run_voice("Spiel den Film Matrix",expires_at=time.time()-1)["status"],"error");self.assertEqual(self.players.calls,[])
    def test_dry_run_never_plays(self):
        self.assertEqual(self.run_voice("Spiel den Film Matrix",dry_run=True)["status"],"ready");self.assertEqual(self.players.calls,[])
    def test_spoken_dry_run(self):
        self.assertEqual(self.run_voice("Kodi prüfe Film Matrix")["status"],"ready");self.assertEqual(self.players.calls,[])
    def test_keyword_required_even_for_exact_movie(self):
        def forbidden(*args): raise AssertionError("Unmarked command reached Kodi library")
        self.library.search_media=forbidden
        for text in ("Spiel Matrix", "Spiel Dune", "Spiel Matrix im Wohnzimmer", "Spiel Matrix von 1999", "Spiel Filmstar", "Spiel Folgenreich", "Spiel ABBA"):
            self.assertFalse(self.run_voice(text)["handled"],text)
        self.assertEqual(self.run_voice("Kodi spiel Matrix")["status"],"error")
        self.assertEqual(self.players.calls,[])
    def test_incomplete_series_stays_with_kodi(self):
        for text in ("Spiel Staffel 1 von Andor", "Spiel Folge 3 von Andor", "Starte die Staffel eins von Andor"):
            result=self.run_voice(text)
            self.assertTrue(result["handled"])
            self.assertEqual(result["status"],"error")
            self.assertIn("Serientitel",result["speech"])
        self.assertEqual(self.players.calls,[])
    def test_umlaut_numbers(self):
        self.assertEqual(number("fünf"),5);self.assertEqual(number("zwölf"),12)
    def test_non_play_command_is_unhandled(self):
        self.assertFalse(self.run_voice("Pause")["handled"])
if __name__=="__main__":unittest.main()
