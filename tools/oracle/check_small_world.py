"""验证 640×385：使用正式尺寸校验，不改变用户设置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from collections import Counter
from dataclasses import replace
import hashlib
import json
from math import isfinite
from pathlib import Path
import sys
from time import perf_counter
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.behavior.controller import Activity
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.pearls.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.desktop import current_anchor
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.geometry import Vec2

OUT = ROOT/'artifacts/small-world'
OUT.mkdir(parents=True, exist_ok=True)
BASE = AppConfig.load(ROOT/'config.toml')
CONFIG_HASH = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
RESULTS = []
RENDERER = None


def make_scene(height=385., **changes):
    cfg = replace(BASE.oracle, world_width=640., world_height=height, **changes)
    return OracleScene(cfg)


def snapshot(scene, name):
    image = QImage(2560, round(scene.world.height*4), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('#182630'))
    p = QPainter(image)
    try:
        p.scale(4, 4)
        RENDERER.draw(p, scene, 1., raster_scale=4.)
    finally:
        p.end()
    image.save(str(OUT/(name+'.png')))


def in_band(p, scene):
    w, hole = scene.world, scene.world.inner
    return (-1e-5 <= p.x <= w.width+1e-5 and -1e-5 <= p.y <= w.height+1e-5
            and not (hole.left+1e-5 < p.x < hole.right-1e-5 and hole.top+1e-5 < p.y < hole.bottom-1e-5))


class Audit:
    def __init__(self, scene, name):
        self.s, self.name = scene, name
        self.ticks = 0
        self.errors = Counter()
        self.first = {}
        self.states, self.edges = set(), set()
        self.max_arm_error = self.max_body_step = 0.
        self.min_angle = self.max_angle = 0.

    def flag(self, name, detail=''):
        self.errors[name] += 1
        if name not in self.first:
            self.first[name] = {'tick': self.ticks, 'detail': str(detail)}
            snapshot(self.s, self.name+'-'+name)

    def step(self):
        s = self.s
        old = s.body.chunks[0].position
        s.step()
        self.ticks += 1
        self.states.add(s.behavior.state.name)
        self.edges.add(current_anchor(s)[0].value)
        self.max_arm_error = max(self.max_arm_error, s.arm.constraint_error)
        self.max_body_step = max(self.max_body_step, (s.body.chunks[0].position-old).length())
        self.min_angle = min(self.min_angle, s.pose.angle)
        self.max_angle = max(self.max_angle, s.pose.angle)
        if s.arm.constraint_error > .2:
            self.flag('arm_constraint', s.arm.constraint_error)
        if abs((s.body.chunks[0].position-s.body.chunks[1].position).length()-9.) > 1e-5:
            self.flag('body_length')
        if not s.drag.controlling and not s.navigator.region.contains(s.body.chunks[0].position):
            self.flag('body_center_outside', s.body.chunks[0].position)
        if self.ticks % 10:
            return
        points = [p.position for p in (*s.body.chunks, *s.arm.joints, *s.appearance.points)]
        if not all(isfinite(v) for point in points for v in (point.x, point.y)):
            self.flag('non_finite')
        if not s.drag.controlling:
            if not all(s.arm_region.segment_safe(a.position, b.position)
                       for a, b in zip(s.arm.joints, s.arm.joints[1:])):
                self.flag('arm_segment_outside')
            bad = [p.position for p in s.appearance.body_points if not in_band(p.position, s)]
            if bad:
                self.flag('puppet_points_outside', bad[:2])
        for name, group in (('matrix', s.pearl_matrix), ('orbits', s.pearl_orbits), ('fixed', s.fixed_pearls)):
            if group is None:
                continue
            for p, _, _ in group.samples(1.):
                # 包含珠体与字符，不含允许进入中央的光环、电弧、软线缆
                corners = [p+Vec2(x, y) for x in (-4., 15.) for y in (-15., 4.)]
                if not all(in_band(q, s) for q in corners):
                    self.flag(name+'_visible_outside', p)
                    break

    def run(self, count, done=None):
        for _ in range(count):
            self.step()
            if done is not None and done():
                return True
        return done is None

    def result(self):
        s = self.s
        return dict(ticks=self.ticks, simulated_seconds=self.ticks/40,
                    errors=dict(self.errors), first_errors=self.first,
                    max_arm_error=self.max_arm_error, max_body_step=self.max_body_step,
                    edges=sorted(self.edges), states=sorted(self.states),
                    pose_angle_range=(self.min_angle, self.max_angle),
                    sleeping=s.appearance.sleeping, arrived=s.arrived,
                    matrix_layout_scale=s.pearl_matrix.layout_scale if s.pearl_matrix else None)


def record(name, action):
    started = perf_counter()
    try:
        result = action()
    except Exception:
        result = {'exception': traceback.format_exc()}
    result.update(name=name, elapsed_seconds=round(perf_counter()-started, 3))
    RESULTS.append(result)
    (OUT/'results.json').write_text(json.dumps(dict(config_sha256=CONFIG_HASH, cases=RESULTS),
                                             ensure_ascii=False, indent=2), encoding='utf-8')
    print(name, json.dumps({k:v for k,v in result.items() if k not in ('first_errors','exception')},
                          ensure_ascii=True), flush=True)
    if 'exception' in result:
        print(result['exception'], flush=True)


def stationary(side, **changes):
    s = make_scene(base_side=side, **changes)
    a = Audit(s, 'idle-'+side)
    a.run(900)
    snapshot(s, 'idle-'+side)
    return a.result()


def lap(clockwise, **changes):
    s = make_scene(**changes)
    a = Audit(s, 'lap-'+str(clockwise))
    s.start_lap(clockwise)
    complete = a.run(6000, lambda: s.arrived)
    travel_ticks = a.ticks
    a.run(900)
    return dict(a.result(), complete=complete, travel_ticks=travel_ticks)


def read_matrix(side):
    s = make_scene(base_side=side)
    a = Audit(s, 'matrix-'+side)
    s.observe_matrix_pearl(s.pearl_matrix.pearls[0].slot)
    complete = a.run(7000, lambda: s.behavior.completed_cycles > 0 and s.pearl_matrix.extracted is None)
    a.run(900)
    return dict(a.result(), complete=complete)


def drag(side):
    s = make_scene(base_side=side)
    s.drag.set_enabled(True)
    a = Audit(s, 'drag-'+side)
    assert s.drag.press(s.body.chunks[0].position, lambda _: True)
    s.drag.move(Vec2(320., 192.5))
    a.run(240)
    s.drag.release()
    returned = a.run(2000, lambda: not s.drag.controlling)
    a.run(900)
    return dict(a.result(), returned=returned)


def drift():
    s = make_scene()
    a = Audit(s, 'drift')
    s.drift()
    duration = s.behavior.drift_duration
    complete = a.run(17000, lambda: not s.behavior.drift_active and s.pose.settled and s.arrived)
    a.run(900)
    return dict(a.result(), complete=complete, planned_duration=duration/40)


def crossing(side, sign):
    s = make_scene(base_side=side)
    a = Audit(s, 'drift-cross-'+side+str(sign))
    s.drift()
    s.behavior.drift_next_move = s.behavior.drift_next_observation = 100000
    a.run(130)
    destination = (('top', 'right', 'bottom', 'left').index(side)+sign) % 4
    started = s.behavior.start_drift_crossing(s, destination)
    complete = a.run(3000, lambda: s.behavior.state != Activity.DRIFT_CROSS_EDGE)
    snapshot(s, a.name)
    return dict(a.result(), started=started, complete=complete)


def main():
    global RENDERER
    app = QApplication.instance() or QApplication([])
    atlas = Atlas(extract_atlas(BASE.game_dir))
    RENDERER = OracleRenderer(atlas, BASE.oracle.colors, glyphs=load_pearl_glyphs(BASE.game_dir, atlas.root))
    for arm, fraction in ((.35,.2),(.6,.2),(.65,.2),(.7,.2),(.75,.2),(.75,.22),(.75,.25)):
        record(f'geometry-arm-{arm}-band-{fraction}', lambda arm=arm,fraction=fraction:
               stationary('top', arm_scale=arm, edge_fraction=fraction))
    for side in ('top', 'right', 'bottom', 'left'):
        record('idle-'+side, lambda side=side: stationary(side))
    for clockwise in (True, False):
        record('lap-'+str(clockwise), lambda clockwise=clockwise: lap(clockwise))
    for side in ('top', 'right', 'bottom', 'left'):
        record('matrix-'+side, lambda side=side: read_matrix(side))
        record('drag-'+side, lambda side=side: drag(side))
        for sign in (-1, 1):
            record('drift-cross-'+side+str(sign), lambda side=side,sign=sign: crossing(side, sign))
    record('drift-full-duration', drift)
    record('lap-max-arm-wider-band', lambda: lap(True, arm_scale=.75, edge_fraction=.25))
    assert hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest() == CONFIG_HASH


if __name__ == '__main__':
    main()
