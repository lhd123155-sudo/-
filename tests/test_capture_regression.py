import unittest,tempfile,json,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from auto_capture import Detector,save_profile,DeathCounter
from analytics_data import Repository

class CaptureRegression(unittest.TestCase):
    def setUp(self):
        rng=np.random.default_rng(42)
        self.player=rng.integers(0,256,(18,14,3),dtype=np.uint8)
        self.death=rng.integers(0,256,(15,40,3),dtype=np.uint8)
        self.live=np.full((160,220,3),50,dtype=np.uint8);self.live[80:98,90:104]=self.player
        self.dead=np.full_like(self.live,50);self.dead[10:25,20:60]=self.death
    def detector(self):return Detector(self.player,self.death,(20,10,40,15),(220,160))
    def test_count_when_mapping_is_lost(self):
        class Lost:
            def locate(self,*args):return None
        d=self.detector();d.mapper=Lost()
        d.process(self.live,0);d.process(self.live,.5)
        result=d.process(self.dead,.6)
        self.assertTrue(result['death']);self.assertIsNone(result['world_point'])
        self.assertFalse(d.process(self.dead,1).get('death'))
    def test_mirrored_character(self):
        f=self.live.copy();f[80:98,90:104]=self.player[:,::-1]
        d=self.detector();d.process(f,0);result=d.process(f,.5)
        self.assertIsNotNone(result.get('point'))
    def test_viewport_excludes_side_panel(self):
        d=self.detector();d.viewport=(10,5,220,160);d.capture_size=(300,180)
        canvas=np.zeros((180,300,3),dtype=np.uint8);canvas[5:165,10:230]=self.live
        d.process(canvas,0);self.assertIsNotNone(d.process(canvas,.5).get('point'))
        self.assertIn('变化',d.process(canvas[:170],.6)['status'])
    def test_no_death_from_missing_sprite(self):
        d=self.detector();d.process(self.live,0);d.process(self.live,.5)
        self.assertFalse(d.process(np.full_like(self.live,50),.6).get('death'))
    def test_stale_point_is_not_saved(self):
        d=self.detector();d.process(self.live,0);d.process(self.live,.5)
        result=d.process(self.dead,3)
        self.assertTrue(result['death']);self.assertIsNone(result['world_point'])
    def test_old_database_migrates(self):
        import sqlite3
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            path=Path(tmp)/'old.db';db=sqlite3.connect(path)
            db.executescript('CREATE TABLE sessions(id TEXT PRIMARY KEY,player TEXT,game TEXT,level TEXT,started TEXT,seconds INTEGER,completed INTEGER,status TEXT,source TEXT); CREATE TABLE events(id INTEGER PRIMARY KEY,session TEXT,elapsed INTEGER,type TEXT,x REAL,y REAL);');db.close()
            repo=Repository(path)
            try:
                sid=repo.start('P','I Wanna Maker','1-2','自动画面识别','map')
                repo.event(sid,1,'死亡',world_point=(12,34))
                self.assertEqual(repo.events(sid)[0]['world_x'],12)
            finally:repo.db.close()

class DeathCycleRegression(unittest.TestCase):
    def ready(self):
        c=DeathCounter();c.update(0,True,0);c.update(0,True,.08);return c
    def test_clear_short_death_is_counted_in_one_frame(self):
        c=self.ready();self.assertTrue(c.update(.99,False,.16))
        self.assertFalse(c.update(.99,False,.24))
    def test_fast_respawn_and_second_death(self):
        c=self.ready();self.assertTrue(c.update(.99,False,.16))
        c.update(0,True,.24);c.update(0,True,.32)
        self.assertTrue(c.update(.99,False,.40))
    def test_single_clear_respawn_frame_allows_next_fast_death(self):
        c=self.ready();self.assertTrue(c.update(.99,False,.16))
        c.update(0,True,.24,strong_alive=True)
        self.assertTrue(c.update(.99,False,.32))
    def test_single_noisy_match_is_not_death(self):
        c=self.ready();self.assertFalse(c.update(.90,False,.16))
        self.assertFalse(c.update(0,True,.24))
    def test_medium_match_needs_two_observations(self):
        c=self.ready();self.assertFalse(c.update(.91,False,.16))
        self.assertTrue(c.update(.91,False,.24))
    def test_fading_overlay_does_not_rearm(self):
        c=self.ready();self.assertTrue(c.update(.99,False,.16))
        c.update(.85,True,.24);c.update(.85,True,.40)
        self.assertFalse(c.update(.99,False,.48))
    def test_capture_pause_keeps_counted_death_latched(self):
        c=self.ready();self.assertTrue(c.update(.99,False,.16));c.pause()
        self.assertFalse(c.update(.99,False,4))
        c.update(0,True,4.1);c.update(0,True,4.2)
        self.assertTrue(c.update(.99,False,4.3))
    def test_sampling_gap_does_not_confirm_noisy_match(self):
        c=self.ready();self.assertFalse(c.update(.90,False,.16))
        self.assertFalse(c.update(.90,False,2))
    def test_death_at_recording_start_is_not_counted(self):
        c=DeathCounter();self.assertFalse(c.update(.99,False,0))
        self.assertFalse(c.update(.99,False,.2))

if __name__=='__main__':unittest.main()
