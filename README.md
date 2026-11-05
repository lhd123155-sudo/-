# 横版游戏可视化交互平台

Platformer Analytics 是一个 Windows 桌面应用。它从游戏窗口识别死亡和通关状态，将滚动画面拼接成地图，并在确认角色位置后绘制死亡热点。玩家端提供记录、单次复盘和个人成长，管理端提供关卡分析、玩家行为和关卡对比。

## 安装和启动

使用 Windows 和 Python 3.11。在项目目录打开终端并执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe desktop_main.py
```

安装依赖后，也可以双击 `start.bat` 启动。首次启动时，程序会创建本地数据库。

## 记录游玩

在玩家端选择游戏、关卡和实际游戏窗口。首次使用时，在对应的游戏画面按 `Alt+A`、`Alt+S`、`Alt+D`，分别采集正常、死亡和通关样本。如果已有自己的样本库，可以将本机的 `count_profiles/` 复制到项目目录。已有的角色定位样本可放入 `capture_profiles/`。

切回游戏后按 `Alt+F` 开始或停止记录。确认通关时会自动保存并停止。`Alt+E` 开关地图截取，计数继续运行。

在「单次复盘」查看地图、死亡热点和事件。地图只显示位置已确认的死亡。管理端可以按来源筛选实采记录，超级马里奥的地图资料与游玩统计分开使用。

## 项目结构

- `desktop_main.py`、`counting_ui.py` 和 `ui_design.py` 管理玩家端和管理端界面。
- `sample_counter.py` 比对截图特征，`route_capture.py` 和 `scroll_mapping.py` 负责拼接地图，`route_heat.py` 将角色位置关联到长图。
- `analytics_data.py` 管理 SQLite 记录与统计，`tests/` 包含回归测试。
- `main.py` 是管理端可打开的超级马里奥图块分析页面。使用这个页面时，将已有的 `mario-关-房间.png` 地图放入 `TheVGLC-master/Super Mario Bros/Original/`。关卡资料来源见 [The Video Game Level Corpus](https://github.com/TheVGLC/TheVGLC)。

公开仓库仅提供源码。截图样本、角色定位素材、游玩记录和地图留在本机。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```
