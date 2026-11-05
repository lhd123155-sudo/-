import sys, time, json, csv, subprocess
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPixmap, QPen, QFontDatabase, QFont
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,
    QPushButton,QComboBox,QLineEdit,QStackedWidget,QFrame,QTableWidget,QTableWidgetItem,
    QScrollArea,QCheckBox,QFileDialog,QMessageBox,QHeaderView,QAbstractItemView,QDialog,QInputDialog,QTabWidget)
from analytics_data import Repository, BASE, MARIO, GAMES, maps, analyze, summarize_runs, rate, duration_text, run_metric_rows
from auto_capture import WindowCapture, load_profile, save_profile, config_dir
from route_heat import review_route, route_deaths
from sample_counter import screenshot_entries, screenshot_levels

LEGACY_STYLE='''
QWidget {background:#111722;color:#e5edf7;font-family:"Microsoft YaHei";font-size:14px;}
QFrame#sidebar {background:#192332;border-right:1px solid #2c3d50;}
QLabel#title {font-size:26px;font-weight:700;color:#ffffff;}
QLabel#muted {color:#9eafc4;}
QPushButton {background:#243348;border:1px solid #364b64;border-radius:7px;padding:10px 14px;text-align:left;}
QPushButton:hover {background:#324b63;} QPushButton:checked {background:#20685f;border-color:#64d7be;}
QPushButton:disabled {color:#64748b;background:#1b2635;}
QLineEdit,QComboBox {background:#1b2635;border:1px solid #3b5067;border-radius:6px;padding:8px;}
QTableWidget {background:#16202e;alternate-background-color:#1e2b3d;gridline-color:#304158;}
QHeaderView::section {background:#26394e;color:#e5edf7;padding:8px;border:0;}
QScrollArea {border:0;} QCheckBox {padding:5px;} QToolTip {color:#fff;background:#26394e;}
'''
from ui_design import STYLE,polish,update_player,update_admin,card,text


def label(text, title=False, muted=False):
    w=QLabel(text); w.setWordWrap(True)
    if title: w.setObjectName('title')
    elif muted: w.setObjectName('muted')
    return w

def button(text, fn):
    w=QPushButton(text);w.clicked.connect(fn);return w

def table(headers):
    w=QTableWidget(0,len(headers));w.setHorizontalHeaderLabels(headers)
    w.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    w.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);w.setAlternatingRowColors(True)
    w.setMinimumHeight(220);return w

def fill(w, rows):
    w.setRowCount(len(rows))
    for i,row in enumerate(rows):
        for j,v in enumerate(row): w.setItem(i,j,QTableWidgetItem(str(v)))

class MapCanvas(QWidget):
    picked=Signal(float,float)
    def __init__(self):
        super().__init__();self.setMinimumSize(600,230);self.pix=QPixmap();self.points=[];self.selected=None;self.heat=True;self.zoom=1.;self.pan=(0.,0.);self.drag=None
    def set_data(self,path=None,points=None):
        key=str(path) if path else ''
        if getattr(self,'path_key',None)!=key:self.zoom=1.;self.pan=(0.,0.)
        self.path_key=key;self.pix=QPixmap(key) if key else QPixmap();self.points=points or [];self.selected=None;self.update()
    def area(self):
        r=QRectF(18,24,self.width()-36,self.height()-48)
        if not self.pix.isNull():
            size=self.pix.size();ratio=min(r.width()/size.width(),r.height()/size.height())*self.zoom
            return QRectF(r.x()+(r.width()-size.width()*ratio)/2+self.pan[0],r.y()+(r.height()-size.height()*ratio)/2+self.pan[1],size.width()*ratio,size.height()*ratio)
        return r
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.fillRect(self.rect(),QColor('#101c2c'));r=self.area()
        if self.pix.isNull():
            p.setPen(QColor('#9eafc4'));p.drawText(r,Qt.AlignmentFlag.AlignCenter,getattr(self,'empty_text','地图尚未就绪\n选择已有配置，或完成识别设置后开始探索'));return
        p.drawPixmap(r,self.pix,QRectF(self.pix.rect()))
        if self.heat:
            from collections import Counter
            cells = Counter((round(x*r.width()/6), round(y*r.height()/6)) for x,y in self.points)
            for (x,y), count in cells.items():
                p.setPen(QPen(QColor('#fff3da'), .8))
                p.setBrush(QColor(255, 64, 28, min(245, 185+count*12)))
                radius = min(4.5, 2.6+count*.35)
                p.drawEllipse(QPointF(r.x()+x*6, r.y()+y*6), radius, radius)
        if self.selected:
            x,y=self.selected;p.setPen(QPen(QColor('#63ffe1'),2));p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(r.x()+x*r.width()-7,r.y()+y*r.height()-7,14,14))
    def wheelEvent(self,event):
        before=self.area();pos=event.position()
        nx=(pos.x()-before.x())/max(before.width(),1);ny=(pos.y()-before.y())/max(before.height(),1)
        self.zoom=max(1.,min(12.,self.zoom*(1.2 if event.angleDelta().y()>0 else 1/1.2)))
        after=self.area();self.pan=(self.pan[0]+pos.x()-after.x()-nx*after.width(),self.pan[1]+pos.y()-after.y()-ny*after.height())
        if self.zoom==1:self.pan=(0.,0.)
        self.update();event.accept()
    def mousePressEvent(self,event):self.drag=event.position()
    def mouseMoveEvent(self,event):
        if self.drag is not None:
            delta=event.position()-self.drag;self.pan=(self.pan[0]+delta.x(),self.pan[1]+delta.y());self.drag=event.position();self.update()
    def mouseReleaseEvent(self,event):self.drag=None
    def mouseDoubleClickEvent(self,event):self.zoom=1.;self.pan=(0.,0.);self.update()

class Trend(QWidget):
    def __init__(self):
        super().__init__()
        self.runs = []
        self.setMinimumHeight(280)

    def set_runs(self, runs):
        self.runs = runs
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gap = 16
        width = (self.width() - gap) / 2
        self.draw_chart(painter, QRectF(0, 0, width, self.height()), '通关用时',
                        [run['seconds'] if run['completed'] else None for run in self.runs],
                        QColor('#415ce8'), '暂无通关记录', seconds=True)
        self.draw_chart(painter, QRectF(width+gap, 0, width, self.height()), '死亡次数',
                        [run['deaths'] for run in self.runs], QColor('#168979'), '暂无已结束的记录')

    def draw_chart(self, painter, panel, title, values, color, empty, seconds=False):
        painter.setPen(QColor('#e3e8f0'))
        painter.setBrush(QColor('#ffffff'))
        painter.drawRoundedRect(panel.adjusted(1, 1, -1, -1), 12, 12)
        painter.setPen(QColor('#25324a'))
        painter.drawText(QPointF(panel.x()+18, panel.y()+27), title)
        available = [value for value in values if value is not None]
        if not available:
            painter.setPen(QColor('#687b98'))
            painter.drawText(panel, Qt.AlignmentFlag.AlignCenter, empty)
            return
        plot = panel.adjusted(57, 46, -22, -47)
        step = max(1, (max(available)+3)//4)
        ceiling = step*4
        for tick in range(5):
            value = tick*step
            y = plot.bottom() - value/ceiling*plot.height()
            painter.setPen(QColor('#e8edf5'))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor('#687b98'))
            label_text = f'{value//60}:{value%60:02d}' if seconds else str(value)
            painter.drawText(QRectF(panel.x()+7, y-10, 43, 20),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label_text)
        count = len(values)
        def x_for(index):
            return plot.center().x() if count == 1 else plot.left()+index*plot.width()/(count-1)
        indices = sorted({round(i*(count-1)/min(5,count-1)) for i in range(min(5,count-1)+1)}) if count>1 else [0]
        painter.setPen(QColor('#687b98'))
        for index in indices:
            painter.drawText(QRectF(x_for(index)-17, plot.bottom()+4, 34, 19),
                             Qt.AlignmentFlag.AlignCenter, str(index+1))
        painter.drawText(QRectF(plot.left(), plot.bottom()+23, plot.width(), 19),
                         Qt.AlignmentFlag.AlignCenter, '尝试序号')
        points = [QPointF(x_for(index), plot.bottom()-value/ceiling*plot.height())
                  for index,value in enumerate(values) if value is not None]
        painter.setPen(QPen(color, 2.4))
        for start, end in zip(points, points[1:]):
            painter.drawLine(start, end)
        painter.setBrush(color)
        for point in points:
            painter.drawEllipse(point, 3.4, 3.4)


class CropView(QWidget):
    def __init__(self,frame):
        super().__init__();self.frame=frame;self.start=None;self.end=None
        self.pix=QPixmap.fromImage(__import__('PySide6.QtGui',fromlist=['QImage']).QImage(frame.data,frame.shape[1],frame.shape[0],frame.strides[0],__import__('PySide6.QtGui',fromlist=['QImage']).QImage.Format.Format_RGB888).copy())
        self.setMinimumSize(640,400)
    def area(self):
        scale=min(self.width()/self.pix.width(),self.height()/self.pix.height());return QRectF(0,0,self.pix.width()*scale,self.pix.height()*scale)
    def paintEvent(self,e):
        p=QPainter(self);p.drawPixmap(self.area(),self.pix,QRectF(self.pix.rect()))
        if self.start and self.end:
            p.setPen(QPen(QColor('#5affdc'),2));p.drawRect(QRectF(self.start,self.end).normalized())
    def mousePressEvent(self,e):self.start=e.position();self.end=e.position();self.update()
    def mouseMoveEvent(self,e):self.end=e.position();self.update()
    def mouseReleaseEvent(self,e):self.end=e.position();self.update()
    def crop(self):
        if self.start is None or self.end is None:return None
        r=QRectF(self.start,self.end).normalized().intersected(self.area());scale=self.pix.width()/self.area().width()
        x,y,w,h=[int(v*scale) for v in (r.x(),r.y(),r.width(),r.height())]
        if w<6 or h<6:return None
        return (x,y,w,h),self.frame[y:y+h,x:x+w].copy()

class CropDialog(QDialog):
    def __init__(self,frame,title,parent):
        super().__init__(parent);self.setWindowTitle(title);self.resize(1000,680);v=QVBoxLayout(self)
        v.addWidget(label(title));self.view=CropView(frame);v.addWidget(self.view,1)
        v.addWidget(button('保存识别区域',self.save));self.result_crop=None
    def save(self):
        result=self.view.crop()
        if result is None:return
        self.result_crop=result;self.accept()

class PlatformerApp(QMainWindow):
    def __init__(self,db_path=None):
        super().__init__();QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc');QApplication.instance().setFont(QFont('Microsoft YaHei',10));self.repo=Repository(db_path);self.maps=maps();self.player='Player';self.sid=None;self.point=None;self.children_processes=[];self.capture=WindowCapture();self.detector=None;self.capture_hwnd=None;self.setup_player=None;self.setup_frame=None;self.setup_viewport=None;self.setup_capture_size=None
        self.setWindowTitle('Platformer Analytics · 关卡与玩家分析');self.resize(1380,900)
        self.stack=QStackedWidget();self.setCentralWidget(self.stack)
        self.stack.addWidget(self.login());self.stack.addWidget(self.player_shell());self.stack.addWidget(self.admin_shell())
        self.capture_timer=QTimer(self);self.capture_timer.setInterval(80);self.capture_timer.timeout.connect(self.capture_tick)
        self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.refresh_workspace();self.refresh_admin();polish(self)
        from counting_ui import install_counting
        install_counting(self)
    def page(self,title,subtitle):
        w=QWidget();v=QVBoxLayout(w);v.setContentsMargins(24,22,24,22);v.setSpacing(14)
        v.addWidget(label(title,True));v.addWidget(label(subtitle,muted=True));return w,v
    def login(self):
        page=QWidget();outer=QVBoxLayout(page);outer.setContentsMargins(50,40,50,40);outer.addStretch()
        center=QWidget();center.setMaximumWidth(920);v=QVBoxLayout(center);v.setSpacing(18)
        v.addWidget(text('PLATFORMER  /  ANALYTICS','eyebrow'))
        v.addWidget(text('每一次挑战，都值得被看见。','title'))
        v.addWidget(text('记录游玩过程，探索死亡分布，理解关卡中的每一道挑战。','muted'))
        row=QHBoxLayout();row.setSpacing(24)
        player,l=card('玩家空间');l.addWidget(text('PLAY & REFLECT','eyebrow'));l.addWidget(text('记录一次游玩，在地图中复盘失败，看到自己的进步。','muted'))
        self.name=QLineEdit();self.name.setPlaceholderText('输入你的玩家昵称');l.addWidget(self.name)
        enter=button('进入玩家端  →',self.enter_player);enter.setObjectName('primary');l.addWidget(enter);row.addWidget(player)
        admin,l=card('分析工作区');l.addWidget(text('EXPLORE & UNDERSTAND','eyebrow'));l.addWidget(text('从关卡结构到群体行为，发现值得关注的设计问题。','muted'));l.addStretch()
        l.addWidget(button('进入管理端  →',lambda:self.stack.setCurrentIndex(2)));row.addWidget(admin)
        v.addLayout(row);v.addWidget(text('本地原型 · 通过昵称区分玩家，尚未接入账号认证','muted'))
        outer.addWidget(center,0,Qt.AlignmentFlag.AlignHCenter);outer.addStretch();return page
    def enter_player(self):
        self.player=self.name.text().strip() or 'Player';self.player_identity.setText('当前玩家：'+self.player)
        self.refresh_workspace();self.refresh_review();self.refresh_growth();self.stack.setCurrentIndex(1)
    def shell(self,role,names):
        w=QWidget();h=QHBoxLayout(w);h.setContentsMargins(0,0,0,0);side=QFrame();side.setObjectName('sidebar');side.setFixedWidth(220)
        v=QVBoxLayout(side);v.addWidget(label('PA / '+role,True));v.addSpacing(20);stack=QStackedWidget();nav=[]
        for i,name in enumerate(names):
            b=QPushButton(name);b.setCheckable(True);v.addWidget(b);nav.append(b)
            def go(checked=False,index=i):
                stack.setCurrentIndex(index)
                for j,b in enumerate(nav):b.setChecked(j==index)
                if role=='ADMIN':self.refresh_admin()
                elif index==1:self.refresh_review()
                elif index==2:self.refresh_growth()
            b.clicked.connect(go)
        nav[0].setChecked(True);stack.currentChanged.connect(lambda index: [b.setChecked(j==index) for j,b in enumerate(nav)]);v.addStretch();v.addWidget(button('返回角色入口',self.leave));h.addWidget(side);h.addWidget(stack,1)
        return w,stack,v
    def leave(self):
        if self.sid:self.end_session()
        self.stack.setCurrentIndex(0)
    def player_shell(self):
        w,self.player_pages,v=self.shell('PLAYER',['游玩工作台','单次复盘','个人成长'])
        self.player_identity=label('当前玩家：Player');v.insertWidget(1,self.player_identity)
        page,l=self.page('游玩工作台','I Wanna Maker 自动画面采集：填写关卡 / 滚动房间名称，完成一次识别设置后开始记录。')
        row=QHBoxLayout();self.game=QComboBox();self.game.addItems(self.repo.games());self.game_add=button('+ 游戏',self.add_game);self.level=QComboBox();self.level.setEditable(False);self.level_add=button('+ 添加',self.add_level)
        self.scope=QComboBox();self.scope.addItems(['我的死亡分布','全体玩家死亡分布']);self.heat=QCheckBox('显示热力图');self.heat.setChecked(True)
        for x in [self.game,self.level,self.scope,self.heat]:row.addWidget(x)
        l.addLayout(row);self.status=label('未开始记录');l.addWidget(self.status);self.count_note=label('本次死亡：0 · 已定位：0 · 未定位：0');l.addWidget(self.count_note);row=QHBoxLayout()
        self.start=button('开始记录',self.begin);self.stop=button('停止记录',self.end_session);self.setup_region=button('设置游戏区域',lambda:self.prepare_capture('viewport'));self.setup_alive=button('设置角色识别',lambda:self.prepare_capture('player'));self.setup_dead=button('设置死亡画面',lambda:self.prepare_capture('death'))
        for x in [self.start,self.stop,self.setup_region,self.setup_alive,self.setup_dead]:row.addWidget(x)
        l.addLayout(row);self.canvas=MapCanvas();l.addWidget(self.canvas,1)
        self.map_note=label('',muted=True);l.addWidget(self.map_note);self.player_pages.addWidget(page)
        self.game.currentTextChanged.connect(self.change_player_game);self.level.currentTextChanged.connect(self.refresh_workspace)
        self.scope.currentIndexChanged.connect(self.refresh_workspace);self.heat.toggled.connect(self.toggle_heat);self.change_player_game()
        page,l=self.page('单次复盘','仅显示当前昵称的记录；选择事件可定位地图。')
        self.review_select=QComboBox();l.addWidget(self.review_select)
        self.review_map_caption=label('关卡路线地图',muted=True);l.addWidget(self.review_map_caption)
        self.review_map=MapCanvas();l.addWidget(self.review_map,1)
        self.event_table=table(['经过时间（秒）','事件','位置','来源']);l.addWidget(self.event_table)
        self.review_note=label('',muted=True);l.addWidget(self.review_note);self.review_select.currentIndexChanged.connect(self.show_review)
        self.event_table.cellClicked.connect(self.focus_event);self.player_pages.addWidget(page)
        page,l=self.page('个人成长','跟踪当前关卡的通关用时与死亡次数。未通关的尝试仅计入死亡次数。')
        self.growth_note=label('');l.addWidget(self.growth_note);self.trend=Trend();l.addWidget(self.trend,1)
        self.growth_table=table(['时间','游戏 / 关卡','用时（秒）','死亡次数','结果']);self.growth_table.setMinimumHeight(150);l.addWidget(self.growth_table,1);self.player_pages.addWidget(page)
        return w
    def change_player_game(self,*args):
        profiles=[]
        if self.game.currentText()=='I Wanna Maker':
            for config in (BASE/'capture_profiles').glob('*/config.json'):
                try:profiles.append(json.loads(config.read_text(encoding='utf-8'))['level'])
                except (OSError,ValueError,KeyError):pass
        self.level.blockSignals(True);self.level.clear();self.level.addItems(list(self.maps) if self.game.currentText()==MARIO else (sorted(set(profiles+self.repo.levels(self.game.currentText())),key=str.casefold)));self.level.blockSignals(False);self.level.setPlaceholderText('请先添加关卡 / 房间');self.refresh_workspace()
    def add_game(self):
        if self.sid:
            return
        name, accepted = QInputDialog.getText(self, '添加游戏', '游戏名称')
        if not accepted:
            return
        try:
            name = self.repo.add_game(name)
        except ValueError as error:
            QMessageBox.information(self, '名称无效', str(error))
            return
        for picker in (self.game, self.admin_game):
            if picker.findText(name) < 0:
                picker.addItem(name)
        self.game.setCurrentText(name)
    def add_level(self):
        if self.sid or self.game.currentText()==MARIO:return
        name,ok=QInputDialog.getText(self,'添加关卡 / 房间','名称（例如：1-2 或 1-2 / 房间 A）')
        if not ok:return
        try:
            selected=self.repo.add_level(self.game.currentText(),name)
        except ValueError as error:
            QMessageBox.information(self,'名称无效',str(error));return
        self.change_player_game();self.level.setCurrentText(selected)
        self.setup_player=None;self.setup_frame=None;self.setup_viewport=None
        self.status.setText('已选择 '+selected+'；已有识别配置可直接记录，否则请先完成识别设置')
    def toggle_heat(self,on):self.canvas.heat=on;self.canvas.update()
    def scene_path(self,game,level,map_id=None):
        if game==MARIO:return self.maps.get(level)
        if game=='I Wanna Maker':
            folder=self.repo.map_folder(level,map_id)
            p=folder/'atlas.png' if folder else config_dir(level)/'scene.png'
            return p if p.exists() else None
        return None
    def prepare_capture(self,kind):
        if self.sid:return
        if self.game.currentText()!='I Wanna Maker':
            self.status.setText('当前自动采集仅支持 I Wanna Maker');return
        if self.level.currentText()=='请填写关卡与房间名称' or not self.level.currentText().strip():
            self.status.setText('请先填写实际关卡和房间名称');return
        self.status.setText('5 秒后采集：请切到游戏前台，'+('保持正常游戏画面' if kind=='viewport' else ('让角色保持静止' if kind=='player' else '停留在死亡画面')))
        for b in [self.setup_region,self.setup_alive,self.setup_dead,self.start]:b.setEnabled(False)
        QTimer.singleShot(5000,lambda:self.capture_setup(kind))
    def capture_setup(self,kind):
        try:
            windows=self.capture.windows()
            if not windows:raise RuntimeError('未找到 I Wanna Maker 游戏窗口，请先启动游戏')
            frame=self.capture.grab(windows[0][0])
            full_size=(frame.shape[1],frame.shape[0])
            if kind!='viewport':
                if self.setup_viewport is None:raise RuntimeError('请先设置游戏区域，排除右侧信息栏和窗口边框')
                if full_size!=self.setup_capture_size:raise RuntimeError('窗口尺寸已改变，请重新设置游戏区域')
                x,y,w,h=self.setup_viewport;frame=frame[y:y+h,x:x+w]
            dialog=CropDialog(frame,'框选实际游戏区域，排除右侧信息栏' if kind=='viewport' else '框选角色本体（紧贴轮廓）' if kind=='player' else '框选死亡时独有的文字或图案（不包含角色）',self)
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            rect,crop=dialog.result_crop
            if kind=='viewport':
                self.setup_viewport=rect;self.setup_capture_size=full_size;self.setup_player=None;self.status.setText('游戏区域已设置，继续设置角色识别')
            elif kind=='player':
                self.setup_player=crop;self.setup_frame=frame;self.setup_level=self.level.currentText();self.status.setText('角色样本已设置；继续设置死亡画面')
            else:
                if self.setup_player is None or self.setup_level!=self.level.currentText():raise RuntimeError('请先设置当前房间的角色识别')
                if frame.shape!=self.setup_frame.shape:raise RuntimeError('窗口大小发生变化，请重新设置角色')
                save_profile(self.level.currentText(),self.setup_player,crop,rect,(frame.shape[1],frame.shape[0]),self.setup_frame,self.setup_viewport,self.setup_capture_size)
                self.status.setText('识别设置已保存；重生后点击开始记录，再切回游戏')
        except (RuntimeError,OSError,ValueError) as e:self.status.setText(str(e))
        finally:self.setup_alive.setEnabled(True);self.setup_dead.setEnabled(True);self.refresh_workspace()
    def capture_tick(self):
        if not self.sid or self.detector is None:return
        try:
            frame=self.capture.grab(self.capture_hwnd);result=self.detector.process(frame)
            self.status.setText('自动采集 · '+result['status'])
            if result.get('death'):
                self.repo.event(self.sid,int(time.monotonic()-self.started),'死亡',None,world_point=result.get('world_point'))
                self.detector.mapper.save(force=True);self.refresh_workspace()
            else:self.detector.mapper.save()
        except (RuntimeError,OSError,ValueError) as e:
            self.detector.reset();self.detector.mapper.lose();self.status.setText(str(e))

    def refresh_workspace(self,*args):
        if not hasattr(self,'canvas'):return
        g,lv=self.game.currentText(),self.level.currentText();owner=self.player if self.scope.currentIndex()==0 else None
        sid=self.sid or getattr(self,'last_sid',None)
        current=[s for s in self.repo.sessions(self.player,g,lv) if s['id']==sid]
        events=[e for e in self.repo.events(sid) if e['type']=='死亡'] if current else []
        located=sum(e.get('world_x') is not None or e.get('x') is not None for e in events)
        update_player(self,len(events),located)
        self.count_note.setText(f'本次死亡：{len(events)} · 已定位：{located} · 未定位：{len(events)-located}（未定位也计入死亡总数）')
        points=self.repo.points(g,lv,owner);self.canvas.set_data(self.scene_path(g,lv),points);self.point=None
        self.map_note.setText(f'定位死亡记录：{len(points)} 条 · 滚轮缩放、拖动地图、双击复位；颜色越浓表示记录越多。' if points else '暂无自动定位死亡记录。支持同一房间横向 / 纵向滚动；切换独立房间请另设房间名称。')
        self.level_add.setEnabled(not self.sid and g!=MARIO)
        self.start.setEnabled(not self.sid and bool(lv))
        self.stop.setEnabled(bool(self.sid))
        for b in [self.setup_region,self.setup_alive,self.setup_dead]:b.setEnabled(not self.sid and g=='I Wanna Maker' and bool(lv))
    def begin(self):
        if self.sid:return
        if self.game.currentText()!='I Wanna Maker':
            self.status.setText('当前自动采集仅支持 I Wanna Maker；其他游戏尚未适配');return
        if not self.level.currentText():
            self.status.setText('请先添加并选择关卡 / 房间');return
        self.detector=load_profile(self.level.currentText())
        if self.detector is None:
            self.status.setText('请先完成角色和死亡画面的识别设置');return
        windows=self.capture.windows()
        if not windows:self.status.setText('未找到 I Wanna Maker，请先启动游戏');return
        self.capture_hwnd=windows[0][0]
        self.sid=self.repo.start(self.player,self.game.currentText(),self.level.currentText(),'自动画面识别',capture_map=self.detector.mapper.map_id)
        self.last_sid=self.sid
        self.started=time.monotonic();self.game.setEnabled(False);self.level.setEnabled(False)
        self.capture_timer.start();self.refresh_workspace();self.status.setText('等待游戏前台画面')
    def tick(self):pass
    def end_session(self,completed=False):
        if not self.sid:return
        if self.detector and self.detector.mapper:self.detector.mapper.save(force=True)
        elapsed=int(time.monotonic()-self.started)
        if completed:self.repo.event(self.sid,elapsed,'通关')
        self.repo.finish(self.sid,elapsed,completed);self.sid=None;self.timer.stop();self.capture_timer.stop();self.status.setText('本轮已通关' if completed else '本轮已停止')
        self.game.setEnabled(True);self.level.setEnabled(True);self.refresh_workspace()
    def refresh_review(self):
        self.review_select.blockSignals(True);self.review_select.clear()
        for s in self.repo.sessions(self.player):self.review_select.addItem(f"{s['started']} · {s['game']} / {s['level']} · {s['status']}",s['id'])
        self.review_select.blockSignals(False);self.show_review()
    def show_review(self,*args):
        sid=self.review_select.currentData();sessions={s['id']:s for s in self.repo.sessions(self.player)};s=sessions.get(sid);self.review_events=[]
        if not s:
            fill(self.event_table, [])
            self.review_map.set_data()
            self.review_map_caption.setText('关卡路线地图')
            self.review_note.setText('暂无个人会话，请先在工作台记录一次游玩。')
            return
        self.review_session = s
        self.review_events = self.repo.events(sid)
        level_sessions = self.repo.sessions(self.player, s['game'], s['level'])
        route_root = (BASE/'route_maps').resolve()
        route = review_route(self.repo, route_root, level_sessions)
        self.review_uses_route = route is not None
        if self.review_uses_route:
            self.review_map_caption.setText(f"{s['game']} · {s['level']} · 路线地图")
            self.review_route_key = route.relative_to(route_root).as_posix()
            points = route_deaths(self.review_events, self.review_route_key)
            self.review_map.set_data(route, points)
            self.review_map_caption.setText(f"{s['game']} · {s['level']} · 死亡热力图 · {len(points)} 个已确认角色位置")
        else:
            if s['game'] == 'I Wanna Maker' and not s.get('capture_map'):
                path = config_dir(s['level'])/'scene.png'
            else:
                path = self.scene_path(s['game'], s['level'], s.get('capture_map'))
            self.review_map_caption.setText(f"{s['game']} · {s['level']} · 关卡地图")
            self.review_map.set_data(path, self.repo.points(s['game'], s['level'], self.player, sid))
        fill(self.event_table,[(e['elapsed'],e['type'],f"房间坐标 {e['world_x']:.0f}, {e['world_y']:.0f} px" if e.get('world_x') is not None else (('已定位到画面范围' if e.get('area_width') is not None else f"{'路线图' if e.get('route_map') else '旧屏幕'}坐标 {e['x']:.1%}, {e['y']:.1%}") if e['x'] is not None else '未定位'),s['source']) for e in self.review_events])
        self.review_note.setText(f"用时 {s['seconds']} 秒 · 死亡 {s['deaths']} 次 · {s['status']} · {s['source']}")
    def focus_event(self,row,col):
        if not 0 <= row < len(self.review_events):
            return
        event = self.review_events[row]
        if self.review_uses_route:
            point = (event['x'], event['y']) if event.get('route_map') == self.review_route_key and event['x'] is not None and event.get('area_width') is None else None
        else:
            point = self.repo.display_point(event, self.review_session)
        self.review_map.selected = point
        self.review_map.update()
    def refresh_growth(self):
        game, level = self.game.currentText(), self.level.currentText()
        sessions = self.repo.sessions(self.player, game, level)
        finished = [session for session in sessions if session['status'] != '记录中']
        completed = sum(session['completed'] for session in finished)
        self.growth_note.setText(f'{game} / {level or "请先选择关卡"} · 已结束 {len(finished)} 次 · 通关 {completed} 次')
        chronological = list(reversed(finished))
        self.trend.set_runs(chronological)
        fill(self.growth_table, [(run['started'], game+' / '+level, run['seconds'], run['deaths'], run['status'])
                                 for run in finished])
    def admin_shell(self):
        w,self.admin_pages,v=self.shell('ADMIN',['数据总览','关卡分析','玩家行为','关卡对比','数据管理'])
        self.admin_source = QComboBox()
        self.admin_source.addItems(['实际采集','模拟生成','手动演示'])
        v.insertWidget(v.count()-2, label('统计数据来源', muted=True))
        v.insertWidget(v.count()-2, self.admin_source)
        self.admin_source.currentTextChanged.connect(self.refresh_admin)
        page,l=self.page('数据总览','先看当前游戏的样本量与关卡表现。点击关卡可查看详细分析。')
        self.admin_game=QComboBox();self.admin_game.addItems(['请选择游戏']+self.repo.games());l.addWidget(self.admin_game)
        self.overview_text=label('请选择游戏');l.addWidget(self.overview_text)
        self.overview_levels=table(['关卡','已结束记录','通关率','通关用时中位数','死亡发生率'])
        self.overview_levels.cellClicked.connect(self.open_overview_level)
        l.addWidget(self.overview_levels,1)
        self.mario_panel=QWidget();ml=QVBoxLayout(self.mario_panel);ml.addWidget(label('超级马里奥 · VGLC 地图数据',True))
        ml.addWidget(label('已接入本地关卡图片。图块差异用于结构分析，不等同于真实游玩难度。',muted=True))
        self.map_table=table(['关卡','宽度（px）','高度（px）']);ml.addWidget(self.map_table)
        ml.addWidget(button('查看选中关卡',self.open_level));ml.addWidget(button('打开原有完整图块分析',self.open_legacy));l.addWidget(self.mario_panel);l.addStretch();self.admin_pages.addWidget(page)
        page,l=self.page('关卡分析','查看某一关的通关表现，再结合路线图和热点检查玩家卡在哪里。')
        self.admin_level=QComboBox();l.addWidget(self.admin_level)
        self.level_metrics=label('');l.addWidget(self.level_metrics)
        tabs = QTabWidget()
        map_page = QWidget();map_layout = QVBoxLayout(map_page)
        self.admin_map = MapCanvas();map_layout.addWidget(self.admin_map,1)
        self.level_text = label('');map_layout.addWidget(self.level_text)
        tabs.addTab(map_page,'关卡地图')
        sample_page = QWidget();sample_layout = QVBoxLayout(sample_page)
        self.admin_sample_picker = QComboBox();sample_layout.addWidget(self.admin_sample_picker)
        self.admin_sample_view = MapCanvas();self.admin_sample_view.heat=False
        self.admin_sample_view.empty_text = '该关卡暂无玩家端截图'
        sample_layout.addWidget(self.admin_sample_view,1)
        self.admin_sample_note = label('',muted=True);sample_layout.addWidget(self.admin_sample_note)
        self.admin_sample_picker.currentIndexChanged.connect(self.show_admin_screenshot)
        tabs.addTab(sample_page,'玩家截图')
        l.addWidget(tabs,1);self.admin_pages.addWidget(page)
        page,l=self.page('玩家行为','查看谁在哪一关卡住。选择一条游玩记录，检查死亡和通关事件的时间。')
        self.behavior=table(['玩家','关卡','时间','用时（秒）','死亡','结果','来源']);l.addWidget(self.behavior,1)
        self.behavior_note=label('选择一条游玩记录查看事件。',muted=True);l.addWidget(self.behavior_note)
        self.behavior_events=table(['经过时间（秒）','事件','地图位置']);self.behavior_events.setMinimumHeight(145)
        l.addWidget(self.behavior_events,1)
        self.behavior.currentCellChanged.connect(self.show_behavior_events)
        self.admin_pages.addWidget(page)
        page,l=self.page('关卡对比','用相同数据来源比较两关表现，再看路线和死亡热点。')
        selector_row = QHBoxLayout()
        self.compare_a, self.compare_b = QComboBox(), QComboBox()
        self.compare_map_a, self.compare_map_b = MapCanvas(), MapCanvas()
        self.compare_note_a, self.compare_note_b = label('', muted=True), label('', muted=True)
        for caption, picker in (('关卡 A',self.compare_a),('关卡 B',self.compare_b)):
            selector_row.addWidget(label(caption,muted=True))
            selector_row.addWidget(picker,1)
        l.addLayout(selector_row)
        self.compare_table = table(['指标','关卡 A','关卡 B'])
        self.compare_table.setMinimumHeight(235)
        self.compare_table.setMaximumHeight(255)
        l.addWidget(self.compare_table)
        l.addWidget(label('死亡发生率 = 至少死亡一次的记录 / 已结束记录。用时中位数仅统计已通关记录。', muted=True))
        row = QHBoxLayout()
        for canvas, note in ((self.compare_map_a,self.compare_note_a),(self.compare_map_b,self.compare_note_b)):
            panel, content = card()
            canvas.setMinimumSize(280, 145)
            canvas.empty_text = '该关卡暂无采集画面'
            content.addWidget(canvas, 1)
            content.addWidget(note)
            row.addWidget(panel, 1)
        l.addLayout(row, 1)
        self.admin_pages.addWidget(page)
        page,l=self.page('数据管理','检查来源、未结束的记录和缺失坐标，再导出当前筛选范围。')
        self.data_text=label('');l.addWidget(self.data_text);l.addWidget(button('刷新数据检查',self.refresh_admin));l.addWidget(button('导出当前游戏和来源 CSV',self.export_sessions))
        l.addWidget(button('打开超级马里奥图块标注',self.open_legacy));l.addWidget(label('地图可来自玩家端路线截图或 VGLC。死亡未定位时仍计数，热力图只显示有坐标的事件。',muted=True));l.addStretch();self.admin_pages.addWidget(page)
        self.admin_game.currentTextChanged.connect(self.change_admin_game);self.admin_level.currentTextChanged.connect(self.refresh_level)
        self.compare_a.currentTextChanged.connect(self.refresh_compare);self.compare_b.currentTextChanged.connect(self.refresh_compare);return w
    def change_admin_game(self,*args):
        levels=list(self.maps) if self.admin_game.currentText()==MARIO else self.admin_levels(self.admin_game.currentText())
        for combo in [self.admin_level,self.compare_a,self.compare_b]:
            combo.blockSignals(True);combo.clear();combo.addItems(levels);combo.blockSignals(False)
        if len(levels)>1:self.compare_b.setCurrentIndex(1)
        self.refresh_admin()
    def refresh_admin(self,*args):
        if not hasattr(self,'data_text'):return
        game = self.admin_game.currentText()
        is_mario = game == MARIO
        all_runs = self.repo.sessions(game=game)
        runs = self.admin_runs(game)
        summary = summarize_runs(runs)
        update_admin(self, summary['count'], rate(summary['cleared'], summary['count']), duration_text(summary['median_time']))
        self.mario_panel.setVisible(is_mario)
        source = self.admin_source.currentText()
        if game == '请选择游戏':
            self.overview_text.setText(game)
        else:
            self.overview_text.setText(f'{game} · {source} · {len(runs)} 条记录，含 {sum(run["status"]=="记录中" for run in runs)} 条记录中')
        overview_rows = []
        for level in sorted({run['level'] for run in runs}, key=str.casefold):
            level_stats = summarize_runs([run for run in runs if run['level']==level])
            count = level_stats['count']
            overview_rows.append((level, count, rate(level_stats['cleared'],count), duration_text(level_stats['median_time']), rate(level_stats['with_death'],count)))
        fill(self.overview_levels, overview_rows)
        self.overview_levels.setVisible(bool(overview_rows))
        if is_mario:
            fill(self.map_table,[(lv,analyze(str(p))['width'],analyze(str(p))['height']) for lv,p in self.maps.items()])
            if not self.admin_level.count() and self.maps:
                self.admin_level.blockSignals(True);self.admin_level.addItems(list(self.maps));self.admin_level.blockSignals(False)
        levels = list(self.maps) if is_mario else self.admin_levels(game)
        for picker in (self.admin_level, self.compare_a, self.compare_b):
            if [picker.itemText(i) for i in range(picker.count())] == levels:
                continue
            selected = picker.currentText()
            picker.blockSignals(True)
            picker.clear()
            picker.addItems(levels)
            if selected in levels:
                picker.setCurrentText(selected)
            elif picker is self.compare_b and len(levels) > 1:
                picker.setCurrentIndex(1)
            picker.blockSignals(False)
        self.behavior_rows = runs
        self.behavior.blockSignals(True)
        fill(self.behavior, [(r['player'],r['level'],r['started'],r['seconds'],r['deaths'],r['status'],r['source']) for r in runs])
        self.behavior.clearSelection()
        self.behavior.setCurrentCell(-1,-1)
        self.behavior.blockSignals(False)
        self.show_behavior_events(-1)
        events = [event for run in runs for event in self.repo.events(run['id']) if event['type']=='死亡']
        located = sum(event.get('world_x') is not None or (event.get('x') is not None and event.get('area_width') is None) for event in events)
        source_counts = ', '.join(f'{name} {sum(r["source"]==name for r in all_runs)} 条' for name in sorted({r['source'] for r in all_runs}))
        self.data_text.setText(f'{game} · {source}\n全部来源：{source_counts or "暂无记录"}\n当前筛选：{len(runs)} 条记录，{len(runs)-summary["count"]} 条未纳入统计\n死亡坐标：{located}/{len(events)} 条已定位')
        self.refresh_level();self.refresh_compare()

    def admin_runs(self, game, level=None):
        source = self.admin_source.currentText()
        sources = ('截图样本计数','自动画面识别') if source == '实际采集' else (source,)
        return [run for run in self.repo.sessions(game=game, level=level) if run['source'] in sources]

    def show_behavior_events(self, row, *_):
        rows = getattr(self,'behavior_rows',[])
        if not 0 <= row < len(rows):
            fill(self.behavior_events, [])
            self.behavior_note.setText('选择一条游玩记录查看事件。')
            return
        run = rows[row]
        events = self.repo.events(run['id'])
        fill(self.behavior_events, [(event['elapsed'], event['type'], '已定位' if event.get('x') is not None or event.get('world_x') is not None else '—') for event in events])
        self.behavior_note.setText(f"{run['player']} · {run['level']} · {run['source']} · {len(events)} 条事件")

    def open_overview_level(self, row, *_):
        item = self.overview_levels.item(row,0)
        if item:
            self.admin_level.setCurrentText(item.text())
            self.admin_pages.setCurrentIndex(1)

    def open_level(self):
        row=self.map_table.currentRow();row=max(0,row)
        if row<self.map_table.rowCount():self.admin_level.setCurrentText(self.map_table.item(row,0).text());self.admin_pages.setCurrentIndex(1)
    def admin_levels(self, game):
        return sorted(set(self.repo.levels(game)) | screenshot_levels(game), key=str.casefold)

    def show_admin_screenshot(self, *_):
        screenshot = self.admin_sample_picker.currentData()
        self.admin_sample_view.set_data(screenshot['path'] if screenshot else None)
        if screenshot:
            source = screenshot['player'] or '历史样本'
            stamp = (screenshot['captured'] or '').replace('T',' ')
            self.admin_sample_note.setText(f"{source} · {stamp} · {'完整截图' if screenshot['full'] else '识别区域'}")
        else:
            self.admin_sample_note.setText('玩家端采样后会自动关联到此游戏和关卡。')

    def refresh_level(self,*args):
        game, level = self.admin_game.currentText(), self.admin_level.currentText()
        values = run_metric_rows(summarize_runs(self.admin_runs(game, level))) if level else []
        self.level_metrics.setText('  ·  '.join(f'{name} {value}' for name,value in values) or '请选择关卡')
        screenshots = screenshot_entries(game, level)
        previous = self.admin_sample_picker.currentData()
        self.admin_sample_picker.blockSignals(True)
        self.admin_sample_picker.clear()
        names = {'normal':'正常', 'death':'死亡', 'complete':'通关'}
        counts = {kind:0 for kind in names}
        for screenshot in screenshots:
            kind = screenshot['kind'];counts[kind] += 1
            self.admin_sample_picker.addItem(f'{names[kind]}样本 {counts[kind]}', screenshot)
        if previous:
            index = self.admin_sample_picker.findData(previous)
            if index >= 0:self.admin_sample_picker.setCurrentIndex(index)
        self.admin_sample_picker.blockSignals(False)
        self.show_admin_screenshot()
        path, points, source = self.admin_level_visual(game, level, screenshots)
        self.admin_map.set_data(path, points)
        if path and source == 'VGLC 地图':
            metrics = analyze(str(path))
            self.level_text.setText(f"{level} · {source} · {metrics['width']} × {metrics['height']} px · {metrics['types']} 种图块")
        elif path:
            self.level_text.setText(f'{level} · {source} · {len(points)} 个已确认角色位置')
        else:
            self.level_text.setText('该关卡暂无采集画面')

    def admin_level_visual(self, game, level, screenshots=None):
        if not level:
            return None, [], '暂无画面'
        sessions = self.repo.sessions(game=game, level=level)
        root = (BASE/'route_maps').resolve()
        route = review_route(self.repo, root, sessions)
        if route:
            key = route.relative_to(root).as_posix()
            filtered_sessions = self.admin_runs(game, level)
            events = [event for session in filtered_sessions for event in self.repo.events(session['id'])]
            points = route_deaths(events, key)
            return route, points, '玩家端路线图'
        if screenshots is None:
            screenshots = screenshot_entries(game, level)
        normal = next((item for item in screenshots if item['kind']=='normal' and item['full']), None)
        if normal:
            return normal['path'], [], '玩家端正常截图'
        path = self.scene_path(game, level)
        if path:
            source = 'VGLC 地图' if game == MARIO else '已有识别地图'
            return path, self.repo.points(game, level) if self.admin_source.currentText()=='实际采集' else [], source
        crop = next((item for item in screenshots if item['kind']=='normal'), None)
        return (crop['path'], [], '玩家端正常样本局部') if crop else (None, [], '暂无画面')

    def refresh_compare(self,*args):
        game = self.admin_game.currentText()
        compared = []
        for picker, canvas, note in ((self.compare_a,self.compare_map_a,self.compare_note_a),
                                     (self.compare_b,self.compare_map_b,self.compare_note_b)):
            level = picker.currentText()
            path, points, source = self.admin_level_visual(game, level)
            canvas.set_data(path, points)
            note.setText(f'{level} · {source}' if level else '请选择关卡')
            compared.append(run_metric_rows(summarize_runs(self.admin_runs(game, level))) if level else [])
        self.compare_table.setHorizontalHeaderLabels(['指标',self.compare_a.currentText() or '关卡 A',self.compare_b.currentText() or '关卡 B'])
        metrics = [name for name,_ in run_metric_rows(summarize_runs([]))]
        a, b = (dict(column) for column in compared)
        fill(self.compare_table, [(name,a.get(name,'—'),b.get(name,'—')) for name in metrics])
    def open_legacy(self):
        if self.admin_game.currentText()!=MARIO:
            QMessageBox.information(self,'选择游戏','请先在数据总览选择超级马里奥。');return
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        if any(p.poll() is None for p in self.children_processes):
            QDesktopServices.openUrl(QUrl('http://localhost:8501'));return
        try:
            p=subprocess.Popen([sys.executable,'-m','streamlit','run',str(BASE/'main.py'),'--server.port','8501'],cwd=str(BASE),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));self.children_processes.append(p)
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QTimer.singleShot(2500,lambda:QDesktopServices.openUrl(QUrl('http://localhost:8501')))
        except OSError as e:QMessageBox.warning(self,'无法打开',str(e))
    def export_sessions(self):
        path,_=QFileDialog.getSaveFileName(self,'导出会话','sessions.csv','CSV (*.csv)')
        if path:
            rows=self.admin_runs(self.admin_game.currentText());keys=['id','player','game','level','started','seconds','completed','status','source','capture_map','deaths']
            try:
                with open(path,'w',encoding='utf-8-sig',newline='') as f:
                    writer=csv.DictWriter(f,keys);writer.writeheader();writer.writerows(rows)
            except OSError as e:QMessageBox.warning(self,'导出失败',str(e))
    def closeEvent(self,e):
        self.end_session()
        for p in self.children_processes:
            if p.poll() is None:p.terminate()
        self.repo.db.close();e.accept()

if __name__=='__main__':
    app=QApplication(sys.argv);app.setStyleSheet(STYLE);window=PlatformerApp();window.show();sys.exit(app.exec())
