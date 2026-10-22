from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import traceback

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt,QThread,Signal,QTimer,QFile,QIODevice,QStandardPaths,QUrl,QEvent
from PySide6.QtGui import QAction,QKeySequence,QIcon,QPixmap,QDesktopServices,QColor
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QSplitter,QLabel,
                              QPushButton,QComboBox,QSlider,QTableWidgetItem,QFileDialog,QMessageBox,QProgressBar,
                              QMenu,QDialog,QCheckBox,QAbstractItemView,QInputDialog)
from PySide6.QtMultimedia import QAudioSink,QAudioFormat,QMediaDevices

from transcora.core.engine import Cancelled
from transcora.core.toolchain import Toolchain
from . import __version__
from .model import Project,Slide,Clip,Title,uid,save_project,load_project,backup_project,atomic_json
from .render import Renderer,preview_pair,pil_to_qimage
from .video import VIDEO_EXTENSIONS,inspect_video
from .audio import audio_duration,mix_audio,pcm16,RATE
from .export import export_project
from .dialogs import PropertiesDialog,ProjectDialog,ExportDialog
from .titles import TitleEditor
from .widgets import STYLE,Preview,Meter,TrackTable,TrackHeader

TRACKS=['slides','overlays','audio1','audio2']
AUDIO_EXTENSIONS={'.wav','.aif','.aiff','.flac','.mp3','.aac','.m4a','.alac','.ogg','.opus','.wma','.mka'}
IMAGE_EXTENSIONS={'.jpg','.jpeg','.jps','.png','.pns','.tif','.tiff','.bmp','.webp','.mpo','.heic','.heif'}


def timestamp(seconds):
    seconds=max(0,float(seconds));minutes,seconds=divmod(seconds,60);hours,minutes=divmod(int(minutes),60)
    return f'{hours:02d}:{minutes:02d}:{seconds:06.3f}'


class Task(QThread):
    progress=Signal(float);done=Signal(object);failed=Signal(str)
    def __init__(self,function,parent=None):
        super().__init__(parent);self.function=function;self.cancel=threading.Event()
    def run(self):
        try:self.done.emit(self.function(self.cancel,self.progress.emit))
        except Cancelled:self.failed.emit('CANCELLED')
        except Exception as error:
            traceback.print_exc();self.failed.emit(str(error))


class PreviewThread(QThread):
    picture=Signal(object,int);failed=Signal(str,int)
    def __init__(self,parent=None):
        super().__init__(parent);self.condition=threading.Condition();self.pending=None;self.stopping=False
    def request(self,project,revision,seconds,mode):
        with self.condition:self.pending=(project,revision,seconds,mode);self.condition.notify()
    def close(self):
        with self.condition:self.stopping=True;self.condition.notify()
    def run(self):
        renderer=None;current=None
        try:
            while True:
                with self.condition:
                    while self.pending is None and not self.stopping:self.condition.wait()
                    if self.stopping:return
                    project,revision,seconds,mode=self.pending;self.pending=None
                try:
                    if current!=revision:
                        if renderer:renderer.close()
                        width=min(960,project.width);height=max(1,round(width*project.height/project.width))
                        renderer=Renderer(project,(width,height));current=revision
                    self.picture.emit(pil_to_qimage(preview_pair(renderer.frame(seconds),mode)),revision)
                except Exception as error:self.failed.emit(str(error),revision)
        finally:
            if renderer:renderer.close()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__();self.project=Project();self.path=None;self.dirty=False;self.revision=0
        self.history=[];self.future=[];self.rows=[];self.task=None;self.playing=False;self.position=0.;self.sink=None;self.audio_file=None;self.audio_map=None
        self.mix_revision=-1;self.play_base=0.;self.play_started=0.;self.fullscreen=None
        self.temp=tempfile.TemporaryDirectory(prefix='diadoris-preview-')
        self.configdir=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation));self.configdir.mkdir(parents=True,exist_ok=True)
        self.recovery=self.configdir/'recovery.dido';self.settings_path=self.configdir/'settings.json'
        try:self.settings=json.loads(self.settings_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.settings={}
        self.language=self.settings.get('language','de');self.input_dir=self.settings.get('input_dir','');self.output_dir=self.settings.get('output_dir','')
        self.setStyleSheet(STYLE);self.resize(1480,980);self.setMinimumSize(980,680)
        self.preview_worker=PreviewThread(self);self.preview_worker.picture.connect(self.show_picture);self.preview_worker.failed.connect(self.preview_error);self.preview_worker.start()
        self.timer=QTimer(self);self.timer.setInterval(33);self.timer.timeout.connect(self.tick)
        self.autosave=QTimer(self);self.autosave.setInterval(30000);self.autosave.timeout.connect(self.recover_save);self.autosave.start()
        self.build_ui();self.refresh()
        QTimer.singleShot(0,self.offer_recovery)
    def tr(self,de,en=None):return de if self.language=='de' else en or de
    def action(self,menu,de,en,shortcut,callback):
        a=QAction(self.tr(de,en),self)
        if shortcut:a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(callback);menu.addAction(a);self.menu_actions.append(a);return a
    def build_ui(self):
        self.menuBar().clear()
        for a in getattr(self,'menu_actions',[]):a.deleteLater()
        self.menu_actions=[];bar=self.menuBar();file=bar.addMenu(self.tr('Projekt','Project'))
        self.action(file,'Neu','New','Ctrl+N',self.new_project);self.action(file,'Öffnen …','Open …','Ctrl+O',self.open_project)
        self.action(file,'Speichern','Save','Ctrl+S',self.save);self.action(file,'Speichern unter …','Save as …','Ctrl+Shift+S',lambda:self.save(True))
        self.action(file,'ZIP-Sicherung …','ZIP backup …','Ctrl+Shift+B',self.backup)
        file.addSeparator();self.action(file,'Projekteinstellungen …','Project settings …',None,self.project_settings)
        self.action(file,'Fehlende Dateien zuordnen …','Relink missing files …',None,self.relink)
        self.action(file,'Dateizuordnung einrichten …','Set up file association …',None,self.file_association)
        edit=bar.addMenu(self.tr('Bearbeiten','Edit'));self.action(edit,'Rückgängig','Undo','Ctrl+Z',self.undo);self.action(edit,'Wiederholen','Redo','Ctrl+Y',self.redo)
        insert=bar.addMenu(self.tr('Einfügen','Insert'));self.action(insert,'Dateien …','Files …','Ctrl+I',self.add_files)
        self.action(insert,'Titel …','Title …','Ctrl+Shift+T',self.add_title);self.action(insert,'Schwarzbild','Black image',None,self.add_black)
        self.action(insert,'L/R-Bildpaar …','L/R image pair …',None,self.add_pair)
        view=bar.addMenu(self.tr('Ansicht','View'));self.action(view,'Vollbild','Fullscreen','F11',self.toggle_fullscreen)
        self.action(view,'Safe Area','Safe area','Ctrl+Shift+H',self.toggle_safe)
        self.action(view,'Raster durchschalten','Cycle grid',None,self.cycle_grid)
        helpmenu=bar.addMenu(self.tr('Hilfe','Help'));self.action(helpmenu,'Tastaturbefehle','Keyboard shortcuts','F1',self.help)
        self.action(helpmenu,'Über DiaDoris','About DiaDoris',None,lambda:QMessageBox.information(self,'DiaDoris',f'DiaDoris {__version__}\n'+self.tr('Erste Testversion · Python / Qt / FFmpeg','First test version · Python / Qt / FFmpeg')))
        root=QWidget();self.setCentralWidget(root);outer=QVBoxLayout(root);outer.setContentsMargins(14,12,14,12);outer.setSpacing(10)
        header=QHBoxLayout();outer.addLayout(header)
        brand=QLabel('DiaDoris');brand.setStyleSheet('color:#c6a95e;font-size:25px;font-weight:600;');header.addWidget(brand)
        self.info=QLabel();self.info.setProperty('muted',True);header.addWidget(self.info);header.addStretch()
        self.language_box=QComboBox();self.language_box.addItems(['Deutsch','English']);self.language_box.setCurrentIndex(0 if self.language=='de' else 1);self.language_box.currentIndexChanged.connect(self.switch_language);header.addWidget(self.language_box)
        split=QSplitter(Qt.Orientation.Vertical);outer.addWidget(split,1)
        upper=QWidget();uv=QVBoxLayout(upper);uv.setContentsMargins(0,0,0,0)
        previewrow=QHBoxLayout();uv.addLayout(previewrow,1);self.preview=Preview();self.preview.toggle_play.connect(self.toggle_play);previewrow.addWidget(self.preview,1)
        self.meter=Meter();self.meter.reference=self.preview;previewrow.addWidget(self.meter)
        controls=QHBoxLayout();uv.addLayout(controls)
        self.play=QPushButton(self.tr('Wiedergabe','Play'));self.play.clicked.connect(self.toggle_play);controls.addWidget(self.play)
        self.time=QLabel();self.time.setMinimumWidth(215);controls.addWidget(self.time)
        self.seek=QSlider(Qt.Orientation.Horizontal);self.seek.setRange(0,100000);self.seek.sliderPressed.connect(self.stop);self.seek.sliderMoved.connect(self.seek_to);self.seek.sliderReleased.connect(self.seek_to);controls.addWidget(self.seek,1)
        self.mode=QComboBox()
        for key,text in [('anaglyph','Anaglyph'),('parallel',self.tr('Parallelblick','Parallel view')),('cross',self.tr('Kreuzblick','Cross view')),('left',self.tr('Linkes Bild','Left eye'))]:self.mode.addItem(text,key)
        self.mode.currentIndexChanged.connect(self.request_preview);controls.addWidget(self.mode)
        split.addWidget(upper)
        lower=QWidget();lv=QVBoxLayout(lower);lv.setContentsMargins(0,0,0,0)
        tools=QHBoxLayout();lv.addLayout(tools)
        self.active=QComboBox();self.active.addItems([self.tr('Spur 1','Track 1'),self.tr('Spur 2','Track 2'),'Audio 1','Audio 2']);tools.addWidget(self.active)
        for de,en,fn in [('Dateien hinzufügen','Add files',self.add_files),('Titel','Title',self.add_title),('Schwarzbild','Black image',self.add_black),('Eigenschaften','Properties',self.properties)]:
            b=QPushButton(self.tr(de,en));b.clicked.connect(fn);tools.addWidget(b)
        tools.addStretch();hb=QPushButton(self.tr('Tastaturbefehle · F1','Keyboard shortcuts · F1'));hb.clicked.connect(self.help);tools.addWidget(hb)
        self.table=TrackTable();self.table.setColumnCount(13)
        labels=[self.tr('Bild / Video','Image / video'),self.tr('Dauer','Duration'),self.tr('Übergang','Transition'),
                self.tr('Titel / Bild','Title / image'),self.tr('Versatz','Offset'),self.tr('Dauer','Duration'),
                self.tr('Datei','File'),self.tr('Versatz','Offset'),self.tr('Dauer','Duration'),
                self.tr('Datei','File'),self.tr('Versatz','Offset'),self.tr('Dauer','Duration'),self.tr('Anfang','Start')]
        groups=[(0,2,self.tr('Spur 1 · Hauptbilder und Videos','Track 1 · Images and videos')),(3,5,self.tr('Spur 2 · Titel und Überlagerungen','Track 2 · Titles and overlays')),(6,8,'Audio 1'),(9,11,'Audio 2'),(12,12,self.tr('Zeit','Time'))]
        self.table.setHorizontalHeader(TrackHeader(labels,groups,self.table));self.table.setHorizontalHeaderLabels(labels)
        for col,width in enumerate([245,80,116,205,75,75,180,75,75,180,75,75,125]):self.table.setColumnWidth(col,width)
        self.table.setIconSize(__import__('PySide6.QtCore',fromlist=['QSize']).QSize(96,64))
        self.table.currentCellChanged.connect(self.cell_selected);self.table.cellDoubleClicked.connect(self.double_click)
        self.table.customContextMenuRequested.connect(self.context_menu);self.table.files_dropped.connect(self.dropped);self.table.moved.connect(self.move_entry)
        lv.addWidget(self.table,1);split.addWidget(lower);split.setSizes([480,360])
        bottom=QHBoxLayout();outer.addLayout(bottom)
        self.status=QLabel(self.tr('Bereit','Ready'));self.status.setWordWrap(True);bottom.addWidget(self.status,1)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setFixedWidth(220);self.progress.hide();bottom.addWidget(self.progress)
        self.cancel=QPushButton(self.tr('Abbrechen','Cancel'));self.cancel.clicked.connect(self.cancel_task);self.cancel.hide();bottom.addWidget(self.cancel)
        self.export_button=QPushButton(self.tr('Video exportieren …','Export video …'));self.export_button.setProperty('primary',True);self.export_button.clicked.connect(self.export);bottom.addWidget(self.export_button)
        self.root=root
    def switch_language(self,index):
        self.stop();self.language='de' if index==0 else 'en';self.build_ui();self.refresh();self.persist_settings()
    def persist_settings(self):
        atomic_json(self.settings_path,{'language':self.language,'input_dir':self.input_dir,'output_dir':self.output_dir})
    def remember(self):
        self.stop();self.history.append(self.project.to_dict());self.history=self.history[-50:];self.future.clear()
    def changed(self):
        self.revision+=1;self.dirty=True;self.mix_revision=-1;self.position=min(self.position,self.project.duration);self.refresh()
    def undo(self):
        if not self.history:return
        self.stop();self.future.append(self.project.to_dict());self.project=Project.from_dict(self.history.pop());self.changed()
    def redo(self):
        if not self.future:return
        self.stop();self.history.append(self.project.to_dict());self.project=Project.from_dict(self.future.pop());self.changed()
    def group_for_column(self,col):return min(3,max(0,col)//3)
    def selected_objects(self):
        group=self.active.currentIndex();track=TRACKS[group];keys=set()
        for item in self.table.selectedItems():
            if self.group_for_column(item.column())==group:
                key=item.data(Qt.ItemDataRole.UserRole)
                if key:keys.add(key)
        return track,[o for o in getattr(self.project,track) if o.id in keys]
    def anchor(self,row=None):
        row=self.table.currentRow() if row is None else row
        if 0<=row<len(self.rows):return self.rows[row][0]
        return self.project.slides[-1].id if self.project.slides else ''
    def refresh(self):
        if not hasattr(self,'table'):return
        self.info.setText(f'{len(self.project.slides)} '+self.tr('Einträge','entries')+f' · {timestamp(self.project.duration)} · {self.project.width} × {self.project.height} / '+self.tr('Auge','eye'))
        self.setWindowTitle(f'DiaDoris {__version__} · '+(self.path.name if self.path else self.tr('Neues Projekt','New project'))+(' *' if self.dirty else ''))
        self.time.setText(f'{timestamp(self.position)} / {timestamp(self.project.duration)}')
        self.table.blockSignals(True);self.table.setRowCount(0);self.rows=[];starts=self.project.starts()
        thumb=Renderer(self.project,(96,54))
        try:
            for index,slide in enumerate(self.project.slides):
                clips=[[c for c in getattr(self.project,t) if c.anchor==slide.id] for t in TRACKS[1:]]
                n=max(1,*(len(c) for c in clips))
                for sub in range(n):
                    row=self.table.rowCount();self.table.insertRow(row);self.table.setRowHeight(row,82 if sub==0 else 46);self.rows.append((slide.id,sub))
                    def item(col,text,key='',icon=None):
                        cell=QTableWidgetItem(text);cell.setData(Qt.ItemDataRole.UserRole,key);cell.setToolTip(text)
                        if icon:cell.setIcon(icon)
                        self.table.setItem(row,col,cell)
                    if sub==0:
                        icon=None
                        try:
                            picture=thumb.slide(slide,max(.01,min(slide.duration/2,1)))[0]
                            icon=QIcon(QPixmap.fromImage(pil_to_qimage(picture)))
                        except Exception:pass
                        item(0,f'{index+1:02d} · '+slide.name,slide.id,icon);item(1,f'{slide.duration:g} s',slide.id)
                        transition=self.tr('Schnitt','Cut') if slide.kind=='video' or (index+1<len(self.project.slides) and self.project.slides[index+1].kind=='video') else {'fade':self.tr('Blende','Fade'),'black':self.tr('Schwarz','Black'),'cut':self.tr('Schnitt','Cut')}[slide.transition]
                        item(2,transition+(f' · {slide.transition_duration:g} s' if transition not in {self.tr('Schnitt','Cut')} else ''),slide.id)
                        item(12,timestamp(starts[slide.id]),slide.id)
                    for group,entries in enumerate(clips,1):
                        col=group*3
                        if sub<len(entries):
                            c=entries[sub];icon=None
                            if group==1:
                                try:
                                    if c.title:picture=thumb.title(c.title)[0].convert('RGB')
                                    else:
                                        from .render import fit_image
                                        picture=fit_image(thumb.pair(c.resource)[0],(96,54)).convert('RGB')
                                    icon=QIcon(QPixmap.fromImage(pil_to_qimage(picture)))
                                except Exception:pass
                            item(col,c.name,c.id,icon);item(col+1,f'{c.offset:+g} s',c.id);item(col+2,f'{c.duration:g} s',c.id)
                        elif sub==0:
                            # Visual continuation only; the original item retains its identity.
                            previous=[c for c in getattr(self.project,TRACKS[group]) if starts[c.anchor]<starts[slide.id] and self.project.clip_window(c)[1]>starts[slide.id]]
                            if previous:item(col,self.tr('↳ Fortsetzung: ','↳ Continues: ')+', '.join(c.name for c in previous))
            row=self.table.rowCount();self.table.insertRow(row);self.table.setRowHeight(row,70)
            for col in (0,3):
                plus=QTableWidgetItem('＋ '+self.tr('Hinzufügen','Add'));plus.setForeground(QColor('#c6a95e'));self.table.setItem(row,col,plus)
        finally:thumb.close()
        self.table.blockSignals(False);self.request_preview()
    def cell_selected(self,row,col,*args):
        if col<12:self.active.setCurrentIndex(self.group_for_column(col))
        if 0<=row<len(self.rows) and not self.playing:
            self.position=self.project.starts()[self.rows[row][0]];self.request_preview()
    def double_click(self,row,col):
        if row>=len(self.rows):self.active.setCurrentIndex(self.group_for_column(col));self.add_files();return
        self.properties(field='duration' if col==1 else 'transition' if col==2 else None)
    def request_preview(self,*args):
        if not hasattr(self,'mode'):return
        self.preview_worker.request(copy.deepcopy(self.project),self.revision,self.position,self.mode.currentData())
        self.time.setText(f'{timestamp(self.position)} / {timestamp(self.project.duration)}')
        if not self.seek.isSliderDown():self.seek.setValue(round(self.position/max(.001,self.project.duration)*100000))
    def show_picture(self,image,revision):
        if revision!=self.revision:return
        self.preview.set_image(image)
        self.preview.stereo_mode=self.mode.currentData()
        rect=self.preview.picture_rect();self.meter.bounds=(rect.top(),rect.bottom());self.meter.update()
        self.meter.setVisible(True)
        if self.fullscreen:self.fullscreen.set_image(image)
    def preview_error(self,error,revision):
        if revision==self.revision:self.status.setText(self.tr('Vorschau: ','Preview: ')+error);self.stop()
    def add_files(self,checked=False,paths=None,group=None,row=None):
        group=self.active.currentIndex() if group is None else group
        if paths is None:
            filt='Audio (*.wav *.aif *.aiff *.flac *.mp3 *.aac *.m4a *.alac *.ogg *.opus *.wma *.mka)' if group>=2 else 'Images / video (*.jpg *.jpeg *.jps *.png *.pns *.tif *.tiff *.bmp *.webp *.mpo *.heic *.heif *.mp4 *.mkv *.mov *.avi *.m4v *.mts *.m2ts *.webm *.wmv *.mpg *.mpeg)'
            paths,_=QFileDialog.getOpenFileNames(self,self.tr('Dateien hinzufügen','Add files'),self.input_dir,filt)
        if not paths:return
        self.input_dir=str(Path(paths[0]).parent);self.persist_settings()
        if group and not self.project.slides:QMessageBox.information(self,'DiaDoris',self.tr('Zuerst einen Eintrag in Spur 1 hinzufügen.','Add an entry to Track 1 first.'));return
        self.remember();project=copy.deepcopy(self.project);anchor=self.anchor(row)
        insertion=next((i for i,s in enumerate(project.slides) if s.id==anchor),len(project.slides)) if row is not None and 0<=row<len(self.rows) else len(project.slides)
        def import_files(cancel,progress):
            failures=[];added=[]
            for i,path in enumerate(paths):
                if cancel.is_set():raise Cancelled()
                try:
                    suffix=Path(path).suffix.lower()
                    if group>=2:
                        duration,channels=audio_duration(path);r=project.add_resource(path,'audio')
                        c=Clip(anchor=anchor,kind='audio',resource=r.id,name=Path(path).name,fade_in=0,fade_out=0,hold=duration)
                        getattr(project,TRACKS[group]).append(c);added.append(c.id)
                    elif suffix in VIDEO_EXTENSIONS:
                        if group!=0:raise ValueError(self.tr('Videos bitte in Spur 1 einfügen.','Insert videos into Track 1.'))
                        info=inspect_video(path);r=project.add_resource(path,'video');r.info=info
                        s=Slide(name=Path(path).name,kind='video',resource=r.id,duration=info['duration'],transition='cut');project.slides.insert(insertion+len(added),s);added.append(s.id)
                    elif suffix in IMAGE_EXTENSIONS:
                        r=project.add_resource(path)
                        test=Renderer(project,(96,54));test.pair(r.id);test.close()
                        if group==0:
                            s=Slide(name=Path(path).name,resource=r.id,duration=project.default_duration,transition_duration=project.default_transition)
                            project.slides.insert(insertion+len(added),s);added.append(s.id)
                        else:
                            c=Clip(anchor=anchor,kind='image',resource=r.id,name=Path(path).name);project.overlays.append(c);added.append(c.id)
                    else:raise ValueError(self.tr('Nicht unterstützte Dateiendung','Unsupported extension'))
                except Exception as error:failures.append(Path(path).name+': '+str(error))
                progress((i+1)/len(paths)*100)
            return project,failures,added
        def done(result):
            self.project,failures,added=result;self.changed()
            if failures:QMessageBox.warning(self,'DiaDoris','\n'.join(failures))
        self.start_task(import_files,done,self.tr('Dateien prüfen …','Inspecting files …'))
    def add_pair(self):
        group=self.active.currentIndex()
        if group>=2:return
        if group==1 and not self.project.slides:return
        left,_=QFileDialog.getOpenFileName(self,self.tr('Linkes Halbbild auswählen','Choose left half-image'),self.input_dir)
        if not left:return
        right,_=QFileDialog.getOpenFileName(self,self.tr('Rechtes Halbbild auswählen','Choose right half-image'),str(Path(left).parent))
        if not right:return
        draft=copy.deepcopy(self.project);r=draft.add_resource(left);r.right=str(Path(right).resolve());anchor=self.anchor()
        def prepare(cancel,progress):
            renderer=Renderer(draft,(96,54))
            try:renderer.pair(r.id)
            finally:renderer.close()
            if group==0:draft.slides.append(Slide(name=Path(left).stem+' / '+Path(right).stem,resource=r.id,duration=draft.default_duration,transition_duration=draft.default_transition))
            else:draft.overlays.append(Clip(anchor=anchor,kind='image',resource=r.id,name=Path(left).stem+' / '+Path(right).stem))
            return draft
        self.remember()
        self.start_task(prepare,lambda p:(setattr(self,'project',p),self.changed()),self.tr('Bildpaar prüfen …','Inspecting image pair …'))
    def dropped(self,paths,col,row):self.add_files(paths=paths,group=self.group_for_column(col),row=row)
    def add_black(self):
        self.remember();s=Slide(name=self.tr('Schwarzbild','Black image'),kind='black',duration=self.project.default_duration,transition_duration=self.project.default_transition)
        index=next((i+1 for i,v in enumerate(self.project.slides) if v.id==self.anchor()),len(self.project.slides));self.project.slides.insert(index,s);self.changed()
    def add_title(self):
        track='slides' if self.active.currentIndex()==0 else 'overlays'
        if track=='overlays' and not self.project.slides:QMessageBox.information(self,'DiaDoris',self.tr('Zuerst Spur 1 anlegen.','Create Track 1 first.'));return
        draft=copy.deepcopy(self.project);title=Title(background='gradient' if track=='slides' else 'transparent')
        if TitleEditor(draft,title,self.tr,self).exec()!=QDialog.DialogCode.Accepted:return
        self.remember();self.project=draft
        if track=='slides':self.project.slides.append(Slide(name=self.tr('Titelseite','Title page'),kind='title',title=title,duration=self.project.default_duration,transition_duration=self.project.default_transition))
        else:self.project.overlays.append(Clip(anchor=self.anchor(),name=self.tr('Titel','Title'),title=title))
        self.changed()
    def properties(self,checked=False,field=None):
        track,objects=self.selected_objects()
        if not objects:return
        draft=copy.deepcopy(self.project);selected=[o for o in getattr(draft,track) if o.id in {v.id for v in objects}]
        if field is None and len(selected)==1 and selected[0].title:
            if TitleEditor(draft,selected[0].title,self.tr,self).exec()!=QDialog.DialogCode.Accepted:return
        elif PropertiesDialog(draft,selected,track,self.tr,self,field).exec()!=QDialog.DialogCode.Accepted:return
        self.remember();self.project=draft;self.changed()
    def timings(self):
        track,objects=self.selected_objects()
        if not objects:return
        draft=copy.deepcopy(self.project);selected=[o for o in getattr(draft,track) if o.id in {v.id for v in objects}]
        if PropertiesDialog(draft,selected,track,self.tr,self).exec()==QDialog.DialogCode.Accepted:self.remember();self.project=draft;self.changed()
    def remove(self):
        track,objects=self.selected_objects()
        if not objects:return
        keys={o.id for o in objects}
        linked=[c for t in TRACKS[1:] for c in getattr(self.project,t) if c.anchor in keys] if track=='slides' else []
        if linked and QMessageBox.question(self,'DiaDoris',self.tr(f'{len(linked)} verankerte Titel/Audioclips ebenfalls entfernen?',f'Also remove {len(linked)} anchored title/audio clips?'))!=QMessageBox.StandardButton.Yes:return
        self.remember();getattr(self.project,track)[:]=[o for o in getattr(self.project,track) if o.id not in keys]
        if track=='slides':
            for t in TRACKS[1:]:getattr(self.project,t)[:]=[c for c in getattr(self.project,t) if c.anchor not in keys]
        self.changed()
    def duplicate(self):
        track,objects=self.selected_objects()
        if not objects:return
        self.remember();entries=getattr(self.project,track)
        for o in reversed(objects):
            duplicate=copy.deepcopy(o);duplicate.id=uid();entries.insert(entries.index(o)+1,duplicate)
        self.changed()
    def move_entry(self,key,col,row):
        target_anchor=self.anchor(row)
        for track in TRACKS:
            entries=getattr(self.project,track);obj=next((o for o in entries if o.id==key),None)
            if obj:
                if TRACKS[self.group_for_column(col)]!=track:return
                self.remember()
                if track=='slides':
                    target=next((i for i,s in enumerate(entries) if s.id==target_anchor),len(entries)) if 0<=row<len(self.rows) else len(entries)
                    old=entries.index(obj);entries.remove(obj);entries.insert(target-(old<target),obj)
                else:obj.anchor=target_anchor
                self.changed();return
    def move_selected(self,direction):
        track,objects=self.selected_objects()
        if not objects:return
        self.remember();entries=getattr(self.project,track)
        for o in (objects if direction<0 else objects[::-1]):
            i=entries.index(o);j=max(0,min(len(entries)-1,i+direction));entries.insert(j,entries.pop(i))
        self.changed()
    def context_menu(self,pos):
        menu=QMenu(self);track,objects=self.selected_objects()
        menu.addAction(self.tr('Dateien hinzufügen …','Add files …'),self.add_files)
        if self.active.currentIndex()<2:menu.addAction(self.tr('Titel hinzufügen …','Add title …'),self.add_title)
        if track=='slides':menu.addAction(self.tr('Schwarzbild danach einfügen','Insert black image after'),self.add_black)
        if objects:
            menu.addSeparator();menu.addAction(self.tr('Eigenschaften …','Properties …'),self.properties)
            menu.addAction(self.tr('Bilddauer und Übergang …','Duration and transition …') if track=='slides' else self.tr('Zeiten und Blenden …','Timing and fades …'),self.timings)
            menu.addAction(self.tr('Duplizieren','Duplicate'),self.duplicate);menu.addAction(self.tr('Entfernen','Remove'),self.remove)
            if track=='slides':menu.addAction(self.tr('Als Vorgabe für neue Bilder übernehmen','Use as defaults for new images'),self.use_defaults)
            if len(objects)==1 and objects[0].resource:
                menu.addAction(self.tr('Datei ersetzen …','Replace file …'),self.replace_resource)
                menu.addAction(self.tr('Im Ordner anzeigen','Show in folder'),self.reveal)
        menu.exec(self.table.viewport().mapToGlobal(pos))
    def use_defaults(self):
        _,objects=self.selected_objects()
        if not objects:return
        self.remember();self.project.default_duration=objects[0].duration;self.project.default_transition=objects[0].transition_duration;self.changed()
    def replace_resource(self):
        _,objects=self.selected_objects()
        if not objects or not objects[0].resource:return
        path,_=QFileDialog.getOpenFileName(self,self.tr('Datei ersetzen','Replace file'),self.input_dir)
        if not path:return
        try:
            old=self.project.resource(objects[0].resource);info=inspect_video(path) if old.kind=='video' else old.info
            self.remember();r=copy.deepcopy(old);r.id=uid();r.path=str(Path(path).resolve());r.info=info;self.project.resources.append(r);objects[0].resource=r.id
            if old.kind=='video':objects[0].source_in=0;objects[0].duration=info['duration']
            self.changed()
        except Exception as error:QMessageBox.warning(self,'DiaDoris',str(error))
    def reveal(self):
        _,objects=self.selected_objects()
        if objects and objects[0].resource:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.project.resource(objects[0].resource).path).parent)))
    def project_settings(self):
        draft=copy.deepcopy(self.project)
        if ProjectDialog(draft,self.tr,self).exec()==QDialog.DialogCode.Accepted:self.remember();self.project=draft;self.changed()
    def ensure_saved(self):
        self.stop()
        if not self.dirty:return True
        box=QMessageBox(self);box.setWindowTitle('DiaDoris');box.setText(self.tr('Änderungen speichern?','Save changes?'))
        box.setStandardButtons(QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Save).setText(self.tr('Speichern','Save'));box.button(QMessageBox.StandardButton.Discard).setText(self.tr('Nicht speichern','Do not save'));box.button(QMessageBox.StandardButton.Cancel).setText(self.tr('Abbrechen','Cancel'))
        answer=box.exec()
        return self.save() if answer==QMessageBox.StandardButton.Save else answer==QMessageBox.StandardButton.Discard
    def new_project(self):
        if not self.ensure_saved():return
        self.project=Project();self.path=None;self.history=[];self.future=[];self.position=0.;self.revision+=1;self.dirty=False;self.mix_revision=-1;self.recovery.unlink(missing_ok=True);self.refresh()
    def open_project(self,checked=False,path=None):
        if not self.ensure_saved():return
        if not path:path,_=QFileDialog.getOpenFileName(self,self.tr('Projekt öffnen','Open project'),self.input_dir,'DiaDoris (*.dido)')
        if not path:return
        try:
            self.project=load_project(path);self.path=Path(path);self.dirty=False;self.position=0;self.revision+=1;self.mix_revision=-1;self.history=[];self.future=[];self.refresh()
            if self.project.missing():self.relink()
        except Exception as error:QMessageBox.warning(self,'DiaDoris',str(error))
    def save(self,save_as=False):
        path=self.path
        if not path or save_as:
            chosen,_=QFileDialog.getSaveFileName(self,self.tr('Projekt speichern','Save project'),str(path or Path(self.input_dir or '.')/'DiaDoris.dido'),'DiaDoris (*.dido)')
            if not chosen:return False
            path=Path(chosen).with_suffix('.dido')
        try:
            save_project(self.project,path);self.path=path;self.dirty=False;self.recovery.unlink(missing_ok=True);self.refresh();return True
        except Exception as error:QMessageBox.warning(self,'DiaDoris',str(error));return False
    def backup(self):
        path,_=QFileDialog.getSaveFileName(self,self.tr('ZIP-Sicherung','ZIP backup'),str(Path(self.output_dir or '.')/'DiaDoris.zip'),'ZIP (*.zip)')
        if path:self.start_task(lambda cancel,progress:backup_project(copy.deepcopy(self.project),path),lambda _:self.status.setText(self.tr('ZIP-Sicherung gespeichert.','ZIP backup saved.')),self.tr('ZIP-Sicherung erstellen …','Creating ZIP backup …'))
    def recover_save(self):
        if self.dirty:
            try:save_project(self.project,self.recovery)
            except OSError:pass
    def offer_recovery(self):
        if self.recovery.exists() and not self.path:
            if QMessageBox.question(self,'DiaDoris',self.tr('Nicht gespeichertes Projekt wiederherstellen?','Recover unsaved project?'))==QMessageBox.StandardButton.Yes:
                try:self.project=load_project(self.recovery);self.changed()
                except Exception as error:QMessageBox.warning(self,'DiaDoris',str(error))
    def relink(self):
        missing=self.project.missing()
        if not missing:QMessageBox.information(self,'DiaDoris',self.tr('Alle Dateien sind verfügbar.','All files are available.'));return
        self.remember();modified=False
        for resource,attr in missing:
            path,_=QFileDialog.getOpenFileName(self,self.tr('Fehlende Datei zuordnen: ','Locate missing file: ')+Path(getattr(resource,attr)).name,self.input_dir)
            if not path:break
            setattr(resource,attr,str(Path(path).resolve()));modified=True
        if modified:self.changed()
    def start_task(self,function,done,label):
        if self.task:return
        self.stop();self.status.setText(label);self.progress.setValue(0);self.progress.show();self.cancel.show()
        self.table.setEnabled(False);self.export_button.setEnabled(False);self.language_box.setEnabled(False)
        self.menuBar().setEnabled(False)
        for b in self.root.findChildren(QPushButton):
            if b is not self.cancel:b.setEnabled(False)
        self.task=Task(function,self);task=self.task
        task.progress.connect(lambda p:self.progress.setValue(round(p)))
        task.done.connect(done);task.failed.connect(self.task_error)
        task.finished.connect(self.task_finished);task.start()
    def task_error(self,error):
        if error=='CANCELLED':self.status.setText(self.tr('Abgebrochen','Cancelled'))
        else:self.status.setText(error);QMessageBox.warning(self,'DiaDoris',error)
    def task_finished(self):
        old=self.task;self.task=None
        self.progress.hide();self.cancel.hide();self.table.setEnabled(True);self.export_button.setEnabled(True);self.language_box.setEnabled(True);self.menuBar().setEnabled(True)
        for b in self.root.findChildren(QPushButton):b.setEnabled(True)
        if old:old.deleteLater()
    def cancel_task(self):
        if self.task:self.task.cancel.set();self.status.setText(self.tr('Abbrechen …','Cancelling …'))
    def export(self):
        if not self.project.slides:return
        self.stop();dialog=ExportDialog(self.project,self.tr,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        settings=dialog.settings()
        path,_=QFileDialog.getSaveFileName(self,self.tr('Video exportieren','Export video'),str(Path(self.output_dir or '.')/('DiaDoris.'+settings.container)),f'{settings.container.upper()} (*.{settings.container})')
        if not path:return
        self.output_dir=str(Path(path).parent);self.persist_settings();draft=copy.deepcopy(self.project)
        self.start_task(lambda cancel,progress:export_project(draft,path,settings,cancel,progress),lambda log:self.status.setText(self.tr('Export fertig: ','Export complete: ')+str(path)),self.tr('Video exportieren …','Exporting video …'))
    def toggle_play(self):
        if self.task:return
        if self.playing:self.stop();return
        if not self.project.slides:return
        if self.position>=self.project.duration-.02:self.position=0.
        if self.mix_revision!=self.revision:
            draft=copy.deepcopy(self.project);revision=self.revision;folder=Path(self.temp.name)
            def prepare(cancel,progress):
                peak=mix_audio(draft,folder/'mix.f32',cancel,progress);pcm16(folder/'mix.f32',folder/'mix.s16');return revision
            def done(revision):
                self.mix_revision=revision;QTimer.singleShot(0,self.begin_play)
            self.start_task(prepare,done,self.tr('Tonvorschau vorbereiten …','Preparing audio preview …'));return
        self.begin_play()
    def begin_play(self):
        self.stop();folder=Path(self.temp.name)
        self.audio_map=np.memmap(folder/'mix.f32',dtype='<f4',mode='r').reshape(-1,2)
        fmt=QAudioFormat();fmt.setSampleRate(RATE);fmt.setChannelCount(2);fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        device=QMediaDevices.defaultAudioOutput()
        self.play_base=self.position;self.play_started=time.monotonic()
        if not device.isNull() and device.isFormatSupported(fmt):
            self.audio_file=QFile(str(folder/'mix.s16'));self.audio_file.open(QIODevice.OpenModeFlag.ReadOnly);self.audio_file.seek(round(self.position*RATE)*4)
            self.sink=QAudioSink(device,fmt,self);self.sink.start(self.audio_file)
        self.playing=True;self.timer.start();self.play.setText(self.tr('Pause','Pause'));self.status.setText(self.tr('Wiedergabe','Playing'))
    def tick(self):
        self.position=self.play_base+(self.sink.processedUSecs()/1e6 if self.sink else time.monotonic()-self.play_started)
        if self.position>=self.project.duration:self.position=self.project.duration;self.stop();self.request_preview();return
        if self.audio_map is not None:
            start=round(self.position*RATE);data=self.audio_map[start:min(start+RATE//30,len(self.audio_map))]
            if len(data):self.meter.set_levels(np.max(np.abs(data),axis=0))
        self.request_preview()
    def stop(self,*args):
        self.timer.stop();self.playing=False
        if self.sink:self.sink.stop();self.sink.deleteLater();self.sink=None
        if self.audio_file:self.audio_file.close();self.audio_file=None
        if self.audio_map is not None:self.audio_map._mmap.close();self.audio_map=None
        if hasattr(self,'play'):self.play.setText(self.tr('Wiedergabe','Play'))
    def seek_to(self,value=None):
        if value is None:value=self.seek.value()
        self.position=self.project.duration*value/100000;self.request_preview()
    def toggle_safe(self):
        self.preview.safe=not self.preview.safe;self.preview.update()
    def cycle_grid(self):
        grids=[0,3,4,6,9,12];self.preview.grid=grids[(grids.index(self.preview.grid)+1)%len(grids)];self.preview.update()
    def toggle_fullscreen(self):
        if self.fullscreen:self.fullscreen.close();self.fullscreen=None;return
        self.fullscreen=Preview();self.fullscreen.safe=self.preview.safe;self.fullscreen.set_image(self.preview.image);self.fullscreen.showFullScreen();self.fullscreen.installEventFilter(self)
        self.fullscreen.closed.connect(lambda:setattr(self,'fullscreen',None))
    def eventFilter(self,watched,event):
        if watched is self.fullscreen and event.type()==QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Escape,Qt.Key.Key_F11):self.toggle_fullscreen();return True
            if event.key()==Qt.Key.Key_Space:self.toggle_play();return True
        return super().eventFilter(watched,event)
    def keyPressEvent(self,event):
        if self.task:return
        key=event.key();mods=event.modifiers()
        if key==Qt.Key.Key_Space and not event.isAutoRepeat():self.toggle_play();return
        if key==Qt.Key.Key_Delete:self.remove();return
        if key in (Qt.Key.Key_Return,Qt.Key.Key_Enter):self.properties();return
        if key in (Qt.Key.Key_Up,Qt.Key.Key_Down) and mods&Qt.KeyboardModifier.AltModifier:self.move_selected(-1 if key==Qt.Key.Key_Up else 1);return
        if key in (Qt.Key.Key_PageUp,Qt.Key.Key_PageDown):
            row=max(0,min(len(self.rows)-1,self.table.currentRow()+(-1 if key==Qt.Key.Key_PageUp else 1)));self.table.setCurrentCell(row,max(0,self.table.currentColumn()));return
        if key==Qt.Key.Key_G and not event.isAutoRepeat():
            if mods&Qt.KeyboardModifier.ShiftModifier:self.preview.grid=0;self.preview.update()
            else:self.cycle_grid()
            return
        if event.matches(QKeySequence.StandardKey.SelectAll):
            group=self.active.currentIndex();self.table.clearSelection()
            for row in range(len(self.rows)):
                for col in range(group*3,group*3+3):
                    item=self.table.item(row,col)
                    if item:item.setSelected(True)
            return
        super().keyPressEvent(event)
    def help(self):
        text=self.tr(
            'PROJEKT\nStrg+N / Strg+O: Neu / Öffnen\nStrg+S / Strg+Umschalt+S: Speichern / Speichern unter\nStrg+Umschalt+B: ZIP-Sicherung\nStrg+Z / Strg+Y: Rückgängig / Wiederholen\n\nLISTE\nStrg+I: Dateien zur aktiven Spur hinzufügen\nStrg+Umschalt+T: Titel hinzufügen\nStrg+A: Aktive Spur markieren\nAlt+↑/↓: Auswahl umordnen\nBild auf / Bild ab: Vorheriger / nächster Eintrag\nEnter / Doppelklick: Eigenschaften\nEntf: Aus Projekt entfernen\nRechtsklick: Dauer, Übergänge, Zeiten und Blenden\n\nVORSCHAU\nLeertaste: Wiedergabe / Pause\nF11 / Esc: Vollbild / verlassen\nG / Umschalt+G: Raster durchschalten / aus\nStrg+Umschalt+H: Safe Area\nPegelanzeige: Sample-Peak in dBFS; Klick löscht Spitzen und Übersteuerungsanzeige.\n\nTITEL\nEigene F1-Hilfe im Titeleditor. Tiefenwirkung und Ebenenreihenfolge bewusst aufeinander abstimmen.',
            'PROJECT\nCtrl+N / Ctrl+O: New / Open\nCtrl+S / Ctrl+Shift+S: Save / Save as\nCtrl+Shift+B: ZIP backup\nCtrl+Z / Ctrl+Y: Undo / Redo\n\nLIST\nCtrl+I: Add files to active track\nCtrl+Shift+T: Add title\nCtrl+A: Select active track\nAlt+↑/↓: Reorder selection\nPage Up / Page Down: Previous / next entry\nEnter / double click: Properties\nDelete: Remove from project\nRight click: Duration, transitions, timing and fades\n\nPREVIEW\nSpace: Play / pause\nF11 / Esc: Fullscreen / leave\nG / Shift+G: Cycle grid / off\nCtrl+Shift+H: Safe area\nMeter: sample peak in dBFS; click resets held peaks and clip indicators.\n\nTITLE\nSeparate F1 help in the title editor. Arrange stereo depth and layer order deliberately.')
        QMessageBox.information(self,self.tr('Tastaturbefehle','Keyboard shortcuts'),text)
    def file_association(self):
        if os.name!='nt':QMessageBox.information(self,'DiaDoris',self.tr('Die Dateizuordnung ist hier für Windows vorgesehen.','This file association action is intended for Windows.'));return
        import winreg
        exe=str(Path(sys.executable).resolve())
        command=f'"{exe}" "%1"' if getattr(sys,'frozen',False) else f'"{exe}" "{Path(__file__).resolve().parents[1]/"run_diadoris.py"}" "%1"'
        for key,value in [(r'Software\Classes\.dido\OpenWithProgids\DiaDoris.Project',''),(r'Software\Classes\DiaDoris.Project','DiaDoris project'),(r'Software\Classes\DiaDoris.Project\shell\open\command',command)]:
            if 'OpenWithProgids' in key:
                parent,name=key.rsplit('\\',1)
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER,parent) as k:winreg.SetValueEx(k,name,0,winreg.REG_SZ,'')
            else:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER,key) as k:winreg.SetValueEx(k,'',0,winreg.REG_SZ,value)
        QDesktopServices.openUrl(QUrl('ms-settings:defaultapps'))
    def closeEvent(self,event):
        if self.task:
            self.cancel_task();event.ignore();return
        if not self.ensure_saved():event.ignore();return
        self.stop();self.preview_worker.close()
        if not self.preview_worker.wait(5000):event.ignore();return
        if self.fullscreen:self.fullscreen.close()
        self.recovery.unlink(missing_ok=True);self.persist_settings();self.temp.cleanup();event.accept()


def main():
    app=QApplication(sys.argv);app.setOrganizationName('StereoTools');app.setApplicationName('DiaDoris');app.setStyle('Fusion')
    if '--self-test' in sys.argv:
        report=Path(sys.argv[sys.argv.index('--self-test')+1])
        try:
            from transcora.core.engine import methods
            tools=Toolchain.find();capabilities=tools.inspect()
            p=Project(width=160,height=90,slides=[Slide(kind='title',title=Title(background='gradient'),duration=.1)])
            assert Renderer(p).frame(.05)[0].size==(160,90)
            with tempfile.TemporaryDirectory() as folder:
                file=Path(folder)/'test.dido';save_project(p,file);assert load_project(file).duration==.1
                from .export import ExportSettings
                export_project(p,Path(folder)/'test.mp4',ExportSettings(width=160,height=90,audio='none'))
            atomic_json(report,{'ok':True,'version':__version__,'methods':len(methods()),'ffmpeg':capabilities['version']});return 0
        except Exception:
            atomic_json(report,{'ok':False,'error':traceback.format_exc()});return 1
    window=MainWindow()
    if len(sys.argv)>1 and Path(sys.argv[1]).suffix.lower()=='.dido':window.open_project(path=sys.argv[1])
    window.show();return app.exec()
