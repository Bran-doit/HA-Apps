import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'appdaemon'/'apps'))
from ha_mediensteuerung_kodi.hmk_startup import KodiStartup
from ha_mediensteuerung_kodi.hmk_models import MediaError
class Tests(unittest.TestCase):
 def setup(self,states,launch_error=None):
  self.t=0;self.calls=0;self.states=iter(states)
  def probe():return next(self.states,False)
  def launch():
   self.calls+=1
   if launch_error:raise launch_error
  def sleep(t):self.t+=t
  return KodiStartup(probe,launch,timeout=3,clock=lambda:self.t,sleep=sleep)
 def test_ready_no_launch(self):
  self.assertEqual(self.setup([True]).ensure()['status'],'already_ready');self.assertEqual(self.calls,0)
 def test_cold_start(self):
  r=self.setup([False,False,True]).ensure();self.assertEqual(r['status'],'launched');self.assertEqual(self.calls,1)
 def test_background_foreground(self):
  self.assertEqual(self.setup([True,True]).ensure(True)['status'],'launched');self.assertEqual(self.calls,1)
 def test_failure_bounded_single_launch(self):
  with self.assertRaises(MediaError):self.setup([False]).ensure()
  self.assertEqual(self.calls,1);self.assertEqual(self.t,3)
 def test_service_error(self):
  with self.assertRaises(MediaError):self.setup([False],RuntimeError('network')).ensure()
  self.assertEqual(self.calls,1)
 def test_background_not_mistaken_for_ready_after_launch(self):
  starter=self.setup([True,True,True,True,True]);starter.foreground=lambda:False
  with self.assertRaises(MediaError):starter.ensure(True)
  self.assertEqual(self.calls,1)
 def test_timeout_validation(self):
  for n in (True,0,100,'20'):
   with self.assertRaises(ValueError):KodiStartup(lambda:False,lambda:None,n)
if __name__=='__main__':unittest.main()