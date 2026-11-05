from pathlib import Path
import json
import sqlite3
import uuid
from datetime import datetime
from functools import lru_cache
from statistics import median
import numpy as np
from PIL import Image

BASE = Path(__file__).resolve().parent
MARIO = '超级马里奥'
GAMES = [
    'I Wanna Maker', 'Celeste（蔚蓝）', 'SANABI',
    'Sheepy: A Short Adventure', 'MECCHA CHAMELEON', 'Little Nightmares II',
    MARIO, 'Cuphead', 'Super Meat Boy', 'Geometry Dash',
    'Ori and the Blind Forest', 'Shovel Knight', 'VVVVVV', '其他横版平台游戏',
]

class Repository:
    def __init__(self, path=None):
        self.db = sqlite3.connect(str(path or BASE / 'analytics.sqlite3'))
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''CREATE TABLE IF NOT EXISTS sessions
            (id TEXT PRIMARY KEY, player TEXT, game TEXT, level TEXT, started TEXT,
             seconds INTEGER DEFAULT 0, completed INTEGER DEFAULT 0, status TEXT, source TEXT);
            CREATE TABLE IF NOT EXISTS events
            (id INTEGER PRIMARY KEY, session TEXT REFERENCES sessions(id), elapsed INTEGER,
             type TEXT, x REAL, y REAL);''')
        for tab, col, kind in [('sessions','capture_map','TEXT'),('events','world_x','REAL'),('events','world_y','REAL'),('events','route_map','TEXT'),('events','area_width','REAL'),('events','area_height','REAL')]:
            columns={r[1] for r in self.db.execute(f'PRAGMA table_info({tab})')}
            if col not in columns:self.db.execute(f'ALTER TABLE {tab} ADD COLUMN {col} {kind}')
        self.db.execute('CREATE TABLE IF NOT EXISTS level_catalog(game TEXT NOT NULL, name TEXT NOT NULL COLLATE NOCASE, PRIMARY KEY(game,name))')
        self.db.execute('CREATE TABLE IF NOT EXISTS game_catalog(name TEXT PRIMARY KEY COLLATE NOCASE)')
        self.db.commit()
    def games(self):
        existing = self.db.execute('SELECT name FROM game_catalog UNION SELECT game FROM sessions UNION SELECT game FROM level_catalog')
        names = {r[0] for r in existing if r[0]}
        return GAMES + sorted(names.difference(GAMES), key=str.casefold)
    def add_game(self, name):
        name = name.strip()
        if not name or len(name)>80 or name=='请选择游戏' or any(ord(c)<32 for c in name):
            raise ValueError('请输入 1 至 80 个字符的游戏名称')
        existing = next((game for game in self.games() if game.casefold() == name.casefold()), None)
        if existing:
            return existing
        self.db.execute('INSERT OR IGNORE INTO game_catalog(name) VALUES (?)', (name,))
        self.db.commit()
        return name
    def levels(self,game):
        names={r[0] for r in self.db.execute('SELECT name FROM level_catalog WHERE game=?',(game,))}
        names.update(r[0] for r in self.db.execute('SELECT DISTINCT level FROM sessions WHERE game=?',(game,)) if r[0])
        return sorted(names,key=str.casefold)
    def add_level(self,game,name):
        name=name.strip()
        if not name or len(name)>80 or any(ord(c)<32 for c in name):raise ValueError('请输入 1 至 80 个字符的关卡 / 房间名称')
        self.db.execute('INSERT OR IGNORE INTO level_catalog(game,name) VALUES (?,?)',(game,name));self.db.commit()
        return next((n for n in self.levels(game) if n.casefold()==name.casefold()),name)
    def start(self, player, game, level, source='手动演示', capture_map=None):
        sid = uuid.uuid4().hex
        self.db.execute('INSERT INTO sessions(id,player,game,level,started,seconds,completed,status,source,capture_map) VALUES (?,?,?,?,?,0,0,?,?,?)',
                        (sid, player, game, level, datetime.now().isoformat(timespec='seconds'), '记录中', source,capture_map))
        self.db.commit()
        return sid
    def finish(self, sid, seconds, completed=False):
        self.db.execute('UPDATE sessions SET seconds=?, completed=?, status=? WHERE id=?',
                        (seconds, int(completed), '已通关' if completed else '已停止', sid))
        self.db.commit()
    def event(self, sid, elapsed, kind, point=None, world_point=None, route_map=None, area=None):
        x, y = point if point is not None else (None, None)
        wx,wy=world_point if world_point is not None else (None,None)
        width, height = area if area is not None else (None, None)
        cursor = self.db.execute('INSERT INTO events(session,elapsed,type,x,y,world_x,world_y,route_map,area_width,area_height) VALUES (?,?,?,?,?,?,?,?,?,?)', (sid,elapsed,kind,x,y,wx,wy,route_map,width,height))
        self.db.commit()
        return cursor.lastrowid
    def set_route_point(self, sid, event_id, point, route_map):
        self.db.execute("UPDATE events SET x=?, y=?, route_map=? WHERE session=? AND id=? AND type='死亡'",
                        (*point, route_map, sid, event_id))
        self.db.commit()
    def sessions(self, player=None, game=None, level=None):
        sql = 'SELECT s.*, (SELECT COUNT(*) FROM events e WHERE e.session=s.id AND e.type=\'死亡\') deaths FROM sessions s WHERE 1=1'
        params = []
        for key, val in [('player',player),('game',game),('level',level)]:
            if val is not None:
                sql += f' AND s.{key}=?'; params.append(val)
        return [dict(r) for r in self.db.execute(sql+' ORDER BY started DESC, rowid DESC', params)]
    def events(self, sid):
        return [dict(r) for r in self.db.execute('SELECT * FROM events WHERE session=? ORDER BY elapsed,id', (sid,))]
    def map_folder(self,level,map_id=None):
        folder=BASE/'capture_profiles'/__import__('hashlib').sha256(level.encode()).hexdigest()[:16]
        if map_id is None:
            try:map_id=json.loads((folder/'config.json').read_text(encoding='utf-8')).get('map_id')
            except (OSError,ValueError):return None
        return folder/'maps'/map_id if map_id else None
    def display_point(self,event,session):
        if session.get('capture_map'):
            folder=self.map_folder(session['level'],session['capture_map'])
            try:
                meta=json.loads((folder/'atlas.json').read_text(encoding='utf-8'))
                if event.get('world_x') is None:return None
                x=(event['world_x']-meta['origin'][0])/meta['size'][0]
                y=(event['world_y']-meta['origin'][1])/meta['size'][1]
                return (x,y) if 0<=x<=1 and 0<=y<=1 else None
            except (OSError,ValueError,KeyError,TypeError):return None
        return (event['x'],event['y']) if event['x'] is not None else None
    def points(self, game, level, player=None, sid=None):
        sessions=self.sessions(player,game,level);result=[]
        active=self.map_folder(level) if game=='I Wanna Maker' and sid is None else None
        for s in sessions:
            if sid is not None and s['id']!=sid:continue
            if game=='I Wanna Maker':
                if s['source']!='自动画面识别':continue
                # Old viewport-normalized records are never stretched onto a scrolling atlas.
                if sid is None and (not s.get('capture_map') or active is None or s['capture_map']!=active.name):continue
            for e in self.events(s['id']):
                if e['type']=='死亡':
                    point=self.display_point(e,s)
                    if point is not None:result.append(point)
        return result


def summarize_runs(sessions):
    finished = [run for run in sessions if run['status'] in ('已停止', '已通关')]
    cleared = [run for run in finished if run['completed']]
    durations = [run['seconds'] for run in cleared if run['seconds'] is not None and run['seconds'] >= 0]
    count = len(finished)
    return dict(count=count, cleared=len(cleared), deaths=sum(run['deaths'] for run in finished),
                with_death=sum(run['deaths'] > 0 for run in finished),
                median_time=median(durations) if durations else None)


def rate(part, total):
    return f'{part/total:.1%} ({part}/{total})' if total else '—'


def duration_text(seconds):
    if seconds is None:
        return '—'
    minutes, seconds = divmod(round(seconds), 60)
    return f'{minutes}:{seconds:02d}'


def run_metric_rows(summary):
    count = summary['count']
    return [
        ('已结束记录数', count),
        ('通关率', rate(summary['cleared'], count)),
        ('通关用时中位数', duration_text(summary['median_time'])),
        ('死亡发生率', rate(summary['with_death'], count)),
        ('场均死亡次数', f"{summary['deaths']/count:.2f}" if count else '—'),
    ]


def maps():
    import re
    folder = BASE / 'TheVGLC-master' / 'Super Mario Bros' / 'Original'
    result = {}
    for p in folder.glob('mario-*.png'):
        m = re.fullmatch(r'mario-(\d+)-(\d+)', p.stem)
        if m: result[f'{m[1]}-{m[2]}'] = p
    return dict(sorted(result.items(), key=lambda x: tuple(map(int,x[0].split('-')))))

@lru_cache(maxsize=64)
def analyze(path, size=16):
    a = np.asarray(Image.open(path).convert('RGB'))
    h,w = a.shape[:2]; rows,cols = h//size,w//size
    tiles=a[:rows*size,:cols*size].reshape(rows,size,cols,size,3).transpose(0,2,1,3,4).reshape(rows*cols,-1)
    unique, inv, counts=np.unique(tiles,axis=0,return_inverse=True,return_counts=True)
    grid=inv.reshape(rows,cols)
    change=(np.sum(grid[:,1:]!=grid[:,:-1])+np.sum(grid[1:]!=grid[:-1]))/max(rows*(cols-1)+(rows-1)*cols,1)
    return dict(width=w,height=h,rows=rows,cols=cols,types=len(unique),change=round(float(change)*100,2),
                grid=grid,unique=unique,counts=counts,size=size)

