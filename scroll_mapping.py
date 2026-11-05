"""Translation-only visual mapping in calibration-frame pixel coordinates."""
import json, time, uuid
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

class ScrollMapper:
    def __init__(self,reference,folder=None,map_id=None):
        self.folder=Path(folder) if folder else None
        self.map_id=map_id or uuid.uuid4().hex
        self.h,self.w=reference.shape[:2];self.orb=cv2.ORB_create(nfeatures=1800,fastThreshold=12)
        self.matcher=cv2.BFMatcher(cv2.NORM_HAMMING)
        self.step=0;self.frames=[];self.last=None;self.offset=None;self.dirty=False;self.saved=0
        self.image=reference.copy();self.origin=(0,0)
        if self.folder:
            try:
                meta=json.loads((self.folder/'atlas.json').read_text(encoding='utf-8'))
                if meta['map_id']==self.map_id and meta['frame_size']==[self.w,self.h]:
                    self.image=np.asarray(Image.open(self.folder/'atlas.png').convert('RGB')).copy();self.origin=tuple(meta['origin'])
                    for record in meta.get('keyframes',[]):
                        a=np.asarray(Image.open(self.folder/record['file']).convert('RGB'))
                        self.add_keyframe(a,tuple(record['offset']),False)
            except (OSError,KeyError,ValueError):pass
        if not self.frames:self.add_keyframe(reference,(0,0),False)
    def features(self,frame,exclude=None):
        gray=cv2.cvtColor(frame,cv2.COLOR_RGB2GRAY);mask=np.zeros(gray.shape,dtype=np.uint8)
        mask[int(self.h*.12):int(self.h*.94),int(self.w*.02):int(self.w*.98)]=255
        if exclude:
            x,y,w,h=exclude;mask[max(0,y-12):y+h+12,max(0,x-12):x+w+12]=0
        return self.orb.detectAndCompute(gray,mask)
    def add_keyframe(self,frame,offset,dirty=True):
        kp,desc=self.features(frame)
        self.frames.append(dict(frame=frame.copy(),offset=offset,kp=kp,desc=desc))
        if len(self.frames)>64:self.frames.pop(1) # Retain original anchor.
        self.dirty=self.dirty or dirty
    def translation(self,kp,desc,target):
        if desc is None or target['desc'] is None or len(desc)<15 or len(target['desc'])<15:return None
        pairs=self.matcher.knnMatch(desc,target['desc'],k=2)
        matches=[m for pair in pairs if len(pair)==2 for m,n in [pair] if m.distance<.7*n.distance]
        if len(matches)<14:return None
        src=np.float32([kp[m.queryIdx].pt for m in matches]);dst=np.float32([target['kp'][m.trainIdx].pt for m in matches])
        affine,inliers=cv2.estimateAffinePartial2D(src,dst,method=cv2.RANSAC,ransacReprojThreshold=2.0,maxIters=1000)
        if affine is None or inliers is None:return None
        good=inliers.ravel().astype(bool)
        if sum(good)<12 or np.mean(good)<.55:return None
        # Only camera translation is supported; reject zoom/rotation and local animation.
        if abs(affine[0,0]-1)>.015 or abs(affine[1,1]-1)>.015 or abs(affine[0,1])>.012:return None
        spread=np.ptp(src[good],axis=0)
        if spread[0]<self.w*.20 or spread[1]<self.h*.12:return None
        shift=np.median(dst[good]-src[good],axis=0)
        residual=np.linalg.norm(dst[good]-src[good]-shift,axis=1)
        if np.median(residual)>1.5:return None
        return np.array(target['offset'])+shift,int(sum(good))
    def locate(self,frame,exclude=None):
        if frame.shape[:2]!=(self.h,self.w):self.offset=None;return None
        kp,desc=self.features(frame,exclude)
        # Recent mapping supplies continuity. Once lost, absolute keyframes are used
        # instead of carrying the previous offset across respawns or room transitions.
        candidates=([self.last] if self.last else [])+list(reversed(self.frames))
        best=None;absolute=[];self.step+=1
        for target in candidates:
            result=self.translation(kp,desc,target)
            if result is not None:
                if target is not self.last:absolute.append(result)
                if best is None or result[1]>best[1]:best=result
                if target is self.last and result[1]>=25 and self.step%8:break
        if best is None:self.last=None;self.offset=None;return None
        # Periodically close the loop against persistent absolute keyframes. Do not
        # silently choose one of two equally convincing, distant repeated patterns.
        if absolute:
            absolute.sort(key=lambda item:item[1],reverse=True)
            anchor=absolute[0]
            if len(absolute)>1 and absolute[1][1]>=anchor[1]*.9 and np.linalg.norm(absolute[1][0]-anchor[0])>min(self.w,self.h)*.2:
                self.lose();return None
            if anchor[1]>=max(12,best[1]*.7):best=anchor
        offset=tuple(float(x) for x in best[0]);self.offset=offset
        self.last=dict(frame=None,kp=kp,desc=desc,offset=offset)
        if not self.stitch(frame,offset,exclude):self.last=None;self.offset=None;return None
        if min(np.linalg.norm(np.array(offset)-np.array(k['offset'])) for k in self.frames)>min(self.w,self.h)*.35:
            self.add_keyframe(frame,offset)
        return offset
    def lose(self):self.last=None;self.offset=None
    def stitch(self,frame,offset,exclude):
        x,y=map(round,offset);ox,oy=self.origin;ih,iw=self.image.shape[:2]
        left,top=min(ox,x),min(oy,y);right,bottom=max(ox+iw,x+self.w),max(oy+ih,y+self.h)
        if right-left>16000 or bottom-top>16000 or (right-left)*(bottom-top)>32000000:return False
        if (left,top,right-left,bottom-top)!=(ox,oy,iw,ih):
            canvas=np.zeros((bottom-top,right-left,3),dtype=np.uint8)
            canvas[oy-top:oy-top+ih,ox-left:ox-left+iw]=self.image;self.image=canvas;self.origin=(left,top)
        mask=np.zeros((self.h,self.w),dtype=bool);mask[int(self.h*.12):int(self.h*.94),int(self.w*.02):int(self.w*.98)]=True
        if exclude:
            px,py,pw,ph=exclude;mask[max(0,py-3):py+ph+3,max(0,px-3):px+pw+3]=False
        view=self.image[y-top:y-top+self.h,x-left:x-left+self.w];view[mask]=frame[mask];self.dirty=True;return True
    def save(self,force=False):
        if not self.folder or not self.dirty or (not force and time.monotonic()-self.saved<2):return
        self.folder.mkdir(parents=True,exist_ok=True)
        Image.fromarray(self.image).save(self.folder/'atlas.tmp.png');(self.folder/'atlas.tmp.png').replace(self.folder/'atlas.png')
        records=[]
        for i,k in enumerate(self.frames):
            name='keyframe_'+__import__('hashlib').sha256(k['frame'].tobytes()).hexdigest()[:16]+'.png'
            if not (self.folder/name).exists():Image.fromarray(k['frame']).save(self.folder/name)
            records.append(dict(file=name,offset=k['offset']))
        metadata=dict(map_id=self.map_id,frame_size=[self.w,self.h],origin=self.origin,size=[self.image.shape[1],self.image.shape[0]],keyframes=records)
        (self.folder/'atlas.tmp.json').write_text(json.dumps(metadata),encoding='utf-8');(self.folder/'atlas.tmp.json').replace(self.folder/'atlas.json')
        self.dirty=False;self.saved=time.monotonic()
