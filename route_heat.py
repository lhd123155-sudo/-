"""Register a gameplay viewport and a tracked player on an existing route image."""
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image

from auto_capture import Detector, config_dir
from route_capture import best_route, viewport
from scroll_mapping import ScrollMapper


def review_route(repo, root, sessions):
    # Once a route carries locations, keep using that image's coordinate system.
    root = root.resolve()
    for session in sessions:
        for event in reversed(repo.events(session['id'])):
            key = event.get('route_map')
            if key and event.get('area_width') is None:
                path = (root/key).resolve()
                if path.is_relative_to(root) and path.is_file():
                    return path
    return best_route(root, sessions)


def route_deaths(events, key):
    return [(event['x'], event['y']) for event in events
            if event['type']=='死亡' and event.get('route_map')==key
            and event['x'] is not None and event['y'] is not None
            and event.get('area_width') is None and event.get('area_height') is None]


def player_template(game, level):
    if game != 'I Wanna Maker':
        return None
    own = config_dir(level)/'player.png'
    paths = [own] if own.exists() else sorted(own.parent.parent.glob('*/player.png'))
    for path in paths:
        try:
            with Image.open(path) as image:
                return np.array(image.convert('RGBA' if 'A' in image.getbands() else 'RGB'))
        except OSError:
            continue
    return None


def sprite_templates(game, level):
    primary = player_template(game, level)
    templates = [primary] if primary is not None else []
    if game == 'I Wanna Maker':
        for path in sorted(config_dir(level).glob('player_*.png')):
            try:
                with Image.open(path) as image:
                    templates.append(np.array(image.convert('RGBA')))
            except OSError:
                continue
    return templates


def match_sprite(frame, sprite):
    height, width = sprite.shape[:2]
    if height > frame.shape[0] or width > frame.shape[1]:
        return None
    for head_only in (False, True):
        target = sprite[:max(6, height//2)] if head_only else sprite
        scores = None
        for variant in (target, np.ascontiguousarray(target[:, ::-1])):
            distance = cv2.matchTemplate(frame, np.ascontiguousarray(variant[:, :, :3]),
                                         cv2.TM_SQDIFF_NORMED, mask=np.ascontiguousarray(variant[:, :, 3]))
            distance = np.nan_to_num(distance, nan=2., posinf=2., neginf=2.)
            scores = distance if scores is None else np.minimum(scores, distance)
        best, _, (x, y), _ = cv2.minMaxLoc(scores)
        if best > (.065 if head_only else .10):
            continue
        scores[max(0,y-height):y+height+1, max(0,x-width):x+width+1] = 2.
        if float(scores.min())-best < .035:
            continue
        if head_only:
            # Confirm the blue outfit beneath the head, even when the pose changes.
            body = frame[y+height//2:y+height+3, max(0,x-4):x+width+4].astype(np.int16)
            blue = (body[:,:,2] > body[:,:,0]+20) & (body[:,:,2] > body[:,:,1]+14)
            if blue.sum() < 12:
                continue
        return x, y
    return None


class HeatLocator:
    def __init__(self, path, game, level, template):
        self.path = path
        self.game = game
        self.level = level
        templates = template if isinstance(template, list) else ([template] if template is not None else [])
        self.sprites = [sample for sample in templates if sample.shape[2] == 4]
        unmasked = next((sample for sample in templates if sample.shape[2] == 3), None)
        self.tracker = Detector(unmasked, unmasked, (0, 0, 0, 0), (0, 0)) if unmasked is not None else None
        self.recent = deque(maxlen=12)
        self.rechecks = {}
        self.last_remember = 0.
        self.rect = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.last_submit = 0.
        self.last_point = None
        self.ignore_before = 0.
        self.registration = None
        self.tiles = []
        self.last_tile = None

    def prepare(self, frame):
        with Image.open(self.path) as image:
            atlas = np.array(image.convert('RGB'))
        height, width = frame.shape[:2]
        atlas_height, atlas_width = atlas.shape[:2]
        self.atlas_size = atlas_width, atlas_height
        self.registration = ScrollMapper(frame)
        if atlas_height < height or atlas_width < width:
            return
        xs = list(range(0, atlas_width-width+1, max(1, width//2)))
        ys = list(range(0, atlas_height-height+1, max(1, height//2)))
        for y in sorted(set(ys+[atlas_height-height])):
            for x in sorted(set(xs+[atlas_width-width])):
                crop = atlas[y:y+height, x:x+width]
                points, descriptors = self.registration.features(crop)
                if descriptors is not None:
                    self.tiles.append(dict(kp=points, desc=descriptors, offset=(x,y)))

    def locate(self, full_frame):
        if self.rect is None:
            self.rect = viewport(full_frame, self.game, self.level)
        x, y, width, height = self.rect
        frame = full_frame[y:y+height, x:x+width]
        if self.registration is None:
            self.prepare(frame)
        if frame.shape[:2] != (self.registration.h, self.registration.w):
            return None
        player = None
        exclude = None
        for sprite in self.sprites:
            location = match_sprite(frame, sprite)
            if location is not None:
                player_height, player_width = sprite.shape[:2]
                player = (location[0]+player_width/2, location[1]+player_height/2)
                exclude = (*location, player_width, player_height)
                break
        if player is None and self.tracker is not None:
            score, location = self.tracker.track_player(frame)
            if location is not None and score >= (.80 if self.tracker.last_point is not None else .88):
                player_height, player_width = self.tracker.player.shape[:2]
                player = (location[0]+player_width/2, location[1]+player_height/2)
                exclude = (*location, player_width, player_height)
        if player is None:
            return None
        points, descriptors = self.registration.features(frame, exclude)
        candidates = []
        tiles = self.tiles if self.last_tile is None else [self.last_tile]+[tile for tile in self.tiles if tile is not self.last_tile]
        for tile in tiles:
            match = self.registration.translation(points, descriptors, tile)
            if match is not None:
                candidates.append((match[1], match[0], tile))
                if tile is self.last_tile and match[1] >= 35:
                    break
        if not candidates:
            return None
        candidates.sort(key=lambda value:value[0], reverse=True)
        support, offset, tile = candidates[0]
        if any(count >= .9*support and np.linalg.norm(other-offset) > 24 for count,other,_ in candidates[1:]):
            return None
        self.last_tile = tile
        atlas_width, atlas_height = self.atlas_size
        if self.tracker is not None:
            self.tracker.last_point = player
        point = ((offset[0]+player[0])/atlas_width, (offset[1]+player[1])/atlas_height)
        return tuple(float(value) for value in point) if all(0 <= value <= 1 for value in point) else None

    def collect(self):
        if self.pending and self.pending[1].done():
            captured, future = self.pending
            self.pending = None
            point = future.result()
            if captured >= self.ignore_before and point is not None:
                self.last_point = (captured, point)

    def offer(self, frame, now):
        self.collect()
        if self.pending is None and now-self.last_submit >= .16:
            self.last_submit = now
            self.pending = (now, self.executor.submit(self.locate, frame.copy()))

    def remember(self, frame, now):
        if now-self.last_remember >= .075:
            self.recent.append((now, frame))
            self.last_remember = now

    def recheck_death(self, event_id, now):
        frames = [frame for stamp, frame in reversed(self.recent) if now-stamp <= 1.0][:6]
        self.recent.clear()
        if frames and len(self.rechecks) < 6:
            self.rechecks[event_id] = self.executor.submit(self.find_in_frames, frames)

    def find_in_frames(self, frames):
        for frame in frames:
            try:
                point = self.locate(frame)
            except (cv2.error, OSError, ValueError):
                continue
            if point is not None:
                return point
        return None

    def completed_rechecks(self):
        results = []
        for event_id, future in list(self.rechecks.items()):
            if future.done():
                del self.rechecks[event_id]
                point = future.result()
                if point is not None:
                    results.append((event_id, point))
        return results

    def death_point(self, now):
        self.collect()
        result = self.last_point
        self.invalidate(now)
        if result and now-result[0] <= .5:
            return result[1]
        return None

    def invalidate(self, now):
        self.ignore_before = now
        self.last_point = None

    def close(self):
        self.executor.shutdown(wait=True)
