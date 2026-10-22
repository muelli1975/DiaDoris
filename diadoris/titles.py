from __future__ import annotations

import copy
import math
from pathlib import Path
from PySide6.QtCore import Qt,QRectF,QPointF
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QKeySequence
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QSplitter,QListWidget,QPushButton,
                              QPlainTextEdit,QFontComboBox,QCheckBox,QLabel,QComboBox,QFileDialog,QColorDialog,
                              QWidget,QScrollArea,QGridLayout,QMenu,QAbstractItemView,QMessageBox,QSlider)
from .model import Element,GRADIENTS
from .render import Renderer,preview_pair,pil_to_qimage
from .widgets import Preview
from .dialogs import number,combo,buttons


class TitleCanvas(Preview):
    def __init__(self,editor):
        super().__init__();self.editor=editor;self.drag=None;self.guides=[]
        self.setMinimumSize(520,330)
    def pos_project(self,pos):
        rect=self.picture_rect();p=self.editor.project
        return QPointF((pos.x()-rect.x())/rect.width()*p.width,(pos.y()-rect.y())/rect.height()*p.height)
    def paintEvent(self,event):
        super().paintEvent(event)
        e=self.editor;p=QPainter(self);rect=self.picture_rect()
        sx,sy=rect.width()/e.project.width,rect.height()/e.project.height
        for item in e.selected():
            x,y,w,h=e.renderer.element_rect(item)
            r=QRectF(rect.x()+x*sx,rect.y()+y*sy,w*sx,h*sy)
            p.setPen(QPen(QColor('#c6a95e'),1));p.drawRect(r)
            if item.kind=='graphic':
                for point in (r.topLeft(),r.topRight(),r.bottomLeft(),r.bottomRight()):
                    p.fillRect(QRectF(point.x()-4,point.y()-4,8,8),QColor('#c6a95e'))
        for axis,value in self.guides:
            p.setPen(QPen(QColor('#ead49a'),1.3))
            if axis==0:
                x=rect.x()+value*sx;p.drawLine(QPointF(x,rect.top()),QPointF(x,rect.bottom()))
            else:
                y=rect.y()+value*sy;p.drawLine(QPointF(rect.left(),y),QPointF(rect.right(),y))
                if abs(value-e.project.height*.47)<.1:
                    p.drawText(QPointF(rect.left()+6,y-6),e.tr('Optische Mitte','Optical centre'))
    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton:return
        self.setFocus();e=self.editor;pos=self.pos_project(event.position());hit=None;resize=False
        tolerance=8/self.picture_rect().width()*e.project.width
        for item in reversed(e.title.elements):
            x,y,w,h=e.renderer.element_rect(item)
            if QRectF(x-tolerance,y-tolerance,w+2*tolerance,h+2*tolerance).contains(pos):
                hit=item
                if item.kind=='graphic' and item in e.selected():
                    resize=any(abs(pos.x()-a)<tolerance and abs(pos.y()-b)<tolerance for a,b in [(x,y),(x+w,y),(x,y+h),(x+w,y+h)])
                break
        if not hit:return
        if hit not in e.selected():e.select_element(hit.id)
        e.remember();self.drag=(pos,[(v,v.x,v.y,v.scale) for v in e.selected()],resize)
    def mouseMoveEvent(self,event):
        if not self.drag:return
        e=self.editor;pos=self.pos_project(event.position());initial,items,resize=self.drag
        if resize and len(items)==1:
            item,x,y,scale=items[0];cx,cy=x*e.project.width,y*e.project.height
            old=((initial.x()-cx)**2+(initial.y()-cy)**2)**.5
            new=((pos.x()-cx)**2+(pos.y()-cy)**2)**.5
            item.scale=max(.001,scale*new/max(1,old))
        else:
            dx=(pos.x()-initial.x())/e.project.width;dy=(pos.y()-initial.y())/e.project.height
            for item,x,y,_ in items:item.x=x+dx;item.y=y+dy
            self.guides=[]
            if e.magnet.isChecked() and not event.modifiers()&Qt.KeyboardModifier.AltModifier:
                self.snap([v[0] for v in items])
        e.refresh(False)
    def snap(self,items):
        e=self.editor;p=e.project;w,h=p.width,p.height
        threshold=6/self.picture_rect().width()*w
        targets=[[0,w*.1,w*.5,w*.9,w],[0,h*.1,h*.47,h*.5,h*.9,h]]
        n=e.grid.currentData()
        if n:
            origin,span=(.1,.8) if e.reference.currentData()=='safe' else (0,1)
            for axis,size in enumerate((w,h)):targets[axis]+=[(origin+span*i/n)*size for i in range(1,n)]
        for other in e.title.elements:
            if other in items:continue
            x,y,ow,oh=e.renderer.element_rect(other)
            targets[0]+=[x,x+ow/2,x+ow];targets[1]+=[y,y+oh/2,y+oh]
        rects=[]
        for item in items:
            x,y,ow,oh=e.renderer.element_rect(item);extra=abs(item.depth)*w/2000
            rects.append((x-extra,y,ow+2*extra,oh))
        left=min(r[0] for r in rects);top=min(r[1] for r in rects)
        right=max(r[0]+r[2] for r in rects);bottom=max(r[1]+r[3] for r in rects)
        for axis,edges,size in [(0,[left,(left+right)/2,right],w),(1,[top,(top+bottom)/2,bottom],h)]:
            distance,target=min(((t-v,t) for t in targets[axis] for v in edges),key=lambda x:abs(x[0]))
            if abs(distance)<=threshold:
                for item in items:setattr(item,'x' if axis==0 else 'y',getattr(item,'x' if axis==0 else 'y')+distance/size)
                self.guides.append((axis,target))
    def mouseReleaseEvent(self,event):
        self.drag=None;self.guides=[];self.editor.refresh()
    def wheelEvent(self,event):
        if event.modifiers()&Qt.KeyboardModifier.ControlModifier:
            self.editor.remember()
            factor=(1.01 if event.modifiers()&Qt.KeyboardModifier.AltModifier else 1.05)**(event.angleDelta().y()/120)
            for e in self.editor.selected():
                if e.kind=='graphic':e.scale*=factor
            self.editor.refresh();event.accept()
        else:super().wheelEvent(event)
    def keyPressEvent(self,event):
        e=self.editor;mods=event.modifiers();key=event.key()
        if key in (Qt.Key.Key_Left,Qt.Key.Key_Right,Qt.Key.Key_Up,Qt.Key.Key_Down):
            e.remember()
            if mods&Qt.KeyboardModifier.ControlModifier and mods&Qt.KeyboardModifier.ShiftModifier and key in (Qt.Key.Key_Up,Qt.Key.Key_Down):
                for item in e.selected():
                    if item.kind=='graphic':item.scale*=1.05 if key==Qt.Key.Key_Up else 1/1.05
            else:
                step=10 if mods&Qt.KeyboardModifier.ControlModifier else 5 if mods&Qt.KeyboardModifier.ShiftModifier else 1
                for item in e.selected():
                    item.x+=(step if key==Qt.Key.Key_Right else -step if key==Qt.Key.Key_Left else 0)/e.project.width
                    item.y+=(step if key==Qt.Key.Key_Down else -step if key==Qt.Key.Key_Up else 0)/e.project.height
            e.refresh();event.accept();return
        if key==Qt.Key.Key_G:
            if event.isAutoRepeat():return
            e.grid.setCurrentIndex(0 if mods&Qt.KeyboardModifier.ShiftModifier else (e.grid.currentIndex()+1)%e.grid.count());return
        if key==Qt.Key.Key_H and mods&Qt.KeyboardModifier.ControlModifier and mods&Qt.KeyboardModifier.ShiftModifier:
            if not event.isAutoRepeat():e.safe.setChecked(not e.safe.isChecked())
            return
        if key==Qt.Key.Key_R and mods&Qt.KeyboardModifier.ControlModifier:
            e.fit_graphic() if mods&Qt.KeyboardModifier.ShiftModifier else e.original_size();return
        if event.matches(QKeySequence.StandardKey.Undo):e.undo();return
        if key==Qt.Key.Key_F1:e.help();return
        super().keyPressEvent(event)
    def contextMenuEvent(self,event):
        menu=QMenu(self);e=self.editor
        menu.addAction(e.tr('Originalgröße','Original size')+'\tCtrl+R',e.original_size)
        menu.addAction(e.tr('In Titelbereich einpassen','Fit title area')+'\tCtrl+Shift+R',e.fit_graphic)
        menu.exec(event.globalPos())


class TitleEditor(QDialog):
    def __init__(self,project,title,tr,parent=None):
        super().__init__(parent);self.project=project;self.title=title;self.tr=tr;self.loading=False;self.history=[]
        self.renderer=Renderer(project,(project.width,project.height))
        preview_width=min(960,project.width)
        self.preview_renderer=Renderer(project,(preview_width,max(1,round(preview_width*project.height/project.width))))
        self.setWindowTitle(tr('Titel gestalten','Design title'));self.resize(1220,820);self.gesture=False
        outer=QVBoxLayout(self);split=QSplitter();outer.addWidget(split,1)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(360);scroll.setMaximumWidth(450)
        body=QWidget();left=QVBoxLayout(body);scroll.setWidget(body);split.addWidget(scroll)
        self.elements=QListWidget();self.elements.setMaximumHeight(130)
        self.elements.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        left.addWidget(self.elements)
        row=QHBoxLayout();left.addLayout(row)
        for label,fn in [(tr('+ Text','+ Text'),self.add_text),(tr('+ Grafik','+ Graphic'),self.add_graphic),('−',self.remove_element)]:
            b=QPushButton(label);b.clicked.connect(fn);row.addWidget(b)
        order=QHBoxLayout();left.addLayout(order)
        for label,delta in [(tr('Ebene höher','Layer up'),1),(tr('Ebene tiefer','Layer down'),-1)]:
            b=QPushButton(label);b.clicked.connect(lambda checked=False,d=delta:self.reorder(d));order.addWidget(b)
        form=QFormLayout();left.addLayout(form)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.text=QPlainTextEdit();self.text.setMaximumHeight(88);form.addRow(tr('Text','Text'),self.text)
        self.font=QFontComboBox();self.font.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);self.font.setMinimumContentsLength(12);form.addRow(tr('Schrift','Font'),self.font)
        self.size=number(72,.1,10000,1,1);form.addRow(tr('Schriftgröße (px)','Font size (px)'),self.size)
        styles=QHBoxLayout();self.bold=QCheckBox(tr('Fett','Bold'));self.italic=QCheckBox(tr('Kursiv','Italic'));styles.addWidget(self.bold);styles.addWidget(self.italic);form.addRow(styles)
        self.color=QPushButton();self.color.clicked.connect(self.choose_color);form.addRow(tr('Textfarbe','Text colour'),self.color)
        self.align=combo([('left',tr('Links','Left')),('center',tr('Mitte','Centre')),('right',tr('Rechts','Right'))]);form.addRow(tr('Textausrichtung','Text alignment'),self.align)
        self.scale=number(100,.1,100000,.1,1);self.scale.setSuffix(' %');form.addRow(tr('Grafikgröße','Graphic size'),self.scale)
        self.depth=number(0,-1000,1000,.5,2);self.depth.setSuffix(' ‰');self.depth.setToolTip(tr('Minus: vor dem Scheinfenster. Plus: dahinter.','Minus: in front of the screen. Plus: behind it.'));form.addRow(tr('Tiefe','Depth'),self.depth)
        self.depth_slider=QSlider(Qt.Orientation.Horizontal);self.depth_slider.setRange(-5000,5000);self.depth_slider.setSingleStep(50);form.addRow(self.depth_slider)
        self.depth_slider.valueChanged.connect(lambda v:self.depth.setValue(v/100))
        self.depth_slider.sliderPressed.connect(self.begin_gesture);self.depth_slider.sliderReleased.connect(self.end_gesture)
        self.depth.valueChanged.connect(lambda v:self.sync_depth_slider(v))
        self.shadow=QCheckBox(tr('Schlagschatten','Drop shadow'));form.addRow(self.shadow)
        advanced=QPushButton(tr('Erweitert','Advanced'));advanced.setCheckable(True);left.addWidget(advanced)
        self.advanced=QWidget();af=QFormLayout(self.advanced);af.setContentsMargins(0,0,0,0)
        self.outline=number(0,0,100,.5,1);af.addRow(tr('Umriss (px)','Outline (px)'),self.outline)
        self.opacity=number(60,0,100,1,0);af.addRow(tr('Schatten (%)','Shadow (%)'),self.opacity)
        self.offset=number(3,-100,100,.5,1);af.addRow(tr('Schattenversatz (px)','Shadow offset (px)'),self.offset)
        self.blur=number(6,0,100,.5,1);af.addRow(tr('Weichzeichnung (px)','Blur (px)'),self.blur)
        left.addWidget(self.advanced);self.advanced.hide();advanced.toggled.connect(self.advanced.setVisible)
        positions=QGridLayout();left.addLayout(positions)
        for i,label in enumerate(['↖','↑','↗','←','●','→','↙','↓','↘']):
            b=QPushButton(label);b.clicked.connect(lambda checked=False,n=i:self.position(n));positions.addWidget(b,i//3,i%3)
        self.bg=combo([('transparent',tr('Transparent','Transparent')),('solid',tr('Einfarbig','Solid colour')),('gradient',tr('Farbverlauf','Gradient')),('image',tr('Bild','Image'))],title.background)
        form2=QFormLayout();left.addLayout(form2);form2.addRow(tr('Hintergrund','Background'),self.bg)
        form2.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.gradient=QComboBox();self.gradient.addItems([g[0] for g in GRADIENTS]);form2.addRow(tr('Verlauf','Gradient'),self.gradient)
        colors=QHBoxLayout();self.top=QPushButton(tr('Oben','Top'));self.bottom=QPushButton(tr('Unten','Bottom'));colors.addWidget(self.top);colors.addWidget(self.bottom);form2.addRow(colors)
        self.top.clicked.connect(lambda:self.background_color('top'));self.bottom.clicked.connect(lambda:self.background_color('bottom'))
        self.bg_image=QPushButton(tr('Hintergrundbild auswählen','Choose background image'));self.bg_image.clicked.connect(self.choose_background);form2.addRow(self.bg_image)
        self.fit=combo([('crop',tr('Bildfüllend beschneiden','Crop to fill')),('fit',tr('Mit Rändern einpassen','Fit with borders'))],title.fit);form2.addRow(tr('Hintergrund einpassen','Background fitting'),self.fit)
        self.crop_x=number(title.crop_x*100,0,100,1,1);self.crop_y=number(title.crop_y*100,0,100,1,1)
        form2.addRow(tr('Ausschnitt horizontal (%)','Crop horizontal (%)'),self.crop_x);form2.addRow(tr('Ausschnitt vertikal (%)','Crop vertical (%)'),self.crop_y)
        reverse=QPushButton(tr('Verlauf umkehren','Reverse gradient'));reverse.clicked.connect(self.reverse_gradient);form2.addRow(reverse)
        left.addStretch()
        right=QWidget();rv=QVBoxLayout(right);split.addWidget(right);split.setStretchFactor(1,1)
        helpers=QHBoxLayout();rv.addLayout(helpers)
        self.safe=QCheckBox(tr('Safe Area','Safe area'));self.safe.setChecked(True);helpers.addWidget(self.safe)
        self.magnet=QCheckBox(tr('Magnet','Snap'));self.magnet.setChecked(True);helpers.addWidget(self.magnet)
        self.grid=combo([(0,tr('Raster aus','Grid off'))]+[(n,f'{n} × {n}') for n in [3,4,6,9,12]]);helpers.addWidget(self.grid)
        self.reference=combo([('safe',tr('Titelbereich','Title area')),('image',tr('Gesamtbild','Whole image'))]);helpers.addWidget(self.reference)
        self.canvas=TitleCanvas(self);rv.addWidget(self.canvas,1)
        self.note=QLabel(tr('Pfeile: 1 px · Umschalt: 5 px · Strg: 10 px · Alt beim Ziehen: ohne Magnet','Arrows: 1 px · Shift: 5 px · Ctrl: 10 px · Alt while dragging: no snapping'));self.note.setWordWrap(True);rv.addWidget(self.note)
        helpb=QPushButton(tr('Tastaturbefehle · F1','Keyboard shortcuts · F1'));helpb.clicked.connect(self.help);rv.addWidget(helpb)
        buttons(self,outer,tr)
        self.elements.itemSelectionChanged.connect(self.load_element)
        self.text.textChanged.connect(self.fields_changed)
        self.font.currentFontChanged.connect(self.fields_changed)
        for widget in (self.size,self.scale,self.depth,self.outline,self.opacity,self.offset,self.blur):widget.valueChanged.connect(self.fields_changed)
        for widget in (self.bold,self.italic,self.shadow):widget.toggled.connect(self.fields_changed)
        self.align.currentIndexChanged.connect(self.fields_changed)
        self.bg.currentIndexChanged.connect(self.background_changed);self.fit.currentIndexChanged.connect(self.background_changed)
        self.crop_x.valueChanged.connect(self.background_changed);self.crop_y.valueChanged.connect(self.background_changed)
        self.gradient.currentIndexChanged.connect(self.gradient_changed)
        self.safe.toggled.connect(self.refresh);self.grid.currentIndexChanged.connect(self.refresh);self.reference.currentIndexChanged.connect(self.refresh)
        self.reload_elements();self.refresh()
    def begin_gesture(self):self.remember();self.gesture=True
    def end_gesture(self):self.gesture=False
    def sync_depth_slider(self,value):
        self.depth_slider.blockSignals(True);self.depth_slider.setValue(round(max(-50,min(50,value))*100));self.depth_slider.blockSignals(False)
    def selected(self):
        keys={i.data(Qt.ItemDataRole.UserRole) for i in self.elements.selectedItems()}
        return [e for e in self.title.elements if e.id in keys]
    def select_element(self,key):
        for i in range(self.elements.count()):
            item=self.elements.item(i);item.setSelected(item.data(Qt.ItemDataRole.UserRole)==key)
    def reload_elements(self):
        key=self.selected()[0].id if self.selected() else None
        self.elements.blockSignals(True);self.elements.clear()
        from PySide6.QtWidgets import QListWidgetItem
        for e in self.title.elements:
            text=e.text.replace('\n',' ')[:40] if e.kind=='text' else Path(self.project.resource(e.resource).path).name
            item=QListWidgetItem(text or self.tr('Text','Text'));item.setData(Qt.ItemDataRole.UserRole,e.id);self.elements.addItem(item)
            if e.id==key:item.setSelected(True)
        if not self.elements.selectedItems() and self.elements.count():self.elements.item(0).setSelected(True)
        self.elements.blockSignals(False);self.load_element()
    def remember(self):
        if self.gesture:return
        current=copy.deepcopy(self.title)
        if not self.history or self.history[-1]!=current:self.history.append(current)
        self.history=self.history[-50:]
    def undo(self):
        if not self.history:return
        prior=self.history.pop();self.title.__dict__.update(copy.deepcopy(prior.__dict__));self.reload_elements();self.refresh()
    def load_element(self):
        self.loading=True
        selected=self.selected();e=selected[0] if selected else None
        for widget in (self.text,self.font,self.size,self.bold,self.italic,self.color,self.align):widget.setEnabled(e is not None and e.kind=='text')
        self.scale.setEnabled(e is not None and e.kind=='graphic')
        for widget in (self.shadow,self.outline,self.opacity,self.offset,self.blur):widget.setEnabled(e is not None and e.kind=='text')
        if e:
            self.text.setPlainText(e.text);self.font.setCurrentFont(QFont(e.font));self.size.setValue(e.size);self.bold.setChecked(e.bold);self.italic.setChecked(e.italic)
            self.color.setText(e.color);self.scale.setValue(e.scale*100);self.depth.setValue(e.depth);self.shadow.setChecked(e.shadow)
            self.outline.setValue(e.outline);self.opacity.setValue(e.shadow_opacity*100);self.offset.setValue(e.shadow_offset);self.blur.setValue(e.shadow_blur)
            self.align.setCurrentIndex(max(0,self.align.findData(e.align)))
        self.loading=False;self.refresh(False)
    def fields_changed(self,*args):
        if self.loading:return
        selected=self.selected()
        if not selected:return
        self.remember()
        for e in selected:
            e.depth=self.depth.value();e.shadow=self.shadow.isChecked();e.shadow_opacity=self.opacity.value()/100;e.shadow_offset=self.offset.value();e.shadow_blur=self.blur.value();e.outline=self.outline.value()
        e=selected[0]
        e.text=self.text.toPlainText();e.font=self.font.currentFont().family();e.size=self.size.value();e.bold=self.bold.isChecked();e.italic=self.italic.isChecked();e.align=self.align.currentData()
        if e.kind=='graphic':e.scale=self.scale.value()/100
        self.refresh(False)
    def refresh(self,load=True):
        if not hasattr(self,'canvas'):return
        self.canvas.safe=self.safe.isChecked();self.canvas.grid=0  # Draw selected grid below in its correct reference area.
        self.canvas.grid_reference=self.reference.currentData()
        try:
            pair=self.preview_renderer.title(self.title)
            from PIL import Image
            pairs=[]
            for image in pair:
                black=Image.new('RGBA',image.size,'black');black.alpha_composite(image);pairs.append(black.convert('RGB'))
            self.canvas.set_image(pil_to_qimage(preview_pair(pairs)))
            # Raster line rendering is delegated to Preview; same subdivisions, no effect on output.
            self.canvas.grid=self.grid.currentData();self.canvas.update()
            self.top.setText(self.title.top);self.bottom.setText(self.title.bottom)
        except Exception as error:self.note.setText(str(error))
        if load:
            self.loading=True
            selected=self.selected()
            if selected:self.scale.setValue(selected[0].scale*100);self.depth.setValue(selected[0].depth)
            self.loading=False
    def add_text(self):
        self.remember();e=Element(text=self.tr('Neuer Text','New text'));self.title.elements.append(e);self.reload_elements();self.select_element(e.id)
    def add_graphic(self):
        path,_=QFileDialog.getOpenFileName(self,self.tr('Grafik auswählen','Choose graphic'),'','Images (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp *.jps *.pns)')
        if not path:return
        self.remember();r=self.project.add_resource(path,'graphic');e=Element(kind='graphic',resource=r.id,shadow=False)
        self.title.elements.append(e)
        self.reload_elements();self.select_element(e.id);self.fit_graphic()
    def remove_element(self):
        self.remember();selected=self.selected();self.title.elements[:]=[e for e in self.title.elements if e not in selected];self.reload_elements();self.refresh()
    def reorder(self,delta):
        self.remember()
        for e in self.selected():
            i=self.title.elements.index(e);j=max(0,min(len(self.title.elements)-1,i+delta));self.title.elements.insert(j,self.title.elements.pop(i))
        self.reload_elements();self.refresh()
    def fit_graphic(self):
        self.remember();p=self.project
        for e in self.selected():
            if e.kind!='graphic':continue
            original=self.renderer.pair(e.resource)
            width=max(a.width for a in original);height=max(a.height for a in original)
            space=p.width*.8-abs(e.depth)*p.width/1000
            e.scale=max(.001,min(1.,max(1,math.floor(space)-1)/width,max(1,math.floor(p.height*.8)-1)/height))
            self.clamp(e)
        self.refresh()
    def original_size(self):
        self.remember()
        for e in self.selected():
            if e.kind=='graphic':e.scale=1.
        self.refresh()
    def clamp(self,e):
        p=self.project;_,_,w,h=self.renderer.element_rect(e);extra=abs(e.depth)*p.width/2000
        low=.1+(w/2+extra)/p.width;high=.9-(w/2+extra)/p.width
        e.x=max(low,min(high,e.x)) if low<=high else .5
        low=.1+h/2/p.height;high=.9-h/2/p.height;e.y=max(low,min(high,e.y)) if low<=high else .47
    def position(self,index):
        self.remember();p=self.project
        for e in self.selected():
            _,_,w,h=self.renderer.element_rect(e);extra=abs(e.depth)*p.width/2000
            e.x=[.1+(w/2+extra)/p.width,.5,.9-(w/2+extra)/p.width][index%3]
            e.y=[.1+h/2/p.height,.47,.9-h/2/p.height][index//3]
        self.refresh()
    def choose_color(self):
        selected=self.selected()
        if not selected:return
        color=QColorDialog.getColor(QColor(selected[0].color),self)
        if color.isValid():
            self.remember()
            for e in selected:e.color=color.name()
            self.color.setText(color.name());self.refresh(False)
    def background_changed(self,*args):
        if self.loading:return
        self.remember();self.title.background=self.bg.currentData();self.title.fit=self.fit.currentData();self.title.crop_x=self.crop_x.value()/100;self.title.crop_y=self.crop_y.value()/100;self.refresh(False)
    def gradient_changed(self,index):
        self.remember();_,self.title.top,self.title.bottom=GRADIENTS[index];self.title.background='gradient'
        self.bg.setCurrentIndex(self.bg.findData('gradient'));self.refresh(False)
    def background_color(self,key):
        color=QColorDialog.getColor(QColor(getattr(self.title,key)),self)
        if color.isValid():self.remember();setattr(self.title,key,color.name());self.refresh(False)
    def reverse_gradient(self):
        self.remember();self.title.top,self.title.bottom=self.title.bottom,self.title.top;self.refresh(False)
    def choose_background(self):
        path,_=QFileDialog.getOpenFileName(self,self.tr('Hintergrundbild auswählen','Choose background image'),'','Images (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp *.jps *.pns *.mpo)')
        if path:
            self.remember();self.title.image=self.project.add_resource(path,'graphic').id;self.bg.setCurrentIndex(self.bg.findData('image'));self.refresh(False)
    def help(self):
        QMessageBox.information(self,self.tr('Titel · Tastaturbefehle','Title · keyboard shortcuts'),self.tr(
            'Pfeile: 1 Projektpixel\nUmschalt + Pfeile: 5 Pixel\nStrg + Pfeile: 10 Pixel\nStrg + Umschalt + ↑/↓: Grafikgröße\nStrg + R: Originalgröße\nStrg + Umschalt + R: In Titelbereich einpassen\nStrg + Mausrad: Grafikgröße, zusätzlich Alt: fein\nG / Umschalt + G: Raster durchschalten / aus\nAlt beim Ziehen: ohne Magnet\nStrg + Z: Rückgängig\n\nNegative Tiefe: vor dem Scheinfenster. Positive Tiefe: dahinter. Ebenenreihenfolge und Tiefe bewusst aufeinander abstimmen.',
            'Arrows: 1 project pixel\nShift + arrows: 5 pixels\nCtrl + arrows: 10 pixels\nCtrl + Shift + ↑/↓: graphic size\nCtrl + R: original size\nCtrl + Shift + R: fit title area\nCtrl + wheel: graphic size, add Alt for fine steps\nG / Shift + G: cycle grid / off\nAlt while dragging: no snapping\nCtrl + Z: undo\n\nNegative depth: in front of the screen. Positive depth: behind it. Arrange layer order and depth deliberately.'))
