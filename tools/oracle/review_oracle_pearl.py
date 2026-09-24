"""阶段 6：原版字形、两条观察分支的真实外观回放和独立运行开销。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import hashlib
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)
from PIL import Image
from PySide6.QtCore import QPointF, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QImage
from PySide6.QtWidgets import QApplication
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.debug_window import OracleCanvas, OracleDebugWindow
from rw_creature_pet.oracle.render import OracleRenderer


def summary(values):
    values = sorted(values)
    return dict(count=len(values), mean_ms=statistics.mean(values)*1000,
                p95_ms=values[int((len(values)-1)*.95)]*1000) if values else dict(count=0)


def main(timing_only=False):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    config = AppConfig.load(ROOT/'config.toml')
    atlas = Atlas(extract_atlas(config.game_dir))
    glyphs = load_pearl_glyphs(config.game_dir, atlas.root)
    renderer = OracleRenderer(atlas, config.oracle.colors, glyphs=glyphs)
    result_path = ROOT/'artifacts/oracle-pearl-metrics.json'
    result = (json.loads(result_path.read_text(encoding='utf-8')) if timing_only and result_path.exists() else {})
    result['config_sha256'] = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    if not timing_only:
        scenes = [OracleScene(config.oracle) for _ in range(2)]
        renderers = [OracleRenderer(atlas, config.oracle.colors, glyphs=glyphs) for _ in scenes]
        labels = ['靠近观察', '召近观察']
        traces, frames, poses = [[], []], [], []
        for scene, mode in zip(scenes, ('approach', 'recall')):
            scene.observe_pearl(mode)
        def render(tick):
            image = QImage(1080, 480, QImage.Format.Format_RGBA8888)
            image.fill(QColor('#17232e'))
            p = QPainter(image)
            try:
                p.setFont(QFont('Microsoft YaHei UI', 10))
                for i, (scene, r) in enumerate(zip(scenes, renderers)):
                    p.setPen(QColor('#dae5ea'))
                    p.drawText(QPointF(18+i*540, 26), f'{labels[i]} · {scene.behavior.state.value} · {tick/40:.1f}s')
                    p.drawText(QPointF(18+i*540, 46), '3× · 原版字形裁图 · 悬浮点保持不变')
                    p.save()
                    p.setClipRect(i*540, 55, 540, 425)
                    p.translate(i*540+110, 275)
                    p.scale(3, 3)
                    p.translate(-480, -82)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    r.draw(p, scene)
                    p.restore()
            finally:
                p.end()
            return Image.frombytes('RGBA', (1080, 480), bytes(image.constBits())).convert('RGB')
        for tick in range(1000):
            for i, scene in enumerate(scenes):
                scene.step()
                if not traces[i] or traces[i][-1]['state'] != scene.behavior.state.name:
                    traces[i].append(dict(tick=tick+1, state=scene.behavior.state.name,
                        separation=(scene.pearl.position-scene.body.chunks[0].position).length()))
            if tick < 540 and tick % 4 == 0:
                frames.append(render(tick+1))
            if tick in (25, 95, 225, 395):
                poses.append(render(tick+1))
        result['cycles'] = {label: dict(trace=trace, cycles=scene.behavior.completed_cycles,
            returned_error=(scene.pearl.position-scene.pearl.home).length(),
            glyph_id=scene.pearl.glyph_id, sleeping=scene.appearance.sleeping)
            for label, trace, scene in zip(labels, traces, scenes)}
        sheet = Image.new('RGB', (1080, 480*len(poses)))
        for i, pose in enumerate(poses):
            sheet.paste(pose, (0, i*480))
        sheet.save(ROOT/'artifacts/oracle-pearl-poses.png')
        frames[0].save(ROOT/'artifacts/oracle-pearl-preview.gif', save_all=True,
                       append_images=frames[1:], duration=100, loop=0)
        print('Replay complete', result['cycles'], flush=True)
        # 真实窗口：暂停在召近后的观察状态；保留用户配色和默认 1× 预览。
        window = OracleDebugWindow(config)
        window.timer.stop()
        window.scene.observe_pearl('recall')
        for _ in range(225):
            window.scene.step()
        window.set_paused(True)
        window.show()
        window.refresh()
        app.processEvents()
        window.grab().save(str(ROOT/'artifacts/oracle-pearl-debug.png'))
        window.close()
    else:
        # 只运行这部分时避免与耗时回归测试同时进行，数值不包含资源提取。
        result['runtime'] = {}
        original_paint = OracleCanvas.paintEvent
        paints = []
        def measured(canvas, event):
            start = perf_counter()
            original_paint(canvas, event)
            paints.append(perf_counter()-start)
        # Qt 创建 QWidget 时会绑定虚函数；所有窗口创建前只安装一次计时。
        OracleCanvas.paintEvent = measured
        for label in ('recall', 'pearl_only', 'idle'):
            window = OracleDebugWindow(config, load_atlas=False)
            window.renderer = window.canvas.renderer = renderer
            window.timer.stop()
            for _ in range(700):
                window.scene.step()
            assert window.scene.appearance.sleeping
            if label == 'recall':
                window.scene.observe_pearl('recall')
            elif label == 'pearl_only':
                window.scene.set_pearl_home(Vec2(480, 535))
            window.show()
            window.refresh()
            app.processEvents()
            paints.clear()
            tick_start = window.scene.ticks
            window.last_time = perf_counter()
            window.timer.start(16)
            start, cpu = perf_counter(), process_time()
            QTimer.singleShot(6000 if label != 'idle' else 4000, app.quit)
            app.exec()
            duration, used = perf_counter()-start, process_time()-cpu
            if label != 'idle':
                assert paints, '移动期间必须实际测得画布重绘'
            result['runtime'][label] = dict(elapsed_seconds=duration, cpu_seconds=used,
                one_core_percent=used/duration*100, ticks=window.scene.ticks-tick_start,
                paint=summary(paints), paints_per_second=len(paints)/duration,
                dropped_seconds=window.clock.dropped_seconds)
            window.close()
            app.processEvents()
            print(label, result['runtime'][label], flush=True)
        OracleCanvas.paintEvent = original_paint
    result['config_unchanged'] = result['config_sha256'] == hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main('--timing' in sys.argv)
