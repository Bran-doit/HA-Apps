import importlib.util
import time
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
root=Path(sys.argv.pop(1))
spec=importlib.util.spec_from_file_location('complete_test',root/'__init__.py',submodule_search_locations=[str(root)])
pkg=importlib.util.module_from_spec(spec);sys.modules['complete_test']=pkg;spec.loader.exec_module(pkg)
from complete_test.hmk_models import Media, MediaPage, MediaError
from complete_test.hmk_matching import match_catalog
from complete_test.hmk_media import MediaSearch
from complete_test.hmk_voice import VoiceController
from complete_test.hmk_kodi import KodiMediaSource

class Library:
    source_id='test'
    def __init__(self):
        self.items=(Media('test','movie',1,'Matrix',1999,aliases=('The Matrix',)),Media('test','movie',2,'Matrix Reloaded',2003),Media('test','movie',3,'Dune',1984),Media('test','movie',4,'Dune',2021),Media('test','series',5,'Downton Abbey',2010),Media('test','movie',6,'Die fabelhafte Welt der Amélie',2001,aliases=('Amélie',)),Media('test','movie',7,'Spider-Man',2002),Media('test','movie',8,'Alien 3',1992),Media('test','movie',9,'Alien 4',1997))
        self.calls=0
    def title_catalog(self,kind):
        self.calls+=1
        return tuple(m for m in self.items if m.kind==kind)
    def get_movie(self,mid):return next(m for m in self.items if m.library_id==mid)
    get_series=get_movie
    def get_episodes(self,mid,season):return MediaPage((Media('test','episode',30,'Episode Three',season=1,episode=3),),1)
class Players:
    def __init__(self):self.calls=[]
    def play(self,media,replace_current):self.calls.append((media,replace_current));return {'verified':True}
class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.lib=Library();self.media=MediaSearch({'test':self.lib},'test');self.players=Players();self.voice=VoiceController(self.media,self.players)
    def say(self,text,**kw):return self.voice.handle({'text':text,'session':'a',**kw})
    def test_original_title_exact(self):
        r=self.say('Spiel den Film The Matrix',dry_run=True)
        self.assertEqual(r['selected']['library_id'],1)
    def test_typos_are_never_auto_played(self):
        for text in ('Matriks','Metrix','Mtarix','Spiderman','Amelie'):
            r=self.say('Spiel den Film '+text)
            self.assertEqual(r['status'],'choose',text)
        self.assertEqual(self.players.calls,[])
    def test_punctuation_normalization_is_exact(self):
        self.assertEqual(self.say('Spiel den Film Spider Man',dry_run=True)['selected']['library_id'],7)
    def test_unrelated_text(self):
        self.assertEqual(self.say('Spiel den Film Qzywvrpt')['status'],'not_found')
    def test_short_titles_not_fuzzied(self):
        self.assertEqual(match_catalog(self.lib.items,'Du').items,())
    def test_year_filters_before_matching(self):
        r=self.say('Spiel den Film Dune aus dem Jahr 2021',dry_run=True)
        self.assertEqual(r['selected']['library_id'],4)
        self.assertEqual(self.say('Spiel den Film Dune aus dem Jahr 1999')['status'],'not_found')
    def test_alias_collision_asks(self):
        self.lib.items+=(Media('test','movie',99,'Andere Matrix',2000,aliases=('The Matrix',)),)
        self.assertEqual(self.say('Spiel den Film The Matrix')['status'],'choose')
        self.assertEqual(self.players.calls,[])
    def test_sequel_number_respected(self):
        r=self.say('Spiel den Film Alian 4')
        self.assertEqual([m['library_id'] for m in r['choices']],[9])
    def test_numbered_confirmation(self):
        self.say('Spiel den Film Matriks')
        r=self.say('Kodi nimm Film Nummer eins')
        self.assertEqual(r['status'],'playing')
        self.assertEqual(self.players.calls[0][0].library_id,1)
        self.assertIs(self.players.calls[0][1],True)
    def test_confirmation_without_kodi_prefix(self):
        self.say('Spiel den Film Matriks')
        self.assertEqual(self.say('Spiel den Film Nummer eins')['status'],'playing')
    def test_wrong_number_and_kind(self):
        self.say('Spiel den Film Matriks')
        for text in ('Kodi nimm Film Nummer null','Kodi nimm Film Nummer 99','Kodi nimm Folge Nummer eins'):
            self.assertNotEqual(self.say(text)['status'],'playing')
        self.assertEqual(self.players.calls,[])
    def test_confirmation_session_isolation(self):
        self.say('Spiel den Film Matriks')
        r=self.voice.handle({'text':'Kodi nimm Film Nummer eins','session':'b'})
        self.assertEqual(r['status'],'error');self.assertEqual(self.players.calls,[])
    def test_new_search_invalidates_choices(self):
        self.say('Spiel den Film Matriks');self.say('Spiel den Film Qzywvrpt')
        self.assertEqual(self.say('Kodi nimm Film Nummer eins')['status'],'error')
    def test_dry_run_propagates_to_confirmation(self):
        self.say('Kodi pruefe Film Matriks')
        self.assertEqual(self.say('Kodi nimm Film Nummer eins')['status'],'ready')
        self.assertEqual(self.players.calls,[])
    def test_series_typo_keeps_episode(self):
        r=self.say('Spiel Folge drei von Staffel eins von Downton Abey')
        self.assertEqual(r['status'],'choose');self.assertIn('Folge Nummer eins',r['speech'])
        self.assertEqual(self.say('Kodi nimm Folge Nummer eins',dry_run=True)['selected']['library_id'],30)
    def test_reversed_season_episode(self):
        for text in ('Spiel Staffel eins Folge drei von Downton Abbey','Spiel Folge drei Staffel eins Downton Abbey'):
            self.assertEqual(self.say(text,dry_run=True)['selected']['library_id'],30)
    def test_stale_id_never_plays(self):
        self.say('Spiel den Film Matriks')
        self.lib.items=(Media('test','movie',1,'Different movie',2020),)
        self.assertEqual(self.say('Kodi nimm Film Nummer eins')['status'],'error')
        self.assertEqual(self.players.calls,[])
    def test_keywords_required_before_catalog(self):
        for text in ('Spiel Matrix','Spiel Matriks','Spiel Filmstar','Spiel Folgenreich'):
            self.assertFalse(self.say(text)['handled'])
        self.assertEqual(self.lib.calls,0)
    def test_duplicate_alias_not_duplicate_result(self):
        m=Media('test','movie',10,'Matrix',1999,aliases=('Matrix','The Matrix'))
        self.assertEqual(match_catalog((m,),'Matrix').total,1)
    def test_empty_and_oversize_input(self):
        for query in ('','x'*201):
            with self.assertRaises(MediaError):self.media.search_voice(query)

class CatalogTests(unittest.TestCase):
    def client(self,total=501,fail=False,duplicate=False):
        class Client:
            source_id='test'
            def __init__(self):self.calls=[]
            def rpc(self,method,params):
                self.calls.append(params);start=params['limits']['start'];end=min(params['limits']['end'],total)
                rows=[{'movieid':i+1,'title':'Title '+str(i),'originaltitle':'Original '+str(i),'year':2000} for i in range(start,end)]
                if start and fail:rows=[]
                if start and duplicate:rows[0]['movieid']=1
                return {'movies':rows,'limits':{'total':total}}
        return Client()
    def test_pagination_original_titles_and_cache(self):
        client=self.client();source=KodiMediaSource(client)
        items=source.title_catalog('movie');self.assertEqual(len(items),501);self.assertEqual(items[0].aliases,('Original 0',))
        self.assertIs(source.title_catalog('movie'),items);self.assertEqual(len(client.calls),2)
    def test_expired_cache_refreshes(self):
        client=self.client(1);source=KodiMediaSource(client);source.title_catalog('movie')
        source._catalog['movie']=(time.monotonic()-301,());source.title_catalog('movie');self.assertEqual(len(client.calls),2)
    def test_incomplete_never_cached(self):
        source=KodiMediaSource(self.client(fail=True))
        with self.assertRaises(MediaError):source.title_catalog('movie')
        self.assertEqual(source._catalog,{})
    def test_duplicate_ids_rejected(self):
        with self.assertRaises(MediaError):KodiMediaSource(self.client(duplicate=True)).title_catalog('movie')
    def test_empty_library(self):
        self.assertEqual(KodiMediaSource(self.client(0)).title_catalog('movie'),())
if __name__=='__main__':unittest.main()