"""Optimized Oracle: motion/idle timing, rope bounds, real atlas preview."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from collections import Counter
import hashlib
import gc
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)
from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.cords import Rope
from rw_creature_pet.oracle.debug_window import OracleDebugWindow, OracleCanvas
from rw_creature_pet.oracle.render import OracleRenderer
from review_oracle_cords import render


def summary(values):
    values = sorted(values)
    return dict(n=len(values), mean_ms=statistics.mean(values)*1000,
                p95_ms=values[int((len(values)-1)*.95)]*1000, max_ms=values[-1]*1000) if values else dict(n=0)


app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
config = AppConfig.load(ROOT/'config.toml')
atlas = Atlas(extract_atlas(config.game_dir))
renderer = OracleRenderer(atlas, config.oracle.colors)
result = dict(config_sha256=hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest(),
              note='Qt offscreen; 40 Hz physics, 30 fps debug rendering cap; physics timings exclude drawing and metric collection.')
scene = OracleScene(config.oracle)
scene.start_lap()
old_step = Rope.step
spent = dict(main=0., fine=0.)
def measured(self, *args, **kwargs):
    t = perf_counter()
    old_step(self, *args, **kwargs)
    spent['main' if len(self.points)>30 else 'fine'] += perf_counter()-t
Rope.step = measured
samples, poses, frames = [], [], []
iterations = Counter()
result.update(max_main_error=0., max_fine_error=0., max_central_penetration=0., max_outside_screen=0.)
for tick in range(2400):
    spent.update(main=0.,fine=0.)
    t = perf_counter()
    scene.step()
    samples.append(dict(total=perf_counter()-t, **spent))
    a = scene.appearance
    if scene.arrived and 'arrived_tick' not in result:
        result['arrived_tick'] = tick+1
    if a.sleeping and 'first_sleep_tick' not in result:
        result['first_sleep_tick'] = tick+1
    for label, ropes in (('main', [a.cords.main]), ('fine', a.cords.fine)):
        for rope in ropes:
            if tick < 1500:
                iterations[(label,rope.iterations)] += 1
            result['max_'+label+'_error'] = max(result['max_'+label+'_error'],
                max(abs((q.position-p.position).length()-rest) for p,q,rest in zip(rope.points,rope.points[1:],rope.rest)))
    h = scene.world.inner
    for point in a.main_cord:
        p = point.position
        result['max_central_penetration'] = max(result['max_central_penetration'], min(p.x-h.left,h.right-p.x,p.y-h.top,h.bottom-p.y))
        result['max_outside_screen'] = max(result['max_outside_screen'], -p.x, p.x-scene.world.width,-p.y,p.y-scene.world.height)
    if tick % 10 == 0:
        frames.append(render(scene, renderer, tick))
    if tick in (120,440,800,1200,1600,2399):
        poses.append(render(scene, renderer, tick, close=True))
    if (tick+1)%600 == 0:
        print('Replay:',tick+1,flush=True)
Rope.step = old_step
result['moving_simulation'] = {key:summary([v[key] for v in samples[:1500]]) for key in spent.keys()|{'total'}}
result['settled_simulation'] = summary([v['total'] for v in samples[-200:]])
result['iterations'] = {str(key):value for key,value in iterations.items()}
sheet = Image.new('RGB',(1200,680))
for i,pose in enumerate(poses):
    sheet.paste(pose,((i%3)*400,(i//3)*340))
sheet.save(ROOT/'artifacts/oracle-performance-poses.png')
frames[0].save(ROOT/'artifacts/oracle-performance-preview.gif',save_all=True,append_images=frames[1:],duration=250,loop=0)
del frames, poses, sheet
gc.collect()

old_paint = OracleCanvas.paintEvent
paint_times, paint_starts = [], []
def measured_paint(self,event):
    t=perf_counter()
    old_paint(self,event)
    paint_times.append(perf_counter()-t)
    paint_starts.append(t)
OracleCanvas.paintEvent = measured_paint
result['qt_offscreen'] = {}
for label in ('moving','idle'):
    window = OracleDebugWindow(config,load_atlas=False)
    window.renderer = window.canvas.renderer = OracleRenderer(atlas, config.oracle.colors)
    window.timer.stop()
    if label == 'moving':
        window.scene.start_lap()
    else:
        for _ in range(700):
            window.scene.step()
        assert window.scene.appearance.sleeping
    window.show()
    window.refresh()
    app.processEvents()
    paint_times.clear(); paint_starts.clear()
    tick_start = window.scene.ticks
    window.last_time = perf_counter()
    window.timer.start(16)
    start, cpu = perf_counter(), process_time()
    QTimer.singleShot(8000 if label == 'moving' else 4000,app.quit)
    app.exec()
    duration, used = perf_counter()-start, process_time()-cpu
    result['qt_offscreen'][label] = dict(elapsed_seconds=duration, cpu_seconds=used,
        one_core_percent=used/duration*100, ticks=window.scene.ticks-tick_start,
        paint=summary(paint_times), paint_interval=summary([b-a for a,b in zip(paint_starts,paint_starts[1:])]),
        paints_per_second=len(paint_times)/duration, dropped_seconds=window.clock.dropped_seconds)
    window.close(); app.processEvents()
    print(label,result['qt_offscreen'][label],flush=True)
OracleCanvas.paintEvent = old_paint
result['config_unchanged'] = result['config_sha256'] == hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
(ROOT/'artifacts/oracle-performance-after.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('Simulation:',result['moving_simulation'],flush=True)
