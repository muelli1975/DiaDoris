import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import tempfile
from pathlib import Path
import unittest

from PySide6.QtCore import Qt,QStandardPaths
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog
from PIL import Image
from diadoris.app import MainWindow
from diadoris.model import Project,Slide,Title,Element,Clip
from diadoris.dialogs import PropertiesDialog,ExportDialog
from diadoris.titles import TitleEditor
from diadoris.widgets import Meter

APP=QApplication.instance() or QApplication([])
APP.setOrganizationName('DiaDorisTests');APP.setApplicationName('Tests')
QStandardPaths.setTestModeEnabled(True)
def tr(de,en=None):return de


class GuiTests(unittest.TestCase):
    def test_finished_background_task_restores_ready_state(self):
        window=MainWindow()
        try:
            results=[];window.start_task(lambda cancel,progress:42,results.append,'Working')
            for _ in range(40):
                QTest.qWait(25)
                if window.task is None:break
            self.assertEqual(results,[42]);self.assertIsNone(window.task)
            self.assertEqual(window.status.text(),window.tr('Bereit','Ready'));self.assertTrue(window.table.isEnabled())
        finally:window.dirty=False;window.close()
    def test_meter_calibration_is_dbfs(self):
        m=Meter();m.set_levels([.5,1.1])
        self.assertAlmostEqual(m.levels[0],-6.020599913,places=6)
        self.assertFalse(m.clip[0]);self.assertTrue(m.clip[1]);m.reset();self.assertEqual(m.clip,[False,False])
    def test_main_subcolumns_multiple_entries_and_language(self):
        window=MainWindow()
        try:
            a=Slide(name='One',kind='black');b=Slide(name='Two',kind='black')
            window.project=Project(slides=[a,b],overlays=[Clip(anchor=a.id,title=Title()),Clip(anchor=a.id,title=Title())])
            window.refresh();window.show();QTest.qWait(150)
            self.assertEqual(window.table.columnCount(),13);self.assertEqual(len(window.rows),3)
            self.assertEqual(window.rows[:2],[(a.id,0),(a.id,1)])
            window.language_box.setCurrentIndex(1);QTest.qWait(100)
            self.assertEqual(window.active.itemText(0),'Track 1')
        finally:
            window.dirty=False;window.close();QTest.qWait(50)
    def test_multi_edit_changes_only_explicit_field(self):
        a=Slide(kind='black',duration=8,transition_duration=.5);b=Slide(kind='black',duration=10,transition_duration=1)
        p=Project(slides=[a,b]);d=PropertiesDialog(p,[a,b],'slides',tr)
        box,flag,_=d.fields['duration'];flag.setChecked(True);box.setValue(6);d.accept()
        self.assertEqual([a.duration,b.duration],[6,6]);self.assertEqual([a.transition_duration,b.transition_duration],[.5,1])
    def test_resource_interpretation_is_independent_per_use(self):
        p=Project();r=p.add_resource('/nonexistent/photo.png');a=Slide(resource=r.id);b=copy.deepcopy(a);b.id='second';p.slides=[a,b]
        d=PropertiesDialog(p,[a],'slides',tr);d.fields['layout'][0].setCurrentIndex(1);d.accept()
        self.assertNotEqual(a.resource,b.resource);self.assertEqual(p.resource(a.resource).layout,'full_sbs');self.assertEqual(p.resource(b.resource).layout,'mono')
    def test_title_keyboard_uses_project_pixels_and_preserves_depth(self):
        p=Project();e=Element(text='Test',depth=-3);title=Title(elements=[e]);d=TitleEditor(p,title,tr)
        try:
            d.show();d.canvas.setFocus();QTest.qWait(30)
            x=e.x;y=e.y
            QTest.keyClick(d.canvas,Qt.Key.Key_Right);self.assertAlmostEqual(e.x-x,1/p.width)
            QTest.keyClick(d.canvas,Qt.Key.Key_Down,Qt.KeyboardModifier.ShiftModifier);self.assertAlmostEqual(e.y-y,5/p.height)
            QTest.keyClick(d.canvas,Qt.Key.Key_Left,Qt.KeyboardModifier.ControlModifier);self.assertAlmostEqual(e.x-x,-9/p.width)
            self.assertEqual(e.depth,-3)
            QTest.keyClick(d.canvas,Qt.Key.Key_G);self.assertEqual(d.grid.currentData(),3)
        finally:d.reject()
    def test_graphic_reciprocal_size_and_fit_both_eyes(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'logo.png';Image.new('RGBA',(2000,500),'white').save(path)
            p=Project();r=p.add_resource(path,'graphic');e=Element(kind='graphic',resource=r.id,depth=-20,shadow=False)
            d=TitleEditor(p,Title(elements=[e]),tr)
            try:
                before=e.scale
                QTest.keyClick(d.canvas,Qt.Key.Key_Up,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier)
                QTest.keyClick(d.canvas,Qt.Key.Key_Down,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier)
                self.assertAlmostEqual(e.scale,before)
                d.fit_graphic();x,y,w,h=d.renderer.element_rect(e)
                self.assertLessEqual(w+abs(e.depth)*p.width/1000,p.width*.8+.01)
                self.assertEqual(e.depth,-20)
            finally:d.reject()
    def test_export_presets_apply_all_settings(self):
        d=ExportDialog(Project(),tr)
        d.preset.setCurrentIndex(6);s=d.settings()
        self.assertEqual((s.target,s.container,s.audio,s.bitrate),('bd3d','iso','pcm',40))
        d.preset.setCurrentIndex(0);s=d.settings()
        self.assertEqual((s.target,s.container,s.audio,s.bitrate),('full_sbs','mp4','aac',20))


if __name__=='__main__':unittest.main()
