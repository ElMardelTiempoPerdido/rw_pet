"""在项目根目录运行：python tools/lizard/measure_wall_rhythm.py before|after。"""
import json
from math import cos, sin, pi
from pathlib import Path
from statistics import mean
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
(Path(__file__).resolve().parents[2]/'artifacts').mkdir(exist_ok=True)
from rw_creature_pet.lizard.background import BackgroundGrip
from rw_creature_pet.lizard.config import DebugConfig
from rw_creature_pet.lizard.gait import FootPhase
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.lizard.scene import DebugScene


def scene(angle, tracking):
    s = DebugScene(DebugConfig(world_width=10000, world_height=10000, floor_y=9800))
    s.place_on_background(4800)
    center = s.body.chunks[1].position
    for p in [*s.body.chunks, s.appearance.head, *s.appearance.tail]:
        d = p.position-center
        p.position = center+Vec2(d.x*cos(angle)-d.y*sin(angle), d.x*sin(angle)+d.y*cos(angle))
        p.previous_position = p.position
    s.background = BackgroundGrip(s.body)
    s.background.set_enabled(True, s.body, s.world)
    direction = Vec2(cos(angle), sin(angle))
    if tracking: s.background.set_goal(center+direction*3500, s.body, s.world)
    else: s.background.set_direction(direction)
    return s


def measure(s, warmup=200, ticks=1200):
    for _ in range(warmup): s.step()
    start = s.body.chunks[1].position
    last = [None]*4
    strides = [[] for _ in s.feet]
    durations = [[] for _ in s.feet]
    minimum_grips, air_ticks, sliding = 4, 0, 0
    for _ in range(ticks):
        old = [(f.phase, f.position) for f in s.feet]
        s.step()
        minimum_grips = min(minimum_grips, s.background.grip_count)
        for i, (f, (phase, pos)) in enumerate(zip(s.feet, old)):
            air_ticks += f.phase == FootPhase.AIR
            sliding += f.phase == phase == FootPhase.STANCE and f.position != pos
            if f.phase == FootPhase.STANCE and phase == FootPhase.SWING:
                if last[i] is not None: strides[i].append((f.position-last[i]).length())
                last[i] = f.position
                durations[i].append(f.swing_tick)
    return dict(body_units_per_second=(s.body.chunks[1].position-start).length()/(ticks/40),
                mean_stride=[mean(x) if x else 0 for x in strides],
                steps_per_second=[len(x)/(ticks/40) for x in durations],
                swing_ticks=[sorted(set(x)) for x in durations],
                minimum_grips=minimum_grips, air_ticks=air_ticks, sliding_ticks=sliding)


if __name__ == '__main__':
    results=[]
    for tracking in (False, True):
        for i in range(8):
            result=measure(scene(i*pi/4, tracking))
            result.update(degrees=i*45, tracking=tracking)
            results.append(result)
    label=sys.argv[1] if len(sys.argv)>1 else 'after'
    (Path(__file__).resolve().parents[2]/'artifacts'/f'wall-rhythm-{label}.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    for tracking in (False, True):
        rows=[r for r in results if r['tracking']==tracking]
        print('track' if tracking else 'slow',
              'speed', [round(r['body_units_per_second'],2) for r in rows],
              'stride', [round(v,2) for v in rows[0]['mean_stride']],
              'cadence', [round(v,2) for v in rows[0]['steps_per_second']],
              'min grips', min(r['minimum_grips'] for r in rows),
              'air/slips', sum(r['air_ticks']+r['sliding_ticks'] for r in rows))
