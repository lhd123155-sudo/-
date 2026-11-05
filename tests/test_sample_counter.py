import unittest,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sample_counter import SampleCounter, content_bounds
class ScreenshotCounting(unittest.TestCase):
 def setUp(self):
  rng=np.random.default_rng(8);self.frames={k:rng.integers(0,256,(80,120,3),dtype=np.uint8) for k in ['normal','death','complete']}
  self.samples={k:[dict(rect=(10,10,80,40),image=f[10:50,10:90])] for k,f in self.frames.items()}
  self.c=SampleCounter(self.samples,(120,80))
 def feed(self,k,t):return self.c.process(self.frames[k],t)
 def ready(self):self.feed('normal',0);self.feed('normal',.08)
 def test_death_and_clear_once_each(self):
  self.ready();self.feed('death',.16);self.assertEqual(self.feed('death',.24)['event'],'death')
  self.assertIsNone(self.feed('death',.32)['event']);self.feed('normal',.40);self.feed('normal',.48)
  self.feed('complete',.56);self.assertEqual(self.feed('complete',.64)['event'],'complete')
 def test_recording_started_on_death_does_not_count(self):
  self.feed('death',0);self.assertIsNone(self.feed('death',.08)['event'])
 def test_unknown_frame_does_not_rearm(self):
  self.ready();self.feed('death',.16);self.feed('death',.24)
  self.c.process(np.zeros((80,120,3),np.uint8),.32)
  self.feed('death',.4);self.assertIsNone(self.feed('death',.48)['event'])
 def test_pause_keeps_death_latched(self):
  self.ready();self.feed('death',.16);self.feed('death',.24);self.c.pause()
  self.feed('death',4);self.assertIsNone(self.feed('death',4.08)['event'])
 def test_no_event_without_sample(self):
  self.c.samples['death']=[];self.ready();self.feed('death',.16);self.assertFalse(self.feed('death',.24).get('event'))
 def test_window_size_change_keeps_counting(self):
  self.ready()
  resized=np.repeat(np.repeat(self.frames['death'],2,axis=0),2,axis=1)
  self.c.process(resized,.16)
  self.assertEqual(self.c.process(resized,.24)['event'],'death')
  self.assertIsNone(self.feed('death',.32)['event'])
 def test_letterbox_change_keeps_content_aligned(self):
  def pad(frame, amount):return np.pad(frame,((amount,amount),(0,0),(0,0)))
  reference={k:pad(frame,5) for k,frame in self.frames.items()}
  samples={k:[dict(rect=(10,15,80,40),image=frame[15:55,10:90])] for k,frame in reference.items()}
  detector=SampleCounter(samples,(120,90),content_bounds(reference['normal']))
  detector.process(reference['normal'],0)
  detector.process(pad(self.frames['normal'],9),.08)
  detector.process(pad(self.frames['death'],9),.16)
  self.assertEqual(detector.process(pad(self.frames['death'],9),.24)['event'],'death')
 def test_checkpoint_reload_does_not_rearm_or_count_a_second_death(self):
  self.ready();self.feed('death',.16);self.assertEqual(self.feed('death',.24)['event'],'death')
  for stamp in (.32,.40):
   result=self.c.process(self.frames['normal'],stamp,reloading=True)
   self.assertIn('记录继续',result['status'])
  self.feed('death',.48);self.assertIsNone(self.feed('death',.56)['event'])
  self.feed('normal',.64);self.feed('normal',.72)
  self.feed('death',.80);self.assertEqual(self.feed('death',.88)['event'],'death')
if __name__=='__main__':unittest.main()
