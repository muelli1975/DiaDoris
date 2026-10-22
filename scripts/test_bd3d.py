"""Exercise the actual inherited TransCora ISO/M2TS path on Windows."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from diadoris.model import Project,Slide,Title,Element
from diadoris.export import export_project,ExportSettings


app=QApplication([])
p=Project(slides=[Slide(kind='title',title=Title(background='gradient',elements=[Element(text='DiaDoris',size=120)]),duration=.6)],start_fade=0,end_fade=0)
with tempfile.TemporaryDirectory() as folder:
    for container in ('m2ts','iso'):
        out=Path(folder)/('proof.'+container)
        export_project(p,out,ExportSettings(target='bd3d',container=container,fps='24000/1001',audio='none',bitrate=40))
        assert out.stat().st_size>0
        print(container,out.stat().st_size)
