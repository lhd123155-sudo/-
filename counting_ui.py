import ctypes,time
from types import MethodType
from PySide6.QtCore import QTimer,Qt
from PySide6.QtGui import QImage,QPixmap
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QLabel,QDialog,QPushButton,QSizePolicy
from analytics_data import BASE
from route_capture import RouteRecorder
from route_heat import HeatLocator, sprite_templates, review_route
from sample_counter import SampleCounter,recording_samples,save_sample,KINDS,normalize_frame
from ui_design import card,text,detach

class CountingWorkspace:
    def select_windows(self):
        game = self.game.currentText()
        same_game = getattr(self, 'window_game', None) == game
        old = self.window_picker.currentData() if same_game else None
        self.window_game = game
        self.window_picker.clear()
        self.window_picker.addItem('请选择游戏窗口', None)
        keywords = {'Celeste（蔚蓝）': ('celeste', '蔚蓝'), '超级马里奥': ('super mario', '超级马里奥'),
                    'Sheepy: A Short Adventure': ('sheepy',)}
        hints = keywords.get(game, (game.casefold(),))
        matches = []
        for hwnd, title in self.capture.windows(title_hint=None):
            self.window_picker.addItem(title, hwnd)
            if any(hint in title.casefold() for hint in hints):
                matches.append(hwnd)
        index = self.window_picker.findData(old) if old else -1
        if index < 0 and len(matches) == 1:
            index = self.window_picker.findData(matches[0])
        if index >= 0:
            self.window_picker.setCurrentIndex(index)
    def take_sample(self,kind):
        if getattr(self,'sample_busy',False):return
        if self.sid:self.status.setText('请先停止记录再采集样本');return
        if not self.level.currentText():self.status.setText('请先添加并选择关卡');return
        hwnd=self.window_picker.currentData()
        if not hwnd:self.status.setText('请刷新并选择游戏窗口');return
        self.sample_busy=True
        try:
            frame=self.capture.grab(hwnd)
            save_sample(self.game.currentText(),self.level.currentText(),kind,frame,player=self.player)
            self.status.setText('样本已保存，可继续添加不同状态的样本');self.refresh_workspace()
        except (RuntimeError,OSError,ValueError) as error:self.status.setText(str(error))
        finally:self.sample_busy=False
    def delayed_sample(self,kind):
        self.status.setText('3 秒后截图，请切回选中的游戏窗口')
        QTimer.singleShot(3000,lambda:self.take_sample(kind))
    def poll_shortcuts(self):
        user=ctypes.windll.user32
        user.GetForegroundWindow.restype=ctypes.c_void_p
        selected=self.window_picker.currentData()
        if self.stack.currentIndex()!=1 or not selected or user.GetForegroundWindow()!=selected or getattr(self,'sample_busy',False):
            return
        if self.sid and self.game.currentText()=='I Wanna Maker' and user.GetAsyncKeyState(0x52)&0x8000:
            self.reload_until = time.monotonic()+.30
        for key,kind in [(0x41,'normal'),(0x53,'death'),(0x44,'complete'),(0x45,'map'),(0x46,'toggle')]:
            held=bool(user.GetAsyncKeyState(0x12)&0x8000) and bool(user.GetAsyncKeyState(key)&0x8000)
            if held and key not in self.held_keys:
                self.held_keys.add(key)
                if kind=='toggle':self.end_session() if self.sid else self.begin()
                elif kind=='map':self.toggle_route()
                else:self.take_sample(kind)
            if held:self.held_keys.add(key)
            else:self.held_keys.discard(key)
    def toggle_route(self):
        self.record_route = not self.record_route
        self.route_state.setText('地图截取：开启 · Alt+E' if self.record_route else '地图截取：暂停 · Alt+E')
    def begin(self):
        if self.sid:return
        game, level = self.game.currentText(), self.level.currentText()
        if not level:
            self.status.setText('请先添加并选择关卡');return
        samples, size, bounds, shared = recording_samples(game, level)
        if not size or not samples['normal'] or not(samples['death'] or samples['complete']):
            self.status.setText('请先采集正常样本，以及死亡或通关样本');return
        hwnd=self.window_picker.currentData()
        if not hwnd:self.status.setText('请先选择游戏窗口');return
        self.capture_size = size
        self.capture_bounds = bounds
        self.detector = SampleCounter(samples, size, self.capture_bounds)
        self.capture_hwnd = hwnd
        self.recording_profile = samples, shared
        route_root = (BASE/'route_maps').resolve()
        previous = review_route(self.repo, route_root, self.repo.sessions(self.player, game, level))
        template = sprite_templates(game, level) if previous else []
        self.heat_locator = HeatLocator(previous, game, level, template) if template else None
        self.sid=self.repo.start(self.player,self.game.currentText(),self.level.currentText(),'截图样本计数');self.last_sid=self.sid
        self.route=RouteRecorder(BASE/'route_maps'/self.sid,self.game.currentText(),self.level.currentText())
        self.route_error=None
        self.reload_until = 0.
        self.started=time.monotonic();self.game.setEnabled(False);self.level.setEnabled(False);self.window_picker.setEnabled(False)
        self.capture_timer.start(60);self.status.setText('计数已开始，请切回游戏；Alt+F 停止');self.refresh_workspace()
    def end_session(self,completed=False):
        if not self.sid:return
        events=self.repo.events(self.sid);complete=any(e['type']=='通关' for e in events)
        elapsed = int(time.monotonic()-self.started)
        self.capture_timer.stop()
        if self.heat_locator is not None:
            self.heat_locator.close()
            self.save_heat_rechecks()
            self.heat_locator = None
        self.repo.finish(self.sid,elapsed,complete);self.sid=None
        try:
            self.route.finish()
        except Exception as error:
            self.route_error=str(error)
        self.game.setEnabled(True);self.level.setEnabled(True);self.window_picker.setEnabled(True)
        summary = '已通关，记录已自动保存' if complete else '计数已保存'
        if self.route_error:
            self.status.setText(summary+'，地图处理失败：'+self.route_error)
        elif self.route.segment:
            self.status.setText(f'{summary}，生成 {self.route.segment} 张地图')
        else:
            self.status.setText(summary+'，未取得可拼接的游玩画面')
        self.refresh_workspace()
    def save_heat_rechecks(self):
        if self.heat_locator is None:
            return
        key = self.heat_locator.path.relative_to((BASE/'route_maps').resolve()).as_posix()
        for event_id, point in self.heat_locator.completed_rechecks():
            self.repo.set_route_point(self.sid, event_id, point, key)
    def capture_tick(self):
        if not self.sid:return
        try:
            self.save_heat_rechecks()
            raw_frame = self.capture.grab(self.capture_hwnd)
            frame = normalize_frame(raw_frame, self.capture_size, self.capture_bounds)
            reloading = time.monotonic() < self.reload_until
            result = self.detector.process(frame, reloading=True) if reloading else self.detector.process(frame)
            self.status.setText(result['status'])
            scores=result.get('scores',{});self.score_note.setText('匹配度   正常 {:.0%}   /   死亡 {:.0%}   /   通关 {:.0%}'.format(*(scores.get(k,0) for k in KINDS)))
            now = time.monotonic()
            event = result.get('event')
            if event:
                elapsed = int(now - self.started)
                point = None
                route_key = None
                if event == 'death' and self.heat_locator is not None:
                    try:
                        point = self.heat_locator.death_point(now)
                    except (OSError, ValueError, RuntimeError):
                        self.heat_locator.invalidate(now)
                    if point is not None:
                        route_key = self.heat_locator.path.relative_to((BASE/'route_maps').resolve()).as_posix()
                event_id = self.repo.event(self.sid, elapsed, '通关' if event == 'complete' else '死亡', point=point, route_map=route_key)
                if event == 'death' and self.heat_locator is not None:
                    if point is None:
                        self.heat_locator.recheck_death(event_id, now)
                    else:
                        self.heat_locator.recent.clear()
                if event == 'complete':
                    self.end_session()
                    return
                self.refresh_workspace()
            if self.heat_locator is not None and event is None:
                if reloading:
                    self.heat_locator.invalidate(now)
                    self.heat_locator.recent.clear()
                elif max(scores.get('death',0), scores.get('complete',0)) < .91:
                    self.heat_locator.remember(frame, now)
            if result['status']=='游玩中' and self.heat_locator is not None:
                try:
                    self.heat_locator.offer(frame, now)
                except (OSError, ValueError, RuntimeError):
                    self.heat_locator.invalidate(now)
            if result['status']=='游玩中' and self.record_route and not self.route_error:
                try:
                    self.route.offer(frame)
                except Exception as error:
                    self.route_error=str(error)
            if time.monotonic()-self.preview_time>.25:
                self.preview_time=time.monotonic();image=QImage(frame.data,frame.shape[1],frame.shape[0],frame.strides[0],QImage.Format.Format_RGB888).copy()
                self.count_preview.setPixmap(QPixmap.fromImage(image).scaled(self.count_preview.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            if time.monotonic()-self.stats_time>1:self.stats_time=time.monotonic();self.refresh_workspace()
        except (RuntimeError,OSError,ValueError) as error:
            self.detector.pause()
            if self.heat_locator is not None:
                self.heat_locator.invalidate(time.monotonic())
                self.heat_locator.recent.clear()
            self.status.setText(str(error))
    def refresh_workspace(self,*args):
        # The counter workspace owns its controls. The removed map widgets must
        # never be read after their Qt parents have been released.
        has_level=bool(self.level.currentText())
        self.game_add.setEnabled(not self.sid)
        self.level_add.setEnabled(not self.sid and self.game.currentText()!='超级马里奥')
        self.start.setEnabled(not self.sid and has_level)
        self.stop.setEnabled(bool(self.sid))
        sid=self.sid or getattr(self,'last_sid',None);sessions=[s for s in self.repo.sessions(self.player,self.game.currentText(),self.level.currentText()) if s['id']==sid]
        events=self.repo.events(sid) if sessions else []
        values=[sum(e['type']=='死亡' for e in events),sum(e['type']=='通关' for e in events),int(time.monotonic()-self.started) if self.sid else (sessions[0]['seconds'] if sessions else 0)]
        for widget,value in zip(self.metric_values,values):widget.setText(str(value))
        located = sum(event['type']=='死亡' and event.get('route_map') and event['x'] is not None and event.get('area_width') is None for event in events if event.get('route_map'))
        self.heat_note.setText(f'死亡位置已确认 {located}/{values[0]}' if values[0] else '死亡位置将在识别成功后显示')
        if self.sid:
            samples, shared = self.recording_profile
        else:
            samples, _, _, shared = recording_samples(self.game.currentText(), self.level.currentText())
        for k,w in self.sample_labels.items():
            source = '游戏通用样本' if shared else f'{len(samples[k])} 个样本'
            w.setText({'normal':'正常','death':'死亡','complete':'通关'}[k] + '：' + source)
        for b in self.sample_buttons:b.setEnabled(not self.sid)

def install_counting(app):
    app.held_keys=set();app.preview_time=0;app.stats_time=0;app.record_route=True
    for name in ['select_windows','take_sample','delayed_sample','poll_shortcuts','begin','end_session','capture_tick','refresh_workspace','toggle_route','save_heat_rechecks']:
        setattr(app,name,MethodType(getattr(CountingWorkspace,name),app))
    app.start.clicked.disconnect();app.start.clicked.connect(app.begin);app.stop.clicked.disconnect();app.stop.clicked.connect(app.end_session)
    app.capture_timer.timeout.disconnect();app.capture_timer.timeout.connect(app.capture_tick)
    app.level.currentTextChanged.disconnect();app.level.currentTextChanged.connect(app.refresh_workspace)
    layout=app.player_pages.widget(0).layout();item=layout.takeAt(layout.count()-1);detach(item.layout())
    for value,title,detail in zip(app.metric_values,['死亡次数','通关次数','本次用时 / 秒'],['自动识别的死亡事件','自动识别的通关事件','记录开始后的累计用时']):
        labels=value.parentWidget().findChildren(QLabel);labels[0].setText(title);labels[-1].setText(detail)
    body=QHBoxLayout();preview,pl=card('识别预览');app.count_preview=QLabel('选择游戏窗口并采集样本\nAlt+A 正常 · Alt+S 死亡 · Alt+D 通关 · Alt+E 地图截取 · Alt+F 开始 / 停止')
    app.count_preview.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Expanding)
    app.count_preview.setAlignment(Qt.AlignmentFlag.AlignCenter);app.count_preview.setMinimumSize(400,220);app.count_preview.setStyleSheet('background:#101c2c;color:#a3b3cd;border-radius:8px;')
    pl.addWidget(app.count_preview,1);app.score_note=text('等待游戏画面','muted');pl.addWidget(app.score_note);body.addWidget(preview,1)
    rail,rl=card('截图样本');rail.setFixedWidth(270);app.window_picker=QComboBox();rl.addWidget(app.window_picker)
    refresh=QPushButton('刷新游戏窗口');refresh.clicked.connect(app.select_windows);rl.addWidget(refresh)
    rl.addWidget(text('按住 Alt，配合 A / S / D 采集样本，Alt+F 开始或停止。仅在选中的游戏窗口前台生效；也可点击按钮，3 秒后截图。','muted'))
    app.route_state=text('地图截取：开启 · Alt+E','muted');rl.addWidget(app.route_state)
    app.heat_note=text('死亡位置将在识别成功后显示','muted');rl.addWidget(app.heat_note)
    app.sample_labels={};app.sample_buttons=[]
    for kind,key,name in [('normal','Alt+A','正常'),('death','Alt+S','死亡'),('complete','Alt+D','通关')]:
        note=text('');app.sample_labels[kind]=note;rl.addWidget(note)
        b=QPushButton(f'采集{name}样本 · {key}');b.clicked.connect(lambda checked=False,k=kind:app.delayed_sample(k));rl.addWidget(b);app.sample_buttons.append(b)
    rl.addWidget(text('I Wanna Maker 可直接使用游戏通用样本。截图后自动取样，识别到通关后自动停止并保存。','muted'));rl.addStretch();body.addWidget(rail);layout.addLayout(body,1)
    app.game.currentTextChanged.connect(app.select_windows)
    app.select_windows();app.shortcut_timer=QTimer(app);app.shortcut_timer.timeout.connect(app.poll_shortcuts);app.shortcut_timer.start(50);app.refresh_workspace()
