"""Compare cable boundary checks in isolated replay; no production edits."""
import hashlib
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.scene import OracleScene


class UnrestrictedGuide:
    def segment_safe(self, a, b):
        return True


def disable_main_boundaries(scene):
    cords = scene.appearance.cords
    cords.sweep_region = UnrestrictedGuide()
    step = cords.main.step
    def unconstrained(pins, **kwargs):
        kwargs['region'] = None
        kwargs['sweep_region'] = None
        return step(pins, **kwargs)
    cords.main.step = unconstrained


def xy(p):
    return [p.x, p.y]


config = AppConfig.load(ROOT/'config.toml')
results = dict(config_sha256=hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest(),
               description='Remove main node/segment/sweep region checks and guide motion veto only. Keep pins, length solver, supply routing, junction radius 24 and fine radius 32.',
               scenarios={})
for label, unrestricted, clockwise in (
        ('baseline_clockwise', False, True),
        ('unchecked_clockwise', True, True),
        ('unchecked_counterclockwise', True, False)):
    scene = OracleScene(config.oracle)
    if unrestricted:
        disable_main_boundaries(scene)
    scene.start_lap(clockwise)
    timings = []
    record = dict(central_node_ticks=0, central_sample_ticks=0,
                  outside_screen_ticks=0, max_node_depth=0., max_sample_depth=0.,
                  max_outside_screen=0., max_link_error=0., worst=None)
    h = scene.world.inner
    def penetration(p):
        return max(0., min(p.x-h.left, h.right-p.x, p.y-h.top, h.bottom-p.y))
    for tick in range(1800):
        start = perf_counter()
        scene.step()
        timings.append(perf_counter()-start)
        if scene.arrived and 'arrived_tick' not in record:
            record['arrived_tick'] = tick+1
        rope = scene.appearance.cords.main
        points = [p.position for p in rope.points]
        node_depth = max(map(penetration, points))
        sample_depth = max(node_depth, max(penetration(a.lerp(b,.5)) for a,b in zip(points,points[1:])))
        outside = max(max(0., -p.x, p.x-scene.world.width, -p.y, p.y-scene.world.height) for p in points)
        record['central_node_ticks'] += node_depth > 1e-6
        record['central_sample_ticks'] += sample_depth > 1e-6
        record['outside_screen_ticks'] += outside > 1e-6
        record['max_node_depth'] = max(record['max_node_depth'], node_depth)
        record['max_outside_screen'] = max(record['max_outside_screen'], outside)
        record['max_link_error'] = max(record['max_link_error'],
            max(abs((b-a).length()-rest) for a,b,rest in zip(points,points[1:],rope.rest)))
        if sample_depth > record['max_sample_depth']:
            record['max_sample_depth'] = sample_depth
            record['worst'] = dict(tick=tick, main=[xy(p) for p in points],
                arm=[xy(p.position) for p in scene.arm.joints],
                body=[xy(p.position) for p in scene.body.chunks],
                head=xy(scene.appearance.head.position),
                hole=[h.left,h.top,h.right,h.bottom])
        if (tick+1)%600 == 0:
            print(label, tick+1, 'max central depth', round(record['max_sample_depth'],3), flush=True)
    record['mean_step_ms'] = statistics.mean(timings)*1000
    record['mean_moving_step_ms'] = statistics.mean(timings[:1500])*1000
    record['p95_step_ms'] = sorted(timings)[int(len(timings)*.95)]*1000
    results['scenarios'][label] = record
    print(label, json.dumps({k:v for k,v in record.items() if k!='worst'}), flush=True)
results['config_unchanged'] = results['config_sha256'] == hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
(ROOT/'artifacts/oracle-cord-bounds-probe.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
