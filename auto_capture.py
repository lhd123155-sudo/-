"""I Wanna Maker visual collector. No process memory access or game modification."""
import time, ctypes, hashlib, json, uuid
from scroll_mapping import ScrollMapper
from ctypes import wintypes
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from analytics_data import BASE

class WindowCapture:
    def windows(self,title_hint='i wanna maker'):
        result=[];user=ctypes.windll.user32
        user.IsWindowVisible.argtypes=[wintypes.HWND];user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        def visit(hwnd,_):
            if user.IsWindowVisible(hwnd):
                buf=ctypes.create_unicode_buffer(512);user.GetWindowTextW(hwnd,buf,512)
                if buf.value and (title_hint is None or title_hint.lower() in buf.value.lower()):
                    pid=wintypes.DWORD();user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)];user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    if pid.value!=__import__('os').getpid():result.append((int(hwnd),buf.value))
            return True
        user.EnumWindows(callback(visit),0);return result
    def grab(self,hwnd):
        import mss
        # Initialize capture DPI handling before querying client coordinates.
        with mss.mss() as capture:return self._grab(hwnd,capture)
    def _grab(self,hwnd,capture):
        user=ctypes.windll.user32
        user.GetForegroundWindow.restype=wintypes.HWND
        user.IsIconic.argtypes=[wintypes.HWND];user.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)];user.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
        if user.GetForegroundWindow()!=hwnd or user.IsIconic(hwnd):
            raise RuntimeError('请将选中的游戏窗口置于前台；采集已暂停')
        rect=wintypes.RECT();point=wintypes.POINT(0,0)
        if not user.GetClientRect(hwnd,ctypes.byref(rect)) or not user.ClientToScreen(hwnd,ctypes.byref(point)):
            raise RuntimeError('游戏窗口已关闭')
        if rect.right<100 or rect.bottom<100:raise RuntimeError('等待游戏画面恢复，当前记录保留')
        frame=np.array(capture.grab(dict(left=point.x,top=point.y,width=rect.right,height=rect.bottom)))
        return cv2.cvtColor(frame,cv2.COLOR_BGRA2RGB)

class DeathCounter:
    """Separate event recognition from map localization and rendering cadence."""
    def __init__(self,threshold=.88):
        self.threshold=threshold;self.armed=False;self.latched=False
        self.live_frames=0;self.live_since=None;self.hit_frames=0;self.hit_since=None;self.previous=None
    def pause(self):
        self.live_frames=0;self.live_since=None;self.hit_frames=0;self.hit_since=None;self.previous=None
        # Keep the death latch through alt-tab/capture failures. A long pause alone
        # is not proof of respawn and must not start a new death cycle.
    def update(self,score,alive,now,strong_alive=False):
        if self.previous is not None and now-self.previous>.7:
            self.live_frames=0;self.live_since=None;self.hit_frames=0;self.hit_since=None
        self.previous=now
        if score>=self.threshold:
            self.live_frames=0;self.live_since=None
            if self.hit_since is None:self.hit_since=now
            self.hit_frames+=1
            confirmed=(score>=max(.97,self.threshold+.07) or
                       (self.hit_frames>=2 and now-self.hit_since>=.035))
            if confirmed and self.armed and not self.latched:
                self.armed=False;self.latched=True;return True
            return False
        self.hit_frames=0;self.hit_since=None
        if score>self.threshold-.06 or not alive:
            self.live_frames=0;self.live_since=None;return False
        if strong_alive:
            self.armed=True;self.latched=False
        if self.live_since is None:self.live_since=now
        self.live_frames+=1
        if self.live_frames>=2 and now-self.live_since>=.06:
            self.armed=True;self.latched=False
        return False

class Detector:
    def __init__(self,player,death,death_rect,frame_size,threshold=.88):
        self.viewport=None;self.capture_size=None;self.mapper=None;self.last_world=None;self.reference=None;self.player=np.asarray(player,dtype=np.uint8);self.death=np.asarray(death,dtype=np.uint8)
        self.death_rect=death_rect;self.frame_size=tuple(frame_size);self.threshold=threshold;self.counter=DeathCounter(threshold);self.reset()
    def reset(self):
        self.counter.pause()
        self.last_point=None;self.last_world=None;self.last_seen=-1e9;self.alive_since=None;self.death_since=None;self.armed=False;self.blocked=True
    @staticmethod
    def match(frame,template):
        if frame.shape[0]<template.shape[0] or frame.shape[1]<template.shape[1]:return 0,None
        # SQDIFF supports solid and low variance templates without the false perfect
        # matches produced by normalized correlation on constant templates.
        result=cv2.matchTemplate(frame,template,cv2.TM_SQDIFF_NORMED)
        low,_,loc,_=cv2.minMaxLoc(result)
        return 1-float(low),loc
    def track_player(self,frame):
        variants=[self.player,np.ascontiguousarray(self.player[:,::-1])]
        best=max((self.match(frame,t) for t in variants),key=lambda z:z[0])
        if best[0]>=self.threshold:return best
        # Background pixels at the edge of a calibration crop change while walking.
        # Use the interior only after a full sprite was acquired, with a distinct
        # match and a recent position; never bootstrap from a tiny patch alone.
        if self.last_point is None:return best
        best=(0.,None)
        h,w=self.player.shape[:2];left=max(1,int(w*.26));top=max(1,int(h*.10))
        right=max(left+4,int(w*.74));bottom=max(top+6,int(h*.81))
        for template in variants:
            patch=template[top:bottom,left:right]
            scores=1-cv2.matchTemplate(frame,patch,cv2.TM_SQDIFF_NORMED)
            _,score,_,loc=cv2.minMaxLoc(scores)
            radius=max(30,w*2);x,y=loc;other=scores.copy()
            other[max(0,y-radius):y+radius,max(0,x-radius):x+radius]=-1
            if score>=self.threshold-.08 and score-float(other.max())>=.06:
                if score>best[0]:best=(float(score),(x-left,y-top))
        return best
    def process(self,frame,now=None):
        now=time.monotonic() if now is None else now
        if self.capture_size and (frame.shape[1],frame.shape[0])!=tuple(self.capture_size):
            self.reset();return {'status':'游戏窗口大小已变化，请重新设置识别'}
        if self.viewport:
            vx,vy,vw,vh=self.viewport;frame=frame[vy:vy+vh,vx:vx+vw]
        h,w=frame.shape[:2]
        if (w,h)!=self.frame_size:self.reset();return {'status':'窗口尺寸已变化，请重新设置识别'}
        x,y,rw,rh=self.death_rect;ds,_=self.match(frame[y:y+rh,x:x+rw],self.death)
        if ds>=self.threshold:
            counted=self.counter.update(ds,False,now)
            self.armed=self.counter.armed
            if counted:
                point=self.last_point if now-self.last_seen<=1.2 else None
                return {'status':'检测到死亡','death':True,'point':point,
                        'world_point':self.last_world if point is not None else None,'confidence':ds}
            return {'status':'死亡画面 / 等待重生'}
        # A weak overlay match is treated as uncertain, not a clean respawn frame.
        if ds>self.threshold-.06:
            self.counter.update(ds,False,now)
            return {'status':'死亡提示确认中'}
        score,loc=self.track_player(frame)
        tracked=score>=self.threshold or (self.last_point is not None and score>=self.threshold-.08)
        self.counter.update(ds,tracked,now,strong_alive=score>=max(.97,self.threshold+.07));self.armed=self.counter.armed
        exclude=(loc[0],loc[1],self.player.shape[1],self.player.shape[0]) if tracked else None
        offset=self.mapper.locate(frame,exclude) if self.mapper else (0,0)
        if self.mapper and offset is None:
            self.last_point=None;self.last_world=None;self.last_seen=-1e9
            return {'status':'滚动定位丢失，等待已知画面重定位；死亡仅计数'}
        if not tracked:
            self.alive_since=None
            return {'status':'角色暂未识别；不推断死亡'}
        px=(loc[0]+self.player.shape[1]/2)/w;py=(loc[1]+self.player.shape[0]/2)/h
        proposed=(offset[0]+px*w,offset[1]+py*h)
        if self.last_world is not None and now-self.last_seen<1.2 and np.linalg.norm(np.array(proposed)-self.last_world)>max(80,600*(now-self.last_seen)):
            return {'status':'角色匹配跳变，暂不更新位置'}
        self.last_point=(px,py);self.last_world=(offset[0]+px*w,offset[1]+py*h);self.last_seen=now
        return {'status':'角色 / 滚动坐标跟踪中' if self.armed else '确认角色中','point':self.last_point,'world_point':self.last_world,'confidence':score}

def config_dir(level):
    return BASE/'capture_profiles'/hashlib.sha256(level.encode()).hexdigest()[:16]

def save_profile(level,player,death,death_rect,size,background,viewport=None,capture_size=None):
    x,y,rw,rh=death_rect
    if Detector.match(background[y:y+rh,x:x+rw],death)[0]>=.88:
        raise ValueError('死亡样本与正常画面过于相似，请框选死亡时独有的文字或图案')
    if player.shape[0]*player.shape[1]>background.shape[0]*background.shape[1]*.10:
        raise ValueError('角色样本过大，请紧贴角色轮廓框选')
    folder=config_dir(level);folder.mkdir(parents=True,exist_ok=True)
    Image.fromarray(player).save(folder/'player.png');Image.fromarray(death).save(folder/'death.png')
    Image.fromarray(background).save(folder/'scene.png')
    (folder/'config.json').write_text(json.dumps(dict(level=level,death_rect=death_rect,size=size,map_id=uuid.uuid4().hex,viewport=viewport,capture_size=capture_size)),encoding='utf-8')

def load_profile(level):
    folder=config_dir(level)
    try:
        c=json.loads((folder/'config.json').read_text(encoding='utf-8'))
        detector=Detector(np.asarray(Image.open(folder/'player.png').convert('RGB')),np.asarray(Image.open(folder/'death.png').convert('RGB')),c['death_rect'],c['size'])
        detector.viewport=c.get('viewport');detector.capture_size=c.get('capture_size')
        detector.reference=np.asarray(Image.open(folder/'scene.png').convert('RGB'))
        if not c.get('map_id'):
            c['map_id']=uuid.uuid4().hex;(folder/'config.json').write_text(json.dumps(c),encoding='utf-8')
        detector.mapper=ScrollMapper(detector.reference,folder/'maps'/c['map_id'],c['map_id']);detector.mapper.dirty=True;detector.mapper.save(force=True)
        return detector
    except (OSError,ValueError,KeyError):return None
