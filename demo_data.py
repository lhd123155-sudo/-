"""Generate clearly labeled demonstration sessions without changing captured records."""
import argparse,json,random,sqlite3,uuid
from pathlib import Path
from datetime import datetime,timedelta
BASE=Path(__file__).resolve().parent
SOURCE='模拟生成'
def generate(database,output):
 rng=random.Random(20261105);db=sqlite3.connect(str(database));db.row_factory=sqlite3.Row
 backup=BASE/'backups'/('before_synthetic_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.sqlite3');backup.parent.mkdir(exist_ok=True)
 with sqlite3.connect(str(backup)) as target:db.backup(target)
 levels=[('I Wanna Maker','1-1',3),('I Wanna Maker','1-2',6),('I Wanna Maker','1-3',9),('I Wanna Maker','1-4',12),('Celeste（蔚蓝）','1A',6),('Celeste（蔚蓝）','2A',9)]
 rows=[];inserted=0
 with db:
  for player in range(1,13):
   skill=rng.uniform(.65,1.4)
   for game,level,difficulty in levels:
    for attempt in range(1,3):
     sid='synthetic-v1-'+uuid.uuid5(uuid.NAMESPACE_URL,f'platformer-demo/{player}/{game}/{level}/{attempt}').hex
     deaths=max(0,round(rng.gauss(difficulty*skill*(1 if attempt==1 else .78),2.2)))
     completed=rng.random()<(.68 if attempt==1 else .84)
     seconds=int(45+deaths*rng.uniform(12,30)+rng.uniform(15,150))
     started=datetime(2026,10,23,9)+timedelta(minutes=len(rows)*85)
     times=sorted(rng.sample(range(1,seconds),deaths))
     events=[dict(elapsed=t,type='死亡',position=None) for t in times]
     if completed:events.append(dict(elapsed=seconds,type='通关',position=None))
     row=dict(id=sid,player=f'模拟玩家{player:02d}',game=game,level=level,started=started.isoformat(timespec='seconds'),seconds=seconds,completed=int(completed),status='已通关' if completed else '已停止',source=SOURCE,capture_map=None,deaths=deaths,events=events)
     rows.append(row)
     if db.execute('SELECT 1 FROM sessions WHERE id=?',(sid,)).fetchone():continue
     db.execute('INSERT INTO sessions(id,player,game,level,started,seconds,completed,status,source,capture_map) VALUES (?,?,?,?,?,?,?,?,?,?)',tuple(row[k] for k in ['id','player','game','level','started','seconds','completed','status','source','capture_map']))
     for event in events:db.execute('INSERT INTO events(session,elapsed,type,x,y,world_x,world_y) VALUES (?,?,?,NULL,NULL,NULL,NULL)',(sid,event['elapsed'],event['type']))
     inserted+=1
 metadata=dict(description='用于界面展示的模拟生成数据，不是真实玩家实验或画面识别结果。',seed=20261105,players=12,games=2,levels=6,sessions=len(rows),deaths=sum(r['deaths'] for r in rows),completions=sum(r['completed'] for r in rows),position_data=False)
 output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(dict(metadata=metadata,sessions=rows),ensure_ascii=False,indent=2),encoding='utf-8')
 actual=db.execute('SELECT COUNT(*) FROM sessions WHERE source=?',(SOURCE,)).fetchone()[0]
 assert actual>=144
 assert not db.execute("SELECT 1 FROM events e JOIN sessions s ON s.id=e.session WHERE s.source=? AND (e.x IS NOT NULL OR e.world_x IS NOT NULL)",(SOURCE,)).fetchone()
 db.close();print(json.dumps(dict(**metadata,inserted=inserted,backup=str(backup)),ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--database',type=Path,default=BASE/'analytics.sqlite3');p.add_argument('--output',type=Path,required=True);a=p.parse_args();generate(a.database,a.output)
