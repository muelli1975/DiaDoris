from __future__ import annotations

from dataclasses import asdict
from fractions import Fraction
import copy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QDialogButtonBox,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QComboBox,
                              QDoubleSpinBox,QSpinBox,QLineEdit,QCheckBox,QPushButton,QFileDialog,QMessageBox,QScrollArea,QWidget)
from .model import Slide,Title,Resource
from .export import ExportSettings,PRESETS


def number(value=0,minimum=0,maximum=1e10,step=.1,decimals=3):
    box=QDoubleSpinBox();box.setDecimals(decimals);box.setRange(minimum,maximum);box.setSingleStep(step);box.setValue(value)
    box.setKeyboardTracking(False);return box


def combo(values,current=None):
    box=QComboBox()
    for key,label in values:box.addItem(label,key)
    if current is not None:box.setCurrentIndex(max(0,box.findData(current)))
    return box


def buttons(dialog,layout,tr):
    box=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
    box.button(QDialogButtonBox.StandardButton.Ok).setText(tr('Übernehmen','Apply'))
    box.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('Abbrechen','Cancel'))
    box.accepted.connect(dialog.accept);box.rejected.connect(dialog.reject);layout.addWidget(box)


class ProjectDialog(QDialog):
    def __init__(self,project,tr,parent=None):
        super().__init__(parent);self.project=project;self.tr=tr
        self.setWindowTitle(tr('Projekteinstellungen','Project settings'));self.setMinimumWidth(430)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.width=QSpinBox();self.width.setRange(16,7680);self.width.setSingleStep(2);self.width.setValue(project.width)
        self.height=QSpinBox();self.height.setRange(16,4320);self.height.setSingleStep(2);self.height.setValue(project.height)
        form.addRow(tr('Breite je Halbbild','Width per eye'),self.width);form.addRow(tr('Höhe je Halbbild','Height per eye'),self.height)
        self.fps=combo([(x,x.replace('24000/1001','23,976').replace('30000/1001','29,97').replace('60000/1001','59,94')) for x in ['24000/1001','24','25','30000/1001','30','50','60000/1001','60']],project.fps)
        form.addRow(tr('Bildrate','Frame rate'),self.fps)
        self.fields={}
        for key,de,en in [('default_duration','Neue Bilder: Dauer (s)','New images: duration (s)'),
                          ('default_transition','Neue Bilder: Übergang (s)','New images: transition (s)'),
                          ('start_fade','Anfangsblende (s)','Opening fade (s)'),('end_fade','Schlussblende (s)','Closing fade (s)')]:
            box=number(getattr(project,key),minimum=.01 if key=='default_duration' else 0)
            self.fields[key]=box;form.addRow(tr(de,en),box)
        buttons(self,layout,tr)
    def accept(self):
        if self.width.value()%2 or self.height.value()%2:
            QMessageBox.warning(self,'DiaDoris',self.tr('Bitte gerade Bildmaße verwenden.','Please use even image dimensions.'));return
        p=self.project;ratio=self.height.value()/p.height
        for title in [s.title for s in p.slides if s.title]+[c.title for c in p.overlays if c.title]:
            for e in title.elements:
                e.size*=ratio
                if e.kind=='graphic':e.scale*=ratio
        p.width=self.width.value();p.height=self.height.value();p.fps=self.fps.currentData()
        for key,box in self.fields.items():setattr(p,key,box.value())
        super().accept()


class PropertiesDialog(QDialog):
    def __init__(self,project,objects,track,tr,parent=None,field=None):
        super().__init__(parent);self.project=project;self.objects=objects;self.track=track;self.tr=tr;self.fields={}
        self.setWindowTitle(tr('Eigenschaften','Properties'));self.setMinimumWidth(510)
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();form=QFormLayout(body);scroll.setWidget(body);outer.addWidget(scroll)
        self.multi=len(objects)>1
        if self.multi:
            label=QLabel(tr('Nur angehakte Felder werden für die Auswahl übernommen.','Only checked fields are applied to the selection.'));label.setWordWrap(True);form.addRow(label)
        def add(key,label,widget,value=None,resource=False):
            values=[getattr(project.resource(o.resource) if resource else o,key) for o in objects]
            mixed=any(v!=values[0] for v in values[1:])
            flag=QCheckBox(label+(tr(' · Gemischt',' · Mixed') if mixed else '')) if self.multi else None
            if flag:
                flag.setChecked(False);widget.setEnabled(False);flag.toggled.connect(widget.setEnabled);form.addRow(flag,widget)
            else:form.addRow(label,widget)
            self.fields[key]=(widget,flag,resource)
            if key==field:widget.setFocus()
        is_slide=track=='slides'
        if not self.multi:
            self.name=QLineEdit(objects[0].name);form.addRow(tr('Name','Name'),self.name)
        if is_slide:
            add('duration',tr('Anzeigedauer (s)','Display duration (s)'),number(objects[0].duration,.01))
            add('transition',tr('Übergang zum nächsten Bild','Transition to next image'),combo([
                ('fade',tr('Überblendung','Crossfade')),('black',tr('Schwarzblende','Fade through black')),('cut',tr('Direkter Schnitt','Cut'))],objects[0].transition))
            add('transition_duration',tr('Übergangsdauer (s)','Transition duration (s)'),number(objects[0].transition_duration))
            add('fit',tr('Bild einpassen','Image fitting'),combo([('fit',tr('Schwarze Balken anfügen','Add black bars')),('crop',tr('Bildfüllend beschneiden','Crop to fill'))],objects[0].fit))
            if all(o.kind=='video' for o in objects):
                add('source_in',tr('Ausschnitt ab (s)','Source start (s)'),number(objects[0].source_in))
                add('video_fade_in',tr('Video einblenden (s)','Video fade in (s)'),number(objects[0].video_fade_in))
                add('video_fade_out',tr('Video ausblenden (s)','Video fade out (s)'),number(objects[0].video_fade_out))
                add('video_gain_db',tr('Originalton (dB)','Original audio (dB)'),number(objects[0].video_gain_db,-120,24,.5,1))
                mute=QCheckBox();mute.setChecked(objects[0].video_mute);add('video_mute',tr('Originalton stummschalten','Mute original audio'),mute)
                note=QLabel(tr('An Videogrenzen wird direkt geschnitten. Video- und Tonblenden liegen innerhalb des Ausschnitts.','Video boundaries use cuts. Video/audio fades lie within the selected range.'));note.setWordWrap(True);form.addRow(note)
            elif any(o.kind=='video' for o in objects):
                note=QLabel(tr('Videogrenzen verwenden direkte Schnitte.','Video boundaries use cuts.'));form.addRow(note)
        else:
            add('anchor',tr('Ankerbild','Anchor image'),combo([(s.id,f'{i+1:02d} · {s.name}') for i,s in enumerate(project.slides)],objects[0].anchor))
            add('offset',tr('Startversatz (s)','Start offset (s)'),number(objects[0].offset,-1e10))
            if track in {'audio1','audio2'}:add('source_in',tr('Audiodatei ab (s)','Audio source start (s)'),number(objects[0].source_in))
            for key,de,en in [('fade_in','Einblenden (s)','Fade in (s)'),('hold','Standzeit (s)','Hold (s)'),('fade_out','Ausblenden (s)','Fade out (s)')]:
                add(key,tr(de,en),number(getattr(objects[0],key)))
            if track in {'audio1','audio2'}:
                add('gain_db',tr('Lautstärke (dB)','Gain (dB)'),number(objects[0].gain_db,-120,24,.5,1))
                mute=QCheckBox();mute.setChecked(objects[0].mute);add('mute',tr('Stummschalten','Mute'),mute)
                if track=='audio2':
                    duck=QCheckBox();duck.setChecked(objects[0].duck);add('duck',tr('Audio 1 während dieses Clips absenken','Lower Audio 1 during this clip'),duck)
                    for key,de,en,lo,hi in [('duck_db','Absenkung (dB)','Reduction (dB)',-60,0),('duck_lead','Vorlauf (s)','Lead-in (s)',0,60),('duck_release','Wiederanheben (s)','Release (s)',0,60)]:
                        add(key,tr(de,en),number(getattr(objects[0],key),lo,hi))
            if not self.multi:
                self.effective=QLabel();self.effective.setWordWrap(True);form.addRow(tr('Wirksame Zeit','Effective range'),self.effective)
                self.update_effective()
                for widget,_,_ in self.fields.values():
                    if isinstance(widget,QDoubleSpinBox):widget.valueChanged.connect(self.update_effective)
                    elif isinstance(widget,QComboBox):widget.currentIndexChanged.connect(self.update_effective)
        resource_objects=[o for o in objects if o.resource]
        if len(resource_objects)==len(objects) and track not in {'audio1','audio2'}:
            add('layout',tr('Quelllayout','Source layout'),combo([(x,y) for x,y in [('mono','2D'),('full_sbs','Full-SBS'),('half_sbs','Half-SBS'),('full_ou','Full-OU'),('half_ou','Half-OU')]],project.resource(objects[0].resource).layout),resource=True)
            swap=QCheckBox();swap.setChecked(project.resource(objects[0].resource).swap);add('swap',tr('L/R tauschen','Swap L/R'),swap,resource=True)
        buttons(self,outer,tr);self.resize(540,min(780,260+len(self.fields)*38))
    def value(self,widget):
        if isinstance(widget,QComboBox):return widget.currentData()
        if isinstance(widget,QCheckBox):return widget.isChecked()
        return widget.value()
    def draft(self,o):
        o=copy.deepcopy(o)
        for key,(widget,flag,resource) in self.fields.items():
            if not resource and (flag is None or flag.isChecked()):setattr(o,key,self.value(widget))
        return o
    def update_effective(self,*args):
        o=self.draft(self.objects[0]);start,end=self.project.clip_window(o)
        self.effective.setText(f'{max(0,start):.3f} – {max(0,end):.3f} s  ·  '+self.tr('Gesamtdauer','Total duration')+f': {o.duration:.3f} s')
    def accept(self):
        # Validate on a copy before changing any live objects.
        try:
            drafts=[self.draft(o) for o in self.objects]
            for o in drafts:
                if isinstance(o,Slide) and o.kind=='video':
                    end=o.source_in+o.duration
                    if end>self.project.resource(o.resource).info['duration']+1e-4:raise ValueError(self.tr('Der Ausschnitt reicht über das Videoende hinaus.','Selected range exceeds video duration.'))
                    if o.video_fade_in+o.video_fade_out>o.duration:raise ValueError(self.tr('Videoblenden sind länger als der Ausschnitt.','Video fades exceed the selected duration.'))
                elif not isinstance(o,Slide) and o.duration<=0:raise ValueError(self.tr('Die Gesamtdauer muss größer als null sein.','Total duration must be positive.'))
        except Exception as error:QMessageBox.warning(self,'DiaDoris',str(error));return
        for old,draft in zip(self.objects,drafts):
            if any(resource and (flag is None or flag.isChecked()) for _,flag,resource in self.fields.values()):
                copied=copy.deepcopy(self.project.resource(old.resource))
                from .model import uid
                copied.id=uid();self.project.resources.append(copied);old.resource=copied.id
            for key,(widget,flag,resource) in self.fields.items():
                if flag is not None and not flag.isChecked():continue
                if resource:
                    setattr(self.project.resource(old.resource),key,self.value(widget))
                else:setattr(old,key,getattr(draft,key))
            if not self.multi:old.name=self.name.text()
        super().accept()


class ExportDialog(QDialog):
    def __init__(self,project,tr,parent=None):
        super().__init__(parent);self.project=project;self.tr=tr
        self.setWindowTitle(tr('Video exportieren','Export video'));self.setMinimumWidth(580)
        outer=QVBoxLayout(self);form=QFormLayout();outer.addLayout(form)
        self.preset=QComboBox();self.preset.addItems([p[0] for p in PRESETS]);form.addRow(tr('Vorgabe','Preset'),self.preset)
        self.target=combo([(x,y) for x,y in [('full_sbs','Full-SBS'),('full_ou','Full-OU'),('half_sbs','Half-SBS'),('half_ou','Half-OU'),('anaglyph','Anaglyph'),('row_interleaved',tr('Zeilenverschachtelt','Row-interleaved')),('bd3d','Blu-ray 3D')]])
        form.addRow(tr('Ausgabe','Output'),self.target)
        self.width=QSpinBox();self.width.setRange(16,7680);self.width.setSingleStep(2)
        self.height=QSpinBox();self.height.setRange(16,4320);self.height.setSingleStep(2)
        form.addRow(tr('Breite je Halbbild','Width per eye'),self.width);form.addRow(tr('Höhe je Halbbild','Height per eye'),self.height)
        self.fps=combo([(x,x.replace('24000/1001','23,976').replace('60000/1001','59,94')) for x in ['24000/1001','24','25','30','50','60000/1001','60']]);form.addRow(tr('Bildrate','Frame rate'),self.fps)
        self.container=combo([(x,x.upper()) for x in ['mp4','mkv','iso','m2ts']]);form.addRow(tr('Container','Container'),self.container)
        self.codec=combo([('h264','H.264'),('h265','H.265')]);form.addRow('Codec',self.codec)
        self.quality=QCheckBox(tr('Konstante Qualität (CRF)','Constant quality (CRF)'));form.addRow(self.quality)
        self.bitrate=number(20,1,500,1,1);self.bitrate.setSuffix(' Mbit/s');form.addRow(tr('Videobitrate gesamt','Total video bitrate'),self.bitrate)
        self.crf=number(18,0,40,1,0);form.addRow('CRF',self.crf)
        self.audio=combo([('aac','AAC-LC · 48 kHz · Stereo'),('flac','FLAC · 24 Bit · 48 kHz · Stereo'),('pcm','LPCM · 24 Bit · 48 kHz · Stereo'),('none',tr('Ohne Ton','No audio'))]);form.addRow(tr('Ton','Audio'),self.audio)
        self.audio_bitrate=combo([(n,f'{n} kbit/s') for n in (192,256,320)]);form.addRow('AAC',self.audio_bitrate)
        from transcora.core.engine import methods
        self.method=combo([(k,v['label']) for k,v in methods().items()]);form.addRow(tr('Anaglyphenverfahren','Anaglyph method'),self.method)
        self.profile=combo([('quality','8 Bit · 4:4:4'),('quality10','10 Bit · 4:4:4'),('compatible','8 Bit · 4:2:0')]);form.addRow(tr('Anaglyphenqualität','Anaglyph quality'),self.profile)
        self.bd_mode=combo([('1080p','1080p · 23,976 fps'),('720p50','720p · 50 fps'),('720p5994','720p · 59,94 fps')]);form.addRow('Blu-ray 3D',self.bd_mode)
        self.clip_audio=QCheckBox(tr('Übersteuerten Ton ausdrücklich zulassen','Explicitly allow clipped audio'));form.addRow(self.clip_audio)
        buttons(self,outer,tr)
        self.preset.currentIndexChanged.connect(self.apply_preset)
        for widget in (self.target,self.quality,self.audio):
            (widget.toggled if isinstance(widget,QCheckBox) else widget.currentIndexChanged).connect(self.dependencies)
        self.apply_preset(0)
    def apply_preset(self,index):
        values=asdict(PRESETS[index][1])
        values['fps']=self.project.fps if values['target']!='bd3d' else values['fps']
        for key,value in values.items():
            widget=getattr(self,key)
            if isinstance(widget,QComboBox):widget.setCurrentIndex(max(0,widget.findData(value)))
            elif isinstance(widget,QCheckBox):widget.setChecked(value)
            else:widget.setValue(value)
        self.dependencies()
    def dependencies(self,*args):
        bd=self.target.currentData()=='bd3d';ana=self.target.currentData()=='anaglyph'
        for widget in (self.width,self.height,self.fps,self.codec,self.quality):widget.setEnabled(not bd)
        self.bitrate.setEnabled(bd or not self.quality.isChecked());self.crf.setEnabled(not bd and self.quality.isChecked())
        self.bd_mode.setEnabled(bd);self.method.setEnabled(ana);self.profile.setEnabled(ana)
        self.audio_bitrate.setEnabled(self.audio.currentData()=='aac')
    def settings(self):
        values={}
        for key in ExportSettings.__dataclass_fields__:
            widget=getattr(self,key)
            values[key]=widget.currentData() if isinstance(widget,QComboBox) else widget.isChecked() if isinstance(widget,QCheckBox) else widget.value()
        return ExportSettings(**values)
    def accept(self):
        s=self.settings()
        error=None
        if s.width%2 or s.height%2:error=self.tr('Bitte gerade Bildmaße verwenden.','Please use even image dimensions.')
        elif s.target=='bd3d' and (s.container not in {'iso','m2ts'} or s.audio not in {'pcm','none'} or s.bitrate not in {20,25,30,35,40}):error=self.tr('Blu-ray: ISO/M2TS, LPCM oder ohne Ton, 20/25/30/35/40 Mbit/s wählen.','Blu-ray: select ISO/M2TS, LPCM or no audio, and 20/25/30/35/40 Mbit/s.')
        elif s.target!='bd3d' and s.container not in {'mp4','mkv'}:error=self.tr('Für dieses Ziel MP4 oder MKV wählen.','Select MP4 or MKV for this target.')
        elif s.target!='bd3d' and s.audio=='pcm':error=self.tr('LPCM ist für Blu-ray vorgesehen.','LPCM is intended for Blu-ray.')
        elif s.container=='mp4' and s.audio=='flac':error=self.tr('FLAC bitte mit MKV verwenden.','Use MKV for FLAC audio.')
        elif s.codec=='h265' and s.container=='mp4':error=self.tr('H.265 bitte mit MKV verwenden.','Use MKV for H.265.')
        if error:QMessageBox.warning(self,'DiaDoris',error);return
        super().accept()
