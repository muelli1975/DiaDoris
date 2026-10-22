from __future__ import annotations

import math
import time
from PySide6.QtCore import Qt,QRectF,QPointF,Signal,QTimer
from PySide6.QtGui import QColor,QFont,QPainter,QPen
from PySide6.QtWidgets import QWidget,QHeaderView,QTableWidget,QAbstractItemView


STYLE = '''
QWidget {background:#111111;color:#f2f2f2;font-family:"Segoe UI";font-size:13px;}
QMainWindow,QDialog {background:#111111;}
QPushButton,QToolButton,QComboBox {background:#181818;border:1px solid #333333;border-radius:4px;padding:6px 10px;min-height:20px;}
QPushButton:hover,QToolButton:hover {background:#282828;}
QPushButton:disabled,QToolButton:disabled,QComboBox:disabled {color:#727272;border-color:#333333;}
QPushButton[primary="true"] {color:#c6a95e;border-color:#9c7c38;}
QPushButton[primary="true"]:hover {background:#c6a95e;color:#111111;}
QLineEdit,QTextEdit,QPlainTextEdit,QSpinBox,QDoubleSpinBox,QFontComboBox {background:#202020;border:1px solid #333333;border-radius:3px;padding:4px;selection-background-color:#c6a95e;selection-color:#111111;}
QTreeWidget,QListWidget,QTableWidget {background:#202020;alternate-background-color:#181818;border:1px solid #333333;gridline-color:#333333;}
QTableWidget::item:selected,QListWidget::item:selected {background:#c6a95e;color:#111111;}
QHeaderView::section {background:#202020;color:#c6a95e;border:0;border-right:1px solid #333333;border-bottom:1px solid #333333;padding:6px;}
QMenu {background:#181818;border:1px solid #333333;}
QMenu::item {padding:6px 24px;}
QMenu::item:selected {background:#282828;}
QMenuBar {background:#181818;}
QMenuBar::item:selected {background:#282828;}
QProgressBar {border:1px solid #333333;background:#181818;text-align:center;min-height:18px;}
QProgressBar::chunk {background:#9c7c38;}
QSlider::groove:horizontal {height:5px;background:#333333;}
QSlider::sub-page:horizontal {background:#9c7c38;}
QSlider::handle:horizontal {width:13px;margin:-5px 0;background:#c6a95e;border-radius:5px;}
QCheckBox {spacing:7px;}
QCheckBox::indicator {width:15px;height:15px;background:#181818;border:1px solid #555;border-radius:3px;}
QCheckBox::indicator:checked {background:#9c7c38;image:url(none);border:2px solid #c6a95e;}
QCheckBox::indicator:disabled:checked {background:#727272;border-color:#727272;}
QCheckBox:disabled {color:#727272;}
QTabWidget::pane {border:1px solid #333333;}
QTabBar::tab {padding:7px 15px;background:#181818;border:1px solid #333333;}
QTabBar::tab:selected {background:#9c7c38;color:#111111;}
QGroupBox {border:1px solid #333333;border-radius:4px;margin-top:14px;padding-top:10px;}
QGroupBox::title {subcontrol-origin:margin;left:10px;padding:0 5px;}
QScrollBar:vertical {background:#181818;width:12px;}
QScrollBar::handle:vertical {background:#444;min-height:24px;border-radius:4px;}
QLabel[muted="true"] {color:#b8b8b8;}
'''


class Preview(QWidget):
    toggle_play=Signal()
    closed=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.image=None;self.safe=True;self.grid=0;self.grid_reference='image';self.stereo_mode='anaglyph'
        self.setMinimumSize(360,220)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def picture_rect(self):
        if self.image is None:return QRectF(self.rect()).adjusted(20,20,-20,-20)
        w,h=self.image.width(),self.image.height()
        pad=max(16,round(self.width()*.03)+2)
        factor=min((self.width()-2*pad)/w,(self.height()-2*pad)/h)
        return QRectF((self.width()-w*factor)/2,(self.height()-h*factor)/2,w*factor,h*factor)
    def set_image(self,image):self.image=image;self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('black'))
        rect=self.picture_rect()
        if self.image is not None:p.drawImage(rect,self.image)
        else:
            p.setPen(QColor('#b8b8b8'));p.drawText(rect,Qt.AlignmentFlag.AlignCenter,'DiaDoris')
        eyes=[rect] if self.stereo_mode not in {'parallel','cross'} else [QRectF(rect.x(),rect.y(),rect.width()/2,rect.height()),QRectF(rect.center().x(),rect.y(),rect.width()/2,rect.height())]
        for eye in eyes:
            safe=eye.adjusted(eye.width()*.1,eye.height()*.1,-eye.width()*.1,-eye.height()*.1)
            if self.safe:
                p.setPen(QPen(QColor('#9c7c38'),1,Qt.PenStyle.DashLine));p.drawRect(safe)
            gridrect=safe if self.grid_reference=='safe' else eye
            if self.grid:
                for i in range(1,self.grid):
                    major=self.grid in (6,9,12) and i%(self.grid//3)==0
                    x=gridrect.x()+i*gridrect.width()/self.grid;y=gridrect.y()+i*gridrect.height()/self.grid
                    for color,width in [(QColor(0,0,0,120),2.5),(QColor(210,210,210,145 if major else 90),1.2 if major else .8)]:
                        p.setPen(QPen(color,width))
                        p.drawLine(QPointF(x,gridrect.top()),QPointF(x,gridrect.bottom()))
                        p.drawLine(QPointF(gridrect.left(),y),QPointF(gridrect.right(),y))
    def mouseDoubleClickEvent(self,event):self.toggle_play.emit()
    def closeEvent(self,event):self.closed.emit();super().closeEvent(event)


class Meter(QWidget):
    """Sample peak meter, dBFS. Equidistant 1 dB segments from -60 to 0 dBFS."""
    def __init__(self,parent=None):
        super().__init__(parent);self.levels=[-60.,-60.];self.peaks=[-60.,-60.];self.clip=[False,False]
        self.until=[0.,0.];self.setFixedWidth(92);self.setMinimumHeight(220)
        self.bounds=None;self.reference=None
        self.setToolTip('Sample peak · dBFS · 0 dBFS = digital full scale')
    def reset(self):
        self.clip=[False,False];self.levels=[-60.,-60.];self.peaks=[-60.,-60.];self.update()
    def set_levels(self,values):
        now=time.monotonic()
        for i,v in enumerate(values):
            self.levels[i]=max(-60.,20*math.log10(max(1e-10,float(v))))
            self.clip[i]|=v>=1.
            if self.levels[i]>=self.peaks[i] or now>self.until[i]:
                self.peaks[i]=self.levels[i];self.until[i]=now+1.5
        self.update()
    def mousePressEvent(self,event):self.reset()
    def paintEvent(self,event):
        p=QPainter(self);p.setFont(QFont('Segoe UI',8));p.fillRect(self.rect(),QColor('#111111'))
        if self.reference is not None:
            picture=self.reference.picture_rect();top,bottom=picture.top(),picture.bottom()
        else:top,bottom=self.bounds or (29,self.height()-25)
        h=max(1,bottom-top)
        p.setPen(QColor('#b8b8b8'));p.drawText(QRectF(0,top-29,92,18),Qt.AlignmentFlag.AlignCenter,'dBFS')
        for i,x in enumerate((9,31)):
            p.fillRect(QRectF(x,top-9,15,5),QColor('#df4741' if self.clip[i] else '#402322'))
            for db in range(-60,0):
                y=top+(-db-1)/60*h
                active=self.levels[i]>=db
                color=('#df4741' if db>=-3 else '#d7b640' if db>=-12 else '#48ae66') if active else '#242a25'
                p.fillRect(QRectF(x,y,15,max(.5,h/60-1)),QColor(color))
            y=top+max(0,min(60,-self.peaks[i]))/60*h
            p.setPen(QPen(QColor('#e8e8e8'),1));p.drawLine(QPointF(x,y),QPointF(x+15,y))
            p.setPen(QColor('#b8b8b8'));p.drawText(QRectF(x,bottom+5,15,15),Qt.AlignmentFlag.AlignCenter,'L' if i==0 else 'R')
        for db in (0,-3,-6,-12,-18,-24,-36,-48,-60):
            y=top+(-db)/60*h
            p.setPen(QColor('#b8b8b8'));p.drawText(QRectF(50,y-7,39,14),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,str(db))


class TrackHeader(QHeaderView):
    def __init__(self,labels,groups,parent=None):
        super().__init__(Qt.Orientation.Horizontal,parent);self.labels=labels;self.groups=groups
        self.setMinimumHeight(56);self.setMaximumHeight(56);self.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
    def paintSection(self,p,rect,index):
        p.fillRect(rect,QColor('#202020'));p.setPen(QColor('#333333'));p.drawRect(rect)
        p.setPen(QColor('#b8b8b8'));p.drawText(rect.adjusted(7,27,-3,-2),Qt.AlignmentFlag.AlignVCenter,self.labels[index])
    def paintEvent(self,event):
        super().paintEvent(event);p=QPainter(self.viewport())
        for start,end,label in self.groups:
            x=self.sectionViewportPosition(start);width=sum(self.sectionSize(i) for i in range(start,end+1))
            rect=QRectF(x,0,width,27);p.fillRect(rect,QColor('#181818'));p.setPen(QColor('#c6a95e'))
            p.drawText(rect.adjusted(7,0,-3,0),Qt.AlignmentFlag.AlignVCenter,label)


class TrackTable(QTableWidget):
    files_dropped=Signal(list,int,int)
    moved=Signal(str,int,int)
    def __init__(self,parent=None):
        super().__init__(parent);self.setAcceptDrops(True);self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True);self.verticalHeader().hide();self.setShowGrid(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() or event.mimeData().hasFormat('application/x-diadoris-entry'):event.acceptProposedAction()
        else:event.ignore()
    def dragMoveEvent(self,event):event.acceptProposedAction()
    def startDrag(self,actions):
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QDrag
        item=self.currentItem()
        if not item or not item.data(Qt.ItemDataRole.UserRole):return
        mime=QMimeData();mime.setData('application/x-diadoris-entry',str(item.data(Qt.ItemDataRole.UserRole)).encode())
        drag=QDrag(self);drag.setMimeData(mime);drag.exec(Qt.DropAction.MoveAction)
    def dropEvent(self,event):
        row=self.rowAt(round(event.position().y()));col=self.columnAt(round(event.position().x()))
        if event.mimeData().hasUrls():
            self.files_dropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()],max(0,col),row)
        else:self.moved.emit(bytes(event.mimeData().data('application/x-diadoris-entry')).decode(),max(0,col),row)
        event.acceptProposedAction()
    def keyPressEvent(self,event):
        keys={Qt.Key.Key_Space,Qt.Key.Key_Delete,Qt.Key.Key_Return,Qt.Key.Key_Enter,Qt.Key.Key_PageUp,Qt.Key.Key_PageDown,Qt.Key.Key_G}
        if event.key() in keys or (event.key() in {Qt.Key.Key_Up,Qt.Key.Key_Down} and event.modifiers()&Qt.KeyboardModifier.AltModifier) or (event.key()==Qt.Key.Key_A and event.modifiers()&Qt.KeyboardModifier.ControlModifier):
            self.window().keyPressEvent(event);event.accept();return
        super().keyPressEvent(event)
