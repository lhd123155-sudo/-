import os,sys,gc,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication,QPushButton
from desktop_main import PlatformerApp,STYLE
class PlayerEntryRegression(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.app=QApplication.instance() or QApplication([]);cls.app.setStyleSheet(STYLE)
 def setUp(self):
  self.errors=[];self.old_hook=sys.excepthook;sys.excepthook=lambda *args:self.errors.append(args)
  self.window=PlatformerApp(':memory:');self.window.show();self.app.processEvents();gc.collect()
 def tearDown(self):
  self.window.close();self.app.processEvents();sys.excepthook=self.old_hook
 def test_click_actual_player_entry_repeatedly(self):
  for _ in range(3):
   entry=next(b for b in self.window.stack.widget(0).findChildren(QPushButton) if b.text().startswith('进入玩家端'))
   entry.click();self.app.processEvents()
   self.assertFalse(self.errors,repr(self.errors));self.assertEqual(self.window.stack.currentIndex(),1)
   self.window.refresh_workspace();self.window.refresh_review();self.window.refresh_growth()
   self.window.leave();self.assertEqual(self.window.stack.currentIndex(),0)
 def test_game_and_level_change_after_entering(self):
  self.window.enter_player();self.window.game.setCurrentText('Celeste（蔚蓝）');self.app.processEvents()
  self.assertFalse(self.errors,repr(self.errors));self.assertFalse(self.window.start.isEnabled())
  name=self.window.repo.add_level('Celeste（蔚蓝）','test-room');self.window.change_player_game();self.window.level.setCurrentText(name);self.app.processEvents()
  self.assertTrue(self.window.start.isEnabled());self.assertFalse(self.errors,repr(self.errors))
if __name__=='__main__':unittest.main()
