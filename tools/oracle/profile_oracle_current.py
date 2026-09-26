"""Profile the current Oracle without changing runtime code or config.

Uses real cached assets and a transparent QImage at 1x. Timings exclude asset
loading, warmup and cProfile. This does not measure Windows desktop composition.
Run with the rw_pet Python, optionally passing --ticks and --profile-ticks.
"""
import os
import sys
if '--desktop-seconds' not in sys.argv:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import cProfile
import ctypes
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import pstats
import statistics
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.oracle.appearance import OracleAppearance
from rw_creature_pet.oracle.behavior import OracleBehavior
from rw_creature_pet.oracle.cords import Rope
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.navigation import FloatNavigator
from rw_creature_pet.oracle.pearl_fixed import FixedPearls
from rw_creature_pet.oracle.pearl_matrix import PearlMatrix
from rw_creature_pet.oracle.pearl_orbits import PearlOrbits
from rw_creature_pet.oracle.render import OracleRenderer, PaintCommands
from rw_creature_pet.oracle.scene import FixedOracleArm, OracleScene


def summary(values):
    values = sorted(values)
    return dict(n=len(values), mean_ms=statistics.mean(values)*1000,
                p95_ms=values[int((len(values)-1)*.95)]*1000,
                max_ms=values[-1]*1000) if values else dict(n=0)


def physical_work_area():
    if sys.platform != 'win32':
        return 1920, 1080
    from ctypes import wintypes
    user = ctypes.windll.user32
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    try:
        rect = wintypes.RECT()
        if not user.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0):
            raise ctypes.WinError()
        return rect.right-rect.left, rect.bottom-rect.top
    finally:
        if previous:
            user.SetThreadDpiAwarenessContext(previous)


@contextmanager
def measure_sections():
    spent, calls, originals = defaultdict(float), Counter(), []
    replay_depth = 0

    def patch(cls, name, label):
        old = getattr(cls, name)
        originals.append((cls, name, old))

        def measured(self, *args, **kwargs):
            nonlocal replay_depth
            key = label(self, *args, **kwargs) if callable(label) else label
            if key is None:
                return old(self, *args, **kwargs)
            if key == 'qt_command_replay' and replay_depth:
                return old(self, *args, **kwargs)
            if key == 'qt_command_replay':
                replay_depth += 1
            start = perf_counter()
            try:
                return old(self, *args, **kwargs)
            finally:
                spent[key] += perf_counter()-start
                calls[key] += 1
                if key == 'qt_command_replay':
                    replay_depth -= 1
        setattr(cls, name, measured)

    patch(Rope, 'step', lambda self, *a, **k: 'rope_main' if len(self.points)>30 else 'rope_fine')
    for cls, method, label in (
        (OracleAppearance, 'step_cloth', 'cloth'),
        (OracleAppearance, 'step_necklace', 'necklace'),
        (FixedOracleArm, 'step', 'arm'),
        (OracleBehavior, 'step', 'behavior'),
        (FloatNavigator, 'step', 'navigation'),
        (FixedPearls, 'step', 'fixed_satellites'),
        (PearlMatrix, 'step', 'matrix'),
        (PearlOrbits, 'step', 'orbits'),
        (OracleRenderer, 'draw_geometry', 'geometry_build'),
        (OracleRenderer, 'draw_cords', 'cord_geometry'),
        (OracleRenderer, 'draw_arm', 'arm_geometry'),
        (OracleRenderer, 'draw_body', 'body_geometry'),
        (OracleRenderer, 'draw_body_front', 'body_front_geometry'),
        (OracleRenderer, 'draw_pearl', 'pearl_paint'),
        (OracleRenderer, 'draw_scene_head', 'head_paint'),
    ):
        patch(cls, method, label)
    patch(PaintCommands, 'replay', lambda self, painter:
          'qt_command_replay' if isinstance(painter, QPainter) else None)
    try:
        yield spent, calls
    finally:
        for cls, name, old in reversed(originals):
            setattr(cls, name, old)


def draw(renderer, scene, image, alpha=1., cords=True):
    image.fill(0)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.draw(painter, scene, alpha, cords=cords)
    finally:
        painter.end()


def benchmark(config, renderer, size, ticks, *, moving):
    scene = OracleScene(replace(config.oracle, world_width=size[0], world_height=size[1]))
    for _ in range(1400):
        scene.step()
    if moving:
        scene.start_lap()
    image = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
    draw(renderer, scene, image)
    samples, frames = defaultdict(list), defaultdict(list)
    iterations = Counter()
    edges = Counter()
    sleeping_ticks = 0
    with measure_sections() as (spent, calls):
        for tick in range(ticks):
            spent.clear()
            t = perf_counter()
            scene.step()
            samples['total'].append(perf_counter()-t)
            for key in ('rope_main', 'rope_fine', 'cloth', 'necklace', 'arm',
                        'behavior', 'navigation', 'fixed_satellites', 'matrix', 'orbits'):
                samples[key].append(spent[key])
            sleeping_ticks += scene.appearance.sleeping
            b = scene.base
            distances = (b.y, size[0]-b.x, size[1]-b.y, b.x)
            edges[min(range(4), key=lambda i: distances[i])] += 1
            iterations[f'main:{scene.appearance.cords.main.iterations}'] += 1
            for rope in scene.appearance.cords.fine:
                iterations[f'fine:{rope.iterations}'] += 1
            # Exact 40/30 Hz event ordering: render after ticks 1, 2, 4.
            if tick % 4 != 2:
                alpha = (1/3, 2/3, 0., 0.)[tick % 4]
                spent.clear()
                t = perf_counter()
                draw(renderer, scene, image, alpha)
                frames['total'].append(perf_counter()-t)
                for key in ('geometry_build', 'cord_geometry', 'arm_geometry', 'body_geometry',
                            'body_front_geometry', 'qt_command_replay', 'pearl_paint', 'head_paint'):
                    frames[key].append(spent[key])
            if moving and scene.arrived:
                break
    simulation = {k:summary(v) for k,v in samples.items()}
    rendering = {k:summary(v) for k,v in frames.items()}
    return dict(size=size, moving=moving, simulation=simulation, rendering=rendering,
                sleeping_ticks=sleeping_ticks, base_edges=dict(edges), iterations=dict(iterations),
                measured_cpu_work_ms_per_simulated_second=(simulation['total']['mean_ms']*40
                    + rendering['total']['mean_ms']*30),
                note='Section wrappers have small overhead; geometry subcategories overlap geometry_build. '
                     'Wall timings, not Task Manager CPU percentages. Includes clear, excludes Windows compositor.'), scene


def benchmark_desktop(app, config, renderer, seconds, output, prefix, idle=False):
    """Short-lived real click-through desktop window; exits automatically."""
    from PySide6.QtCore import QTimer
    from rw_creature_pet.oracle.desktop import OracleDesktopWindow
    paint_times, step_times, renderer_times = [], [], []
    state = {'active': False}

    class MeasuredWindow(OracleDesktopWindow):
        def paintEvent(self, event):
            start = perf_counter()
            super().paintEvent(event)
            if state['active']:
                paint_times.append(perf_counter()-start)

    window = MeasuredWindow(config, renderer=renderer)
    scene = window.motion.scene
    scene.set_autonomous(False)
    for _ in range(1400):
        scene.step()
    original_step, original_draw = scene.step, renderer.draw

    def step():
        start = perf_counter()
        original_step()
        if state['active']:
            step_times.append(perf_counter()-start)

    def render(*args, **kwargs):
        start = perf_counter()
        original_draw(*args, **kwargs)
        if state['active']:
            renderer_times.append(perf_counter()-start)

    scene.step, renderer.draw = step, render
    window.last_time = perf_counter()
    window.clock.accumulator = 0.

    def begin():
        if not idle:
            scene.start_lap()
        window.last_time = perf_counter()
        window.clock.accumulator = 0.
        window.clock.dropped_seconds = 0.
        state.update(active=True, start=perf_counter(), cpu=process_time())
        QTimer.singleShot(round(seconds*1000), finish)

    def finish():
        elapsed, cpu = perf_counter()-state['start'], process_time()-state['cpu']
        state['active'] = False
        window.timer.stop()
        result = dict(wall_seconds=elapsed, process_cpu_seconds=cpu,
                      idle=idle, halo_enabled=scene.config.halo_enabled,
                      one_core_percent=cpu/elapsed*100,
                      machine_normalized_percent=cpu/elapsed/os.cpu_count()*100,
                      logical_cpus=os.cpu_count(), physics_hz=len(step_times)/elapsed,
                      paint_hz=len(paint_times)/elapsed,
                      dropped_seconds=window.clock.dropped_seconds,
                      simulation=summary(step_times), paint_event=summary(paint_times),
                      renderer=summary(renderer_times),
                      world_size=[scene.world.width, scene.world.height],
                      dpr=window.motion.viewport.dpr,
                      physical_scale=window.motion.viewport.physical_scale,
                      note='Native Qt/Windows click-through desktop, top-edge lap segment. '
                           'CPU time includes this process only; not Windows DWM.')
        (output/f'{prefix}-desktop.json').write_text(
            json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2), flush=True)
        window.quit_pet()

    QTimer.singleShot(1000, begin)
    app.exec()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticks', type=int, default=2400)
    parser.add_argument('--profile-ticks', type=int, default=240)
    parser.add_argument('--desktop-seconds', type=float, default=0.)
    parser.add_argument('--desktop-idle', action='store_true')
    parser.add_argument('--no-halo', action='store_true', help='仅在本次内存配置中关闭光环，供性能对照')
    parser.add_argument('--output-prefix', default='oracle-current-performance')
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    config = AppConfig.load(ROOT/'config.toml')
    if args.no_halo:
        config = replace(config, oracle=replace(config.oracle, halo_enabled=False))
    digest = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    atlas = Atlas(extract_atlas(config.game_dir))
    renderer = OracleRenderer(atlas, config.oracle.colors,
                             glyphs=load_pearl_glyphs(config.game_dir, atlas.root))
    output = ROOT/'artifacts'
    output.mkdir(exist_ok=True)
    if args.desktop_seconds:
        benchmark_desktop(app, config, renderer, args.desktop_seconds, output, args.output_prefix, args.desktop_idle)
        assert digest == hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
        return
    size = physical_work_area()
    result = dict(config_sha256=digest, python=platform.python_version(),
                  logical_cpus=os.cpu_count(), physical_work_area=size,
                  counts=dict(matrix=config.oracle.pearl_matrix_count, inner=config.oracle.pearl_inner_count,
                              outer=config.oracle.pearl_outer_count, fixed=config.oracle.pearl_fixed_count,
                              satellites=config.oracle.pearl_satellite_count), cases=[])
    for dimensions, moving, ticks in (((960,600), True, args.ticks),
                                      (size, True, args.ticks), (size, False, 400)):
        case, scene = benchmark(config, renderer, dimensions, ticks, moving=moving)
        result['cases'].append(case)
        print(json.dumps(dict(size=dimensions, moving=moving,
                         simulation_ms=case['simulation']['total']['mean_ms'],
                         render_ms=case['rendering']['total']['mean_ms'],
                         asleep=case['sleeping_ticks']), ensure_ascii=False), flush=True)
    scene = OracleScene(replace(config.oracle, world_width=size[0], world_height=size[1]))
    scene.start_lap()
    for _ in range(80):
        scene.step()
    image = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
    profile = cProfile.Profile()
    profile.enable()
    for tick in range(args.profile_ticks):
        scene.step()
        if tick % 4 != 2:
            draw(renderer, scene, image, (1/3,2/3,0.,0.)[tick%4])
    profile.disable()
    profile.dump_stats(str(output/f'{args.output_prefix}.pstats'))
    with (output/f'{args.output_prefix}-profile.txt').open('w', encoding='utf-8') as stream:
        pstats.Stats(profile, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(65)
        pstats.Stats(profile, stream=stream).strip_dirs().sort_stats('tottime').print_stats(65)
    assert digest == hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    (output/f'{args.output_prefix}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f'Saved artifacts/{args.output_prefix}.json and profile.txt', flush=True)


if __name__ == '__main__':
    main()
