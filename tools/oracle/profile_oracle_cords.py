"""Read-only performance diagnosis; runtime wrappers do not change pet behavior."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import cProfile
import hashlib
import io
import json
from pathlib import Path
import pstats
import statistics
import sys
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.cords import Rope
from rw_creature_pet.oracle.debug_window import OracleDebugWindow, OracleCanvas
from rw_creature_pet.oracle.render import OracleRenderer


def summary(values):
    values = sorted(values)
    return dict(n=len(values), mean_ms=statistics.mean(values)*1000,
                p95_ms=values[int((len(values)-1)*.95)]*1000,
                max_ms=values[-1]*1000)


app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)
config = AppConfig.load(ROOT/'config.toml')
result = dict(config_sha256=hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest(),
              python=sys.version, note='Offscreen Qt; no production source/config edits. Timing without cProfile unless labeled.')
original_rope_step = Rope.step
spent = dict(main=0., fine=0.)


def timed_rope(self, *args, **kwargs):
    begin = perf_counter()
    original_rope_step(self, *args, **kwargs)
    spent['main' if len(self.points) > 30 else 'fine'] += perf_counter()-begin


Rope.step = timed_rope
scene = OracleScene(config.oracle)
scene.start_lap()
samples = []
snapshots = []
import copy
for tick in range(2200):
    spent.update(main=0., fine=0.)
    begin = perf_counter()
    scene.step()
    elapsed = perf_counter()-begin
    samples.append(dict(tick=tick, total=elapsed, **spent,
                        other=elapsed-spent['main']-spent['fine'],
                        sleeping=scene.appearance.sleeping,
                        fine_sleeping=sum(r.sleeping for r in scene.appearance.cords.fine)))
    if tick in (120, 440, 800, 1200, 2199):
        snapshots.append((tick, copy.deepcopy(scene)))
    if (tick+1) % 400 == 0:
        print('Replay ticks:', tick+1, flush=True)
Rope.step = original_rope_step
result['simulation'] = {}
for label, group in [('moving_0_1499', samples[:1500]), ('idle_2100_2199', samples[2100:]),
                     *[(f'block_{a}_{a+199}', samples[a:a+200]) for a in range(0, 2200, 200)]]:
    result['simulation'][label] = {k: summary([s[k] for s in group]) for k in ('total','main','fine','other')}
    result['simulation'][label]['appearance_sleep_ticks'] = sum(s['sleeping'] for s in group)
    result['simulation'][label]['fine_sleep_mean'] = statistics.mean(s['fine_sleeping'] for s in group)
print('Simulation summary:', json.dumps(result['simulation']['moving_0_1499']), flush=True)

renderer = OracleRenderer(Atlas(extract_atlas(config.game_dir)), config.oracle.colors)
image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
render_spent = {}
for name in ('draw_cords', 'draw_arm', 'draw_gown', 'draw_limbs', 'draw_head'):
    original = getattr(renderer, name)
    def timed(*args, _name=name, _original=original, **kwargs):
        begin = perf_counter()
        value = _original(*args, **kwargs)
        render_spent[_name] = render_spent.get(_name, 0.)+perf_counter()-begin
        return value
    setattr(renderer, name, timed)

result['render'] = {}
for scale in (1, 4):
    timings = []
    by_part = {k: [] for k in ('draw_cords','draw_arm','draw_gown','draw_limbs','draw_head')}
    for tick, snapshot in snapshots:
        for repeat in range(16):
            image.fill(QColor('#17232e'))
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if scale == 4:
                painter.setClipRect(0, 0, 250, 290)
                painter.translate(125, 145)
                painter.scale(4, 4)
                painter.translate(-snapshot.appearance.upper.x, -snapshot.appearance.upper.y)
            render_spent.clear()
            begin = perf_counter()
            renderer.draw(painter, snapshot, (repeat%4)/4)
            elapsed = perf_counter()-begin
            painter.end()
            if repeat > 1:  # Warm tinted images and arm geometry.
                timings.append(elapsed)
                for key in by_part:
                    by_part[key].append(render_spent[key])
    result['render'][f'scale_{scale}'] = dict(total=summary(timings),
        **{key: summary(values) for key, values in by_part.items()})
print('Render summary:', json.dumps(result['render']), flush=True)

profile_scene = OracleScene(config.oracle)
profile_scene.start_lap()
profiler = cProfile.Profile()
profiler.enable()
for _ in range(240):
    profile_scene.step()
profiler.disable()
stream = io.StringIO()
stats = pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats('cumulative')
stats.print_stats(45)
stats.sort_stats('tottime').print_stats(35)
(ROOT/'artifacts/oracle-cords-profile.txt').write_text(stream.getvalue(), encoding='utf-8')
profiler.dump_stats(str(ROOT/'artifacts/oracle-cords-profile.pstats'))
print('cProfile complete', flush=True)

# Real Qt event-loop timing, with atlas and the usual optional magnifier.
# Offscreen rendering is not a substitute for onscreen compositor/frame measurements.
original_paint = OracleCanvas.paintEvent
paint_samples = []
timer_samples = []
last_timer = None
def timed_paint(self, event):
    begin = perf_counter()
    original_paint(self, event)
    paint_samples.append(perf_counter()-begin)
OracleCanvas.paintEvent = timed_paint
result['qt_offscreen'] = {}
for magnifier in (True, False):
    window = OracleDebugWindow(config, load_atlas=False)
    window.renderer = renderer
    window.canvas.renderer = renderer
    window.canvas.magnifier = magnifier
    window.scene.start_lap()
    window.show()
    app.processEvents()
    paint_samples.clear()
    timer_samples.clear()
    last_timer = perf_counter()
    def timer_observer():
        global last_timer
        now = perf_counter()
        timer_samples.append(now-last_timer)
        last_timer = now
    window.timer.timeout.connect(timer_observer)
    begin, cpu_begin = perf_counter(), process_time()
    QTimer.singleShot(8000, app.quit)
    app.exec()
    wall, cpu = perf_counter()-begin, process_time()-cpu_begin
    result['qt_offscreen'][f'magnifier_{magnifier}'] = dict(
        elapsed_seconds=wall, process_cpu_seconds=cpu,
        one_logical_core_percent=cpu/wall*100, ticks=window.scene.ticks,
        dropped_seconds=window.clock.dropped_seconds,
        paint=summary(paint_samples), timer_gap=summary(timer_samples))
    window.close()
    app.processEvents()
    print('Qt loop:', magnifier, json.dumps(result['qt_offscreen'][f'magnifier_{magnifier}']), flush=True)
OracleCanvas.paintEvent = original_paint
result['config_sha256_after'] = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
(ROOT/'artifacts/oracle-cords-performance.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print('Saved artifacts/oracle-cords-performance.json', flush=True)
