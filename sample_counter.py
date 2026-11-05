"""Screenshot event counter. No character tracking or map dependency."""
import json,time,hashlib,uuid
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageChops
from analytics_data import BASE
from route_capture import viewport

KINDS=('normal','death','complete')
def restart_mask(image):
    # The restart prompt has a yellow R with a dark outline. Compare this
    # lettering and its outline, without the moving level behind it.
    red, green, blue = np.moveaxis(image.astype(np.int16), 2, 0)
    yellow = (red > 192) & (green > 145) & (green < 215) & (blue < 90) & (red-green > 30)
    if yellow.sum() < 24:
        return None
    near = cv2.dilate(yellow.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    return yellow | (near & (image.max(axis=2) < 35))


def cue_pixels(image, mask):
    pixels = cv2.GaussianBlur(image, (5, 5), 0)[mask].astype(np.float32)
    pixels -= pixels.mean(axis=0)
    return pixels.ravel()


def similarity(frame, sample):
    x, y, width, height = sample['rect']
    roi = frame[y:y+height, x:x+width]
    template = sample['image']
    if roi.shape != template.shape:
        return 0.
    mask = sample.get('mask')
    if 'cue_pixels' in sample:
        # Compare lettering shape across changes in tint, camera background
        # and capture scaling. Faint noise is not a visible cue.
        pixels = cue_pixels(roi, mask)
        strength = np.linalg.norm(pixels)
        reference, reference_strength = sample['cue_pixels']
        if strength < .35 * reference_strength:
            return 0.
        return float(np.clip(np.dot(pixels, reference) / (strength * reference_strength), 0., 1.))
    if mask is not None:
        difference = np.abs(roi[mask].astype(np.int16) - template[mask]).mean()
    else:
        a = cv2.resize(roi, (96, 64)).astype(np.int16)
        b = cv2.resize(template, (96, 64))
        difference = np.abs(a-b).mean()
    return max(0., 1. - float(difference)*3/255)


def content_bounds(frame):
    height, width = frame.shape[:2]
    # Letterboxing can change while the game's content stays at the same scale.
    bright = frame.max(axis=2) > 12
    rows = np.flatnonzero(bright.mean(axis=1) > .025)
    columns = np.flatnonzero(bright.mean(axis=0) > .025)
    if rows.size and columns.size:
        left, right = int(columns[0]), int(columns[-1])+1
        top, bottom = int(rows[0]), int(rows[-1])+1
        if right-left >= .75*width and bottom-top >= .75*height:
            return left, top, right, bottom
    return 0, 0, width, height


def normalize_frame(frame, size, reference_bounds=None):
    width, height = size
    if frame.shape[:2] == (height, width):
        return frame
    if reference_bounds:
        x0, y0, x1, y1 = content_bounds(frame)
        left, top, right, bottom = reference_bounds
        ratio = ((x1-x0)/(y1-y0))/((right-left)/(bottom-top))
        if .94 <= ratio <= 1.06:
            source = frame[y0:y1, x0:x1]
            interpolation = cv2.INTER_AREA if source.shape[1]>right-left else cv2.INTER_LINEAR
            normalized = np.zeros((height,width,3),dtype=frame.dtype)
            normalized[top:bottom,left:right] = cv2.resize(source,(right-left,bottom-top),interpolation=interpolation)
            return normalized
    interpolation = cv2.INTER_AREA if frame.shape[1]>width else cv2.INTER_LINEAR
    return cv2.resize(frame, (width,height), interpolation=interpolation)


def reference_bounds(game, level, size):
    try:
        with Image.open(folder_for(game, level)/'normal_full.png') as image:
            if image.size == tuple(size):
                return content_bounds(np.array(image.convert('RGB')))
    except OSError:
        pass
    return None


class SampleCounter:
    def __init__(self,samples,size,bounds=None):
        self.samples = samples
        self.size = tuple(size)
        self.bounds = bounds
        self.mapper = None
        self.restart_samples = [sample for sample in samples.get('death', []) if sample.get('match') == 'restart_prompt' and sample.get('mask') is not None]
        self.reset()
    def reset(self):
        self.state='waiting';self.candidate=None;self.hits=0;self.since=None;self.last=None
    def pause(self):
        self.candidate=None;self.hits=0;self.since=None;self.last=None
    def scores(self, frame):
        scores = {
            kind: max((similarity(frame, sample) for sample in self.samples.get(kind, [])), default=0.)
            for kind in ('normal', 'complete')
        }
        # Profiles with a verified restart cue count that cue. Other screenshots
        # stay in the sample library and cannot independently trigger death.
        death_samples = self.restart_samples or self.samples.get('death', [])
        scores['death'] = max((similarity(frame, sample) for sample in death_samples), default=0.)
        return scores
    def process(self,frame,now=None,*,reloading=False):
        now=time.monotonic() if now is None else now
        frame = normalize_frame(frame, self.size, self.bounds)
        scores=self.scores(frame);event_scores=sorted([(scores[k],k) for k in ('death','complete')],reverse=True)
        score,kind=event_scores[0];runner=event_scores[1][0]
        # Event ROIs and normal ROIs may differ: an unchanged normal HUD must not
        # suppress a clear death prompt. Ambiguous death/clear matches are rejected.
        clear_restart = bool(self.restart_samples) and scores['death'] >= .97
        if clear_restart:target='death'
        elif score>=.91 and score-runner>=.06:target=kind
        elif max(scores['death'],scores['complete'])<.83 and scores['normal']>=.90:target='normal'
        else:target=None
        if reloading and target not in ('death','complete'):
            self.pause()
            return {'status':'正在回到存档点，记录继续','scores':scores}
        if self.last is not None and now-self.last>.6:self.candidate=None;self.hits=0;self.since=None
        self.last=now
        if target is None:
            self.candidate=None;self.hits=0;self.since=None
            return {'status':'画面不确定，暂不计数','scores':scores}
        if target!=self.candidate:self.candidate=target;self.hits=1;self.since=now
        else:self.hits+=1
        confirmed = clear_restart or (self.hits >= 2 and now-self.since >= .05)
        if not confirmed:return {'status':'正在确认画面','scores':scores}
        event=None
        if target=='normal':self.state='playing'
        elif self.state=='playing':self.state=target;event=target
        # A held/flickering event screen cannot count again without confirmed play.
        return {'status':{'normal':'游玩中','death':'死亡画面 / 等待重生','complete':'通关画面'}[target],
                'event':event,'scores':scores}

def folder_for(game,level):return BASE/'count_profiles'/hashlib.sha256((game+'\0'+level).encode()).hexdigest()[:20]
def read_samples(game,level):
    folder=folder_for(game,level)
    try:
        data=json.loads((folder/'samples.json').read_text(encoding='utf-8'));samples={k:[] for k in KINDS}
        for k in KINDS:
            for entry in data.get(k,[]):
                image = np.array(Image.open(folder/entry['file']).convert('RGB'))
                sample = dict(rect=entry['rect'], image=image, entry=entry)
                if entry.get('match') == 'restart_prompt':
                    sample['match'] = 'restart_prompt'
                    sample['mask'] = restart_mask(image)
                if entry.get('mask_file'):
                    with Image.open(folder/entry['mask_file']) as mask_image:
                        mask = np.array(mask_image.convert('L')) > 0
                    if mask.shape == image.shape[:2] and mask.any():
                        sample['mask'] = mask
                if entry.get('comparison') == 'cue_shape' and sample.get('mask') is not None:
                    pixels = cue_pixels(image, sample['mask'])
                    strength = np.linalg.norm(pixels)
                    if strength > 0:
                        sample['cue_pixels'] = (pixels, strength)
                samples[k].append(sample)
        return samples,tuple(data['size'])
    except (OSError,ValueError,KeyError):return {k:[] for k in KINDS},None

def recording_samples(game, level):
    samples, size = read_samples(game, level)
    if game == 'I Wanna Maker' and not (size and all(samples[k] for k in KINDS)):
        shared, shared_size = read_samples(game, '')
        if shared_size and all(shared[k] for k in KINDS):
            width, height = shared_size
            return shared, shared_size, (0, 0, width, height), True
    bounds = reference_bounds(game, level, size) if size else None
    return samples, size, bounds, False


def screenshot_levels(game):
    levels = set()
    for path in (BASE/'count_profiles').glob('*/samples.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('game') == game and data.get('level'):
                levels.add(data['level'])
        except (OSError, ValueError):
            continue
    return levels


def screenshot_entries(game, level):
    folder = folder_for(game, level)
    try:
        data = json.loads((folder/'samples.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    results = []
    for kind in KINDS:
        for entry in reversed(data.get(kind, [])):
            patch = folder/Path(entry['file']).name
            full = folder/Path(entry['snapshot']).name if entry.get('snapshot') else None
            if full is None:
                candidate = folder/('normal_full.png' if kind == 'normal' else f'last_{kind}_full.png')
                try:
                    x, y, width, height = entry['rect']
                    with Image.open(candidate) as original, Image.open(patch) as crop:
                        region = original.convert('RGB').crop((x, y, x+width, y+height))
                        if region.size == crop.size and not ImageChops.difference(region, crop.convert('RGB')).getbbox():
                            full = candidate
                except (OSError, ValueError):
                    pass
            if full is not None and not full.is_file():
                full = None
            if full is not None or patch.is_file():
                results.append(dict(kind=kind, path=full or patch, full=full is not None,
                                    player=entry.get('player'), captured=entry.get('captured')))
    return results


def automatic_region(game, level, kind, frame, samples, normal):
    x, y, width, height = viewport(frame, game, level)
    if kind == 'normal':
        sidebar = frame.shape[1] - (x + width)
        if sidebar >= 50:
            return x + width + 4, y + 4, sidebar - 8, min(85, height - 4)
        return x, y, width, height
    for sample in reversed(samples[kind]):
        sx, sy, sw, sh = sample['rect']
        region = frame[sy:sy+sh, sx:sx+sw]
        if region.shape == sample['image'].shape:
            difference = np.abs(region.astype(np.int16) - sample['image']).mean()
            if difference < 8:
                return tuple(sample['rect'])
    if normal is None or normal.shape != frame.shape:
        raise ValueError('请先采集正常样本，再采集死亡或通关画面')
    # Prefer a compact, visually changed prompt over whole-frame camera movement.
    current = cv2.cvtColor(frame[y:y+height, x:x+width], cv2.COLOR_RGB2GRAY)
    reference = cv2.cvtColor(normal[y:y+height, x:x+width], cv2.COLOR_RGB2GRAY)
    contrast = cv2.absdiff(current, reference)
    edges = cv2.Canny(current, 80, 160)
    signal = ((contrast > 25) & (edges > 0)).astype(np.float32)
    rw, rh = max(12, width//3), max(12, height//8)
    candidates = []
    for top in range(0, height-rh+1, max(1, rh//2)):
        for left in range(0, width-rw+1, max(1, rw//2)):
            evidence = signal[top:top+rh, left:left+rw].mean()
            change = contrast[top:top+rh, left:left+rw].mean()
            if change >= 12:
                candidates.append((evidence, left, top))
    if not candidates:
        raise ValueError('与正常画面差异不足，请在死亡或通关提示出现时重新采集')
    _, left, top = max(candidates)
    return x+left, y+top, rw, rh

def recurring_cue(frame, previous, normal, rect):
    """Learn pixels shared by two event screenshots and distinct from normal play."""
    x, y, width, height = rect
    current = frame[y:y+height, x:x+width]
    earlier = previous[y:y+height, x:x+width]
    baseline = normal[y:y+height, x:x+width]
    event_difference = np.abs(current.astype(np.int16)-earlier)
    if event_difference.mean() < 4:
        return None
    stable = event_difference.max(axis=2) <= 18
    changed = np.abs(current.astype(np.int16)-baseline).max(axis=2) >= 32
    edges = cv2.Canny(cv2.cvtColor(current, cv2.COLOR_RGB2GRAY), 65, 145)
    near_edges = cv2.dilate(edges, np.ones((5, 5), np.uint8)) > 0
    mask = stable & changed & near_edges
    if mask.sum() < max(45, mask.size*.035):
        return None
    return mask


def save_sample(game,level,kind,frame,rect=None,*,player=None):
    folder=folder_for(game,level);samples,size=read_samples(game,level);current=(frame.shape[1],frame.shape[0])
    original = frame
    if size and size != current:
        if rect is not None:
            raise ValueError('手动样本坐标需对应原采样尺寸')
        frame = normalize_frame(frame, size, reference_bounds(game, level, size))
        current = size
    mode = None
    comparison = None
    learned_mask = None
    automatic = rect is None
    event_reference = folder / f'last_{kind}_full.png'
    normal_path = folder / 'normal_full.png'
    normal = np.array(Image.open(normal_path).convert('RGB')) if normal_path.exists() else None
    restart_samples = [sample for sample in samples['death'] if sample.get('match') == 'restart_prompt' and sample.get('mask') is not None]
    if rect is None and kind == 'death' and restart_samples:
        match = max(restart_samples, key=lambda sample: similarity(frame, sample))
        x, y, width, height = match['rect']
        if similarity(frame, match) < .91 or restart_mask(frame[y:y+height, x:x+width]) is None:
            raise ValueError('没有拍到“按住 R 重新开始”，请等提示清晰出现后再按 Alt+S')
        rect = match['rect']
        mode = 'restart_prompt'
        comparison = match['entry'].get('comparison')
    if rect is None:
        rect=automatic_region(game,level,kind,frame,samples,normal)
    x,y,w,h=rect;patch=frame[y:y+h,x:x+w].copy()
    if w<6 or h<6:raise ValueError('样本区域过小')
    # Reject a new event crop if an existing normal frame has the same pattern.
    if kind!='normal' and (folder/'normal_full.png').exists():
        normal=np.array(Image.open(folder/'normal_full.png').convert('RGB'))
        if normal.shape==frame.shape and np.mean(np.abs(normal[y:y+h,x:x+w].astype(float)-patch.astype(float)))<10:
            raise ValueError('该区域与正常画面几乎相同，请在死亡或通关提示清晰时重新截图')
    if automatic and kind != 'normal' and mode is None and event_reference.exists() and normal is not None:
        previous = np.array(Image.open(event_reference).convert('RGB'))
        if previous.shape == normal.shape == frame.shape:
            learned_mask = recurring_cue(frame, previous, normal, rect)
    folder.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    entry = dict(rect=rect, file=f'{kind}_{token}.png', snapshot=f'full_{token}.png',
                 match=mode, player=player, captured=datetime.now().isoformat(timespec='seconds'))
    if comparison:
        entry['comparison'] = comparison
    Image.fromarray(patch).save(folder/entry['file'])
    Image.fromarray(original).save(folder/entry['snapshot'])
    if learned_mask is not None:
        entry['mask_file'] = f'mask_{token}.png'
        Image.fromarray(learned_mask.astype(np.uint8)*255).save(folder/entry['mask_file'])
    data = {'size':current, 'game':game, 'level':level}
    for sample_kind in KINDS:
        data[sample_kind] = [sample['entry'] for sample in samples[sample_kind]]
    data[kind] = (data[kind]+[entry])[-6:]
    if kind=='normal':Image.fromarray(frame).save(normal_path)
    elif automatic and mode is None:Image.fromarray(frame).save(event_reference)
    pending = folder/f'samples_{token}.tmp'
    pending.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    pending.replace(folder/'samples.json')
