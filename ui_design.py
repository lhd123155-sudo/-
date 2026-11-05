"""Shared presentation layer. Widgets and data callbacks remain owned by the app."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QSizePolicy

STYLE='''
QWidget { background:#f3f5f9;color:#25324a;font-family:"Microsoft YaHei";font-size:13px; }
QLabel {background:transparent;} QLabel#title {font-size:25px;font-weight:700;color:#17243b;}
QLabel#muted {color:#8490a3;font-size:12px;}
QLabel#eyebrow {color:#687b98;font-size:11px;font-weight:600;}
QLabel#section {font-size:15px;font-weight:600;color:#25324a;}
QLabel#number {font-size:30px;font-weight:700;color:#263a62;}
QFrame#card {background:white;border:1px solid #e3e8f0;border-radius:12px;}
QFrame#sidebar {background:#17243b;border:0;}
QFrame#sidebar QLabel {color:#a4b3cb;}
QFrame#sidebar QLabel#brand {color:white;font-size:18px;font-weight:700;}
QFrame#sidebar QPushButton {background:transparent;border:0;color:#aab8cf;padding:13px 16px;text-align:left;border-radius:8px;}
QFrame#sidebar QPushButton:hover {background:#23344f;color:white;}
QFrame#sidebar QPushButton:checked {background:#344fe2;color:white;font-weight:600;}
QPushButton {background:white;border:1px solid #dce3ee;color:#516078;border-radius:7px;padding:9px 14px;}
QPushButton:hover {background:#eef2ff;border-color:#aebbf6;color:#344fe2;}
QPushButton#primary {background:#415ce8;color:white;border:1px solid #415ce8;font-weight:600;}
QPushButton#primary:hover {background:#304bd6;}
QPushButton#stop {background:#fff3f3;border-color:#ffd7d7;color:#ce5361;}
QPushButton:disabled {color:#b8c0cf;background:#f5f7fa;border-color:#e9edf3;}
QLineEdit,QComboBox {background:#fff;border:1px solid #dfe5ef;border-radius:7px;padding:8px 10px;min-height:20px;selection-background-color:#415ce8;}
QComboBox::drop-down {border:0;width:24px;}
QComboBox QAbstractItemView {background:white;color:#25324a;selection-background-color:#edf1ff;selection-color:#344fe2;}
QCheckBox {background:transparent;color:#718099;spacing:8px;}
QCheckBox::indicator {width:15px;height:15px;border:1px solid #c6cfdd;border-radius:4px;background:white;}
QCheckBox::indicator:checked {background:#415ce8;border-color:#415ce8;}
QTableWidget {background:white;alternate-background-color:#f8faff;border:1px solid #e3e8f0;border-radius:10px;gridline-color:#eef1f6;selection-background-color:#edf1ff;selection-color:#344fe2;}
QHeaderView::section {background:#f8faff;color:#7a879c;padding:13px 8px;border:0;border-bottom:1px solid #e8edf5;font-size:12px;}
QTableWidget::item {padding:9px;border:0;}
QScrollArea {border:0;background:transparent;}
QScrollBar:vertical {background:transparent;width:8px;} QScrollBar::handle:vertical {background:#d6ddea;border-radius:4px;min-height:28px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0px;}
QToolTip {background:#17243b;color:white;border:0;padding:8px;}
'''

def text(value,name=None):
    w=QLabel(value);w.setWordWrap(True)
    if name:w.setObjectName(name)
    return w

def card(title=None):
    w=QFrame();w.setObjectName('card');layout=QVBoxLayout(w);layout.setContentsMargins(20,18,20,18);layout.setSpacing(12)
    if title:layout.addWidget(text(title,'section'))
    return w,layout

def metric(title,detail):
    w,l=card();l.setSpacing(4);l.addWidget(text(title,'muted'));value=text('0','number');l.addWidget(value);l.addWidget(text(detail,'muted'));return w,value

def detach(layout):
    while layout.count():
        item=layout.takeAt(0)
        if item.widget():item.widget().setParent(None)
        elif item.layout():detach(item.layout())

def polish(app):
    app.setMinimumSize(1120,760)
    for sidebar in app.findChildren(QFrame,'sidebar'):
        sidebar.setFixedWidth(208);layout=sidebar.layout();layout.setContentsMargins(16,28,16,20);layout.setSpacing(8)
        brand=layout.itemAt(0).widget();brand.setText('PLATFORMER');brand.setObjectName('brand')
        # Brand and role occupy distinct rows; navigation retains its existing callbacks.
        role=text('分析工作区','muted')
        # Infer the role from the existing navigation labels, without changing routing.
        names=[b.text() for b in sidebar.findChildren(QPushButton)]
        role.setText('PLAYER SPACE  /  玩家端' if '游玩工作台' in names else 'ANALYTICS  /  管理端')
        layout.insertWidget(1,role);layout.insertSpacing(2,22)
        for b in sidebar.findChildren(QPushButton):
            if b.text()=='返回角色入口':b.setText('←  切换身份')
            b.setCursor(Qt.CursorShape.PointingHandCursor)
    for stack in [app.player_pages,app.admin_pages]:
        for i in range(stack.count()):
            l=stack.widget(i).layout();l.setContentsMargins(30,26,30,26);l.setSpacing(16)
    for table in [app.event_table,app.growth_table,app.map_table,app.behavior,app.compare_table]:
        table.verticalHeader().hide();table.verticalHeader().setDefaultSectionSize(44);table.setShowGrid(False)
        table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
    page=app.player_pages.widget(0);layout=page.layout();detach(layout)
    header=QHBoxLayout();heading=QVBoxLayout();heading.setSpacing(5)
    heading.addWidget(text('PLAYER SPACE  /  WORKSPACE','eyebrow'));heading.addWidget(text('游玩工作台','title'));heading.addWidget(text('开始一次游玩，观察你的挑战与进步。','muted'))
    header.addLayout(heading,1);app.status.setMaximumWidth(280);header.addWidget(app.status);layout.addLayout(header)
    filters,fl=card();fl.setContentsMargins(18,12,18,12);row=QHBoxLayout()
    for caption,combo in [('游戏',app.game),('关卡 / 房间',app.level)]:
        row.addWidget(text(caption,'muted'));row.addWidget(combo,1)
        if combo is app.game:row.addWidget(app.game_add)
    row.addWidget(app.level_add);row.addSpacing(12);app.start.setObjectName('primary');app.stop.setObjectName('stop');row.addWidget(app.start);row.addWidget(app.stop);fl.addLayout(row);layout.addWidget(filters)
    metrics=QHBoxLayout();metrics.setSpacing(14);app.metric_values=[]
    for title,detail in [('本次死亡','本轮记录的全部死亡事件'),('已定位','已映射到关卡地图'),('未定位','已计数，暂未获得可靠位置')]:
        w,value=metric(title,detail);metrics.addWidget(w);app.metric_values.append(value)
    layout.addLayout(metrics);app.count_note.hide()
    body=QHBoxLayout();body.setSpacing(18);mapcard,ml=card();maphead=QHBoxLayout();maphead.addWidget(text('死亡分布','section'));maphead.addStretch();maphead.addWidget(app.scope);maphead.addWidget(app.heat);ml.addLayout(maphead)
    app.canvas.setMinimumSize(420,220);app.canvas.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding);ml.addWidget(app.canvas,1)
    ml.addWidget(text('低频  ●  ●  ●  高频       ·       滚轮缩放 / 拖动平移 / 双击复位','muted'));body.addWidget(mapcard,1)
    rail=QWidget();rail.setFixedWidth(232);rl=QVBoxLayout(rail);rl.setContentsMargins(0,0,0,0);rl.setSpacing(14)
    settings,sl=card('识别设置');sl.addWidget(text('首次使用时按顺序设置。已有配置可直接开始记录。','muted'))
    for i,b in enumerate([app.setup_region,app.setup_alive,app.setup_dead],1):b.setText(f'{i:02d}   '+b.text());sl.addWidget(b)
    rl.addWidget(settings);info,il=card('地图信息');app.map_note.setObjectName('muted');il.addWidget(app.map_note);rl.addWidget(info);rl.addStretch();body.addWidget(rail);layout.addLayout(body,1)
    app.compare_table.verticalHeader().setDefaultSectionSize(33)
    # Keep the management overview compact and visually aligned with player metrics.
    overview=app.admin_pages.widget(0).layout();strip=QHBoxLayout();strip.setSpacing(14);app.admin_metric_values=[]
    for title,detail in [('已结束记录','当前游戏和来源的有效样本'),('通关率','已通关 / 已结束记录'),('通关用时中位数','仅统计通关记录，分:秒')]:
        w,value=metric(title,detail);strip.addWidget(w);app.admin_metric_values.append(value)
    overview.insertLayout(3,strip)
    ml=app.mario_panel.layout();actions=QHBoxLayout()
    for b in app.mario_panel.findChildren(QPushButton):
        ml.removeWidget(b);actions.addWidget(b)
    ml.addLayout(actions)
    app.map_table.setMinimumHeight(240);app.map_table.setMaximumHeight(380)
    app.refresh_workspace();app.refresh_admin()


def update_player(app,total,located):
    if hasattr(app,'metric_values'):
        for w,value in zip(app.metric_values,[total,located,total-located]):w.setText(str(value))

def update_admin(app,finished,clear_rate,clear_time):
    if hasattr(app,'admin_metric_values'):
        for w,value in zip(app.admin_metric_values,[finished,clear_rate,clear_time]):w.setText(str(value))
