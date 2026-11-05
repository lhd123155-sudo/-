from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image

from auto_capture import config_dir
from scroll_mapping import ScrollMapper


def viewport(frame, game, level):
    height, width = frame.shape[:2]
    if game == 'I Wanna Maker':
        try:
            config = json.loads((config_dir(level) / 'config.json').read_text(encoding='utf-8'))
            rect = config.get('viewport')
            if rect and config.get('capture_size') == [width, height]:
                x, y, w, h = rect
                if x >= 0 and y >= 0 and w > 0 and h > 0 and x+w <= width and y+h <= height:
                    return tuple(rect)
        except (OSError, ValueError, TypeError):
            pass
    # A sidebar usually forms a strong vertical seam along nearly the whole screen.
    # Reject weak seams so level geometry is not routinely cropped out.
    delta = np.abs(np.diff(frame[height//20:height-height//20].astype(np.int16), axis=1)).mean(axis=2)
    start, end = int(width*.60), int(width*.90)
    strength = (delta[:, start:end] > 20).mean(axis=0)
    if len(strength):
        seam = int(np.argmax(strength)) + start
        if strength.max() >= .76:
            return 0, 0, seam+1, height
    return 0, 0, width, height


def is_edge_transition(frame, previous):
    """Reject a new flat overlay sweeping in from the right edge."""
    height, width = frame.shape[:2]
    rows = slice(height//8, 7*height//8)
    edge = frame[rows, width-4:width-1:2].reshape(-1, 3)
    colors, counts = np.unique(edge, axis=0, return_counts=True)
    largest = int(np.argmax(counts))
    if counts[largest] < .7*len(edge):
        return False
    color = colors[largest]
    area = (rows, slice(int(width*.65), width))
    current = np.all(frame[area] == color, axis=2).mean()
    before = np.all(previous[area] == color, axis=2).mean()
    return current > .42 and current - before > .35


def best_route(root, sessions):
    best_path = None
    largest_area = 0
    for session in sessions:
        for path in sorted((root / session['id']).glob('地图-*.png')):
            try:
                with Image.open(path) as image:
                    area = image.width * image.height
            except (OSError, ValueError):
                continue
            if area > largest_area:
                best_path = path
                largest_area = area
    return best_path


class RouteRecorder:
    def __init__(self, folder, game, level):
        self.folder = Path(folder)
        self.game = game
        self.level = level
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.mapper = None
        self.rect = None
        self.segment = 0
        self.misses = 0
        self.last_submit = 0
        self.last_checkpoint = 0
        self.previous_frame = None

    def offer(self, frame):
        now = time.monotonic()
        if self.pending is not None:
            if not self.pending.done():
                return
            pending, self.pending = self.pending, None
            pending.result()
        if now-self.last_submit >= .18:
            self.last_submit = now
            self.pending = self.executor.submit(self.add_frame, frame.copy())

    def add_frame(self, frame):
        if self.rect is None:
            self.rect = viewport(frame, self.game, self.level)
        x, y, width, height = self.rect
        cropped = frame[y:y+height, x:x+width].copy()
        if self.previous_frame is not None and is_edge_transition(cropped, self.previous_frame):
            return
        if self.mapper is None:
            self.mapper = ScrollMapper(cropped)
        elif self.mapper.locate(cropped) is None:
            self.misses += 1
            if self.misses >= 3:
                self.save_segment()
                self.mapper = ScrollMapper(cropped)
                self.misses = 0
        else:
            self.misses = 0
        if self.misses == 0:
            self.previous_frame = cropped
            now = time.monotonic()
            if now - self.last_checkpoint >= 5:
                self.write_map()
                self.last_checkpoint = now

    def write_map(self):
        if self.mapper is None:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        destination = self.folder / f'地图-{self.segment+1:02d}.png'
        temporary = destination.with_suffix('.tmp')
        Image.fromarray(self.mapper.image).save(temporary, format='PNG')
        temporary.replace(destination)
    def save_segment(self):
        if self.mapper is not None:
            self.write_map()
            self.segment += 1

    def finish(self):
        try:
            if self.pending is not None:
                self.pending.result()
        finally:
            self.executor.shutdown(wait=True)
            self.save_segment()
