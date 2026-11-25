import importlib.util,sys,unittest
from pathlib import Path
from dataclasses import replace
root=Path(sys.argv.pop(1));spec=importlib.util.spec_from_file_location('phase5_test',root/'__init__.py',submodule_search_locations=[str(root)]);pkg=importlib.util.module_from_spec(spec);sys.modules['phase5_test']=pkg;spec.loader.exec_module(pkg)
from phase5_test.hmk_models import Media,MediaPage,MediaError
from phase5_test.hmk_intelligent import Query,parse_query,movie_matches,IntelligentSearch
from phase5_test.hmk_voice import VoiceController
from phase5_test.hmk_adapter import KodiPlayer
class Source:
 def __init__(self):
  self.movies=[Media('test','movie',1,'Goldfinger',1964,actors=('Sean Connery',),collection='James Bond Collection',play_count=0),Media('test','movie',2,'Blade Runner',1982,actors=('Harrison Ford',),genres=('Science Fiction',),play_count=0),Media('test','movie',3,'Kinderfilm',2000,genres=('Familienfilm',),certification='FSK 6',play_count=0,runtime=5400)]
  self.episodes=[Media('test','episode',10,'Gesehen',season=1,episode=1,play_count=1),Media('test','episode',11,'Angefangen',season=1,episode=2,play_count=0,resume_seconds=600),Media('test','episode',12,'Die Tribbles',season=1,episode=3,play_count=0,plot='Auf dem Schiff erscheinen die Tribbles.'),Media('test','episode',13,'Special',season=0,episode=1,play_count=0)]
 def metadata_catalog(self,kind,series_id=None,filters=None):return self.movies if kind=='movie' else self.episodes
 def search_voice(self,query,kind,year=None):return MediaPage((Media('test','series',9,'Andor'),),1)
 def get_movie(self,mid,source=None):return next(m for m in self.movies if m.library_id==mid)
 def get_episode(self,mid,source=None):return next(m for m in self.episodes if m.library_id==mid)
class Player:
 def __init__(self):self.calls=[]
 def play(self,media,replace_current=False):self.calls.append(media);return {'verified':True}
class IntentTests(unittest.TestCase):
 def setUp(self):self.source=Source();self.source.episodes=[replace(m,date_added='2026-01-%02d 12:00:00'%(i+1)) for i,m in enumerate(self.source.episodes)];self.engine=IntelligentSearch(self.source);self.player=Player();self.voice=VoiceController(self.source,self.player)
 def say(self,text,**kw):return self.voice.handle({'text':text,'session':'test',**kw})
 def test_bond_actor(self):
  q=parse_query('Spiel einen James-Bond-Film mit Sean Connery');self.assertEqual([m.library_id for m in self.engine.resolve(q)[0]],[1])
 def test_unseen_actor(self):
  q=parse_query('Spiel einen Film mit Harrison Ford, den wir noch nicht gesehen haben');self.assertTrue(q.unseen);self.assertEqual(self.engine.resolve(q)[0][0].library_id,2)
 def test_genre_decade(self):
  for text in ('Spiel einen Science-Fiction-Film aus den Achtzigern','Spiel einen Science Fiction Film aus den 1980ern'):
   self.assertEqual(self.engine.resolve(parse_query(text))[0][0].library_id,2)
 def test_children_unknown_rating_excluded(self):
  q=parse_query('Such einen Kinderfilm, den wir noch nicht gesehen haben');self.assertTrue(q.search_only);self.assertEqual(self.engine.resolve(q)[0][0].library_id,3)
  self.source.movies[2]=replace(self.source.movies[2],certification='');self.assertEqual(self.engine.resolve(q)[0],[])
 def test_child_age(self):
  q=parse_query('Suche einen Film für Kinder ab 0 Jahren');self.assertEqual(self.engine.resolve(q)[0],[])
 def test_runtime(self):
  q=parse_query('Suche einen Film unter 90 Minuten');self.assertEqual(self.engine.resolve(q)[0][0].library_id,3)
  self.assertFalse(movie_matches(replace(self.source.movies[2],runtime=0),q))
 def test_unknown_playcount_is_not_unseen(self):
  self.assertFalse(movie_matches(replace(self.source.movies[0],play_count=None),Query('movies',unseen=True)))
 def test_unknown_filter_rejected(self):
  with self.assertRaises(MediaError):parse_query('Spiel einen Film ohne Gewalt')
 def test_concrete_title_not_interpreted(self):self.assertIsNone(parse_query('Spiel den Film Matrix'))
 def test_latest_search_variants_never_play(self):
  for phrase in ('neueste','neuste','zuletzt hinzugefügte'):
   result=self.say('Suche die '+phrase+' Folge von Andor')
   self.assertEqual(result['status'],'choose');self.assertEqual(result['choices'][0]['library_id'],12)
  self.assertEqual(self.player.calls,[])
 def test_latest_seen_and_missing_watch_state(self):
  self.source.episodes[2]=replace(self.source.episodes[2],play_count=None)
  self.assertEqual(self.engine.resolve(Query('latest',series='Andor',search_only=True))[0][0].library_id,12)
 def test_latest_uses_added_not_episode_or_release(self):
  self.source.episodes[0]=replace(self.source.episodes[0],date_added='2026-09-01 12:00:00',first_aired='1999-01-01')
  self.assertEqual(self.engine.resolve(Query('latest',series='Andor'))[0][0].library_id,10)
 def test_latest_season_lists_older_added_season(self):
  self.source.episodes[0]=replace(self.source.episodes[0],season=2)
  rows,auto,_=self.engine.resolve(parse_query('Suche die neueste Staffel von Andor'))
  self.assertEqual([m.library_id for m in rows],[11,12]);self.assertFalse(auto)
 def test_latest_missing_date_errors(self):
  self.source.episodes[0]=replace(self.source.episodes[0],date_added='')
  with self.assertRaises(MediaError):self.engine.resolve(Query('latest',series='Andor'))
 def test_latest_duplicate_offered_not_autoplayed(self):
  self.source.episodes.append(replace(self.source.episodes[2],library_id=99))
  rows,auto,_=self.engine.resolve(Query('latest',series='Andor'))
  self.assertEqual(len(rows),2);self.assertFalse(auto)
 def test_duplicate_series_identity_merges_episode_ids(self):
  shows=(Media('test','series',9,'Andor',provider_ids={'tvdb':'123'}),Media('test','series',19,'Andor',provider_ids={'tvdb':'123'}))
  self.source.search_voice=lambda *args:MediaPage(shows,2)
  self.source.get_series=lambda mid:next(m for m in shows if m.library_id==mid)
  rows,_,_=self.engine.resolve(Query('latest',series='Andor',search_only=True))
  self.assertEqual([m.library_id for m in rows],[12])
 def test_same_title_different_series_stays_ambiguous(self):
  shows=(Media('test','series',9,'Andor',provider_ids={'tvdb':'123'}),Media('test','series',19,'Andor',provider_ids={'tvdb':'456'}))
  self.source.search_voice=lambda *args:MediaPage(shows,2)
  self.source.get_series=lambda mid:next(m for m in shows if m.library_id==mid)
  with self.assertRaises(MediaError):self.engine.resolve(Query('latest',series='Andor'))
 def test_latest_empty(self):
  self.source.episodes=[]
  self.assertEqual(self.engine.resolve(Query('latest',series='Andor'))[0],[])
 def test_next_regular_unseen_and_resume(self):
  rows,auto,_=self.engine.resolve(parse_query('Spiel die nächste noch nicht gesehene Folge von Andor'))
  self.assertTrue(auto);self.assertEqual(rows[0].library_id,11);self.assertTrue(rows[0].start_resume)
 def test_future_episode_excluded(self):
  self.source.episodes[1]=replace(self.source.episodes[1],first_aired='2999-01-01')
  self.assertEqual(self.engine.resolve(Query('next',series='Andor'))[0][0].library_id,12)
 def test_next_unknown_state_errors(self):
  self.source.episodes[0]=replace(self.source.episodes[0],play_count=None)
  with self.assertRaises(MediaError):self.engine.resolve(Query('next',series='Andor'))
 def test_all_seen(self):
  self.source.episodes=[replace(m,play_count=1) for m in self.source.episodes]
  self.assertEqual(self.engine.resolve(Query('next',series='Andor'))[0],[])
 def test_duplicate_next_errors(self):
  self.source.episodes.append(replace(self.source.episodes[1],library_id=50))
  with self.assertRaises(MediaError):self.engine.resolve(Query('next',series='Andor'))
 def test_plot_evidence(self):
  rows,auto,_=self.engine.resolve(parse_query('Spiel die Folge von Andor mit den Tribbles'))
  self.assertEqual([m.library_id for m in rows],[12]);self.assertFalse(auto)
 def test_plot_no_invented_answer(self):self.assertEqual(self.engine.resolve(Query('plot',series='Andor',topic='Klingonen'))[0],[])
 def test_filtered_movie_always_confirmed(self):
  self.assertEqual(self.say('Spiel einen Film mit Sean Connery')['status'],'choose');self.assertEqual(self.player.calls,[])
  self.assertEqual(self.say('Kodi nimm Film Nummer eins')['status'],'playing')
 def test_unseen_rechecked_on_confirmation(self):
  self.say('Spiel einen ungesehenen Film mit Sean Connery');self.source.movies[0]=replace(self.source.movies[0],play_count=1)
  self.assertEqual(self.say('Kodi nimm Film Nummer eins')['status'],'error');self.assertEqual(self.player.calls,[])
 def test_next_dry_run(self):
  r=self.say('Kodi prüfe die nächste ungesehene Folge von Andor');self.assertEqual(r['status'],'ready');self.assertTrue(r['selected']['start_resume']);self.assertEqual(self.player.calls,[])
 def test_next_search_never_plays(self):
  self.assertEqual(self.say('Suche die nächste Folge von Andor')['status'],'choose');self.assertEqual(self.player.calls,[])
 def test_plot_selection_plays_episode(self):
  self.say('Spiel die Folge von Andor mit den Tribbles');r=self.say('Kodi nimm Folge Nummer eins');self.assertEqual(r['selected']['library_id'],12)
 def test_unconfigured_room(self):self.assertEqual(self.say('Spiel einen Film mit Sean Connery im Schlafzimmer')['status'],'error')
 def test_resume_json_rpc(self):
  class Client:
   source_id='test'
   def rpc(self,method,params):self.params=params;return 'OK'
  client=Client();KodiPlayer(client).play(replace(self.source.episodes[1],start_resume=True));self.assertEqual(client.params['options'],{'resume':True})
if __name__=='__main__':unittest.main()