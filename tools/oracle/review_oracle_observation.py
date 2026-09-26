"""局部绕珠与冥想的真实图集回放、四边插值边界和休眠测量。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import hashlib
import json
from math import degrees
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from review_oracle_autonomy import check_pixels


def frame(renderer, scene, title):
    image = QImage(640, 420, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#17232e'))
    painter = QPainter(image)
    try:
        painter.setFont(QFont('Microsoft YaHei UI', 11))
        painter.setPen(QColor('#e0e5e9'))
        painter.drawText(14, 26, title)
        painter.drawText(14, 48, f'{scene.behavior.state.value} / 3× / 失重 {scene.pose.weightlessness:.0%}')
        painter.setClipRect(0, 60, 640, 360)
        painter.translate(320, 230)
        painter.scale(3, 3)
        center = scene.body.chunks[0].position.lerp(scene.pearl.position, .5)
        painter.translate(-center.x, -center.y)
        renderer.draw(painter, scene)
    finally:
        painter.end()
    return Image.frombytes('RGBA', (640, 420), bytes(image.constBits())).convert('RGB')


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    config = AppConfig.load(ROOT/'config.toml')
    fingerprint = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    atlas = Atlas(extract_atlas(config.game_dir))
    glyphs = load_pearl_glyphs(config.game_dir, atlas.root)
    frames, poses, metrics = [], [], []
    for index, side in enumerate(('top', 'right', 'bottom', 'left')):
        settings = replace(config.oracle, world_width=640, world_height=480, arm_scale=.75,
                           base_side=side, base_fraction=0.)
        scene = OracleScene(settings)
        renderer = OracleRenderer(atlas, settings.colors, glyphs=glyphs)
        if side == 'bottom':
            scene.drift()
            for _ in range(250):
                scene.step()
        scene.observe_pearl('orbit')
        result = dict(side=side, weightless=scene.behavior.drift_active,
                      pixel_checks=0, max_arm_error=0., arc_degrees=0.)
        captured = False
        for tick in range(2600):
            scene.step()
            result['max_arm_error'] = max(result['max_arm_error'], scene.arm.constraint_error)
            assert scene.arm.constraint_error < .025
            if tick % 30 == 0:
                check_pixels(renderer, scene)
                result['pixel_checks'] += 3
            if scene.behavior.state == Activity.ORBIT:
                route = scene.navigator.route
                radius = (route.start-scene.pearl.position).length()
                result['arc_degrees'] = degrees(route.length/radius)
                if not captured and scene.navigator.distance > route.length*.5:
                    poses.append(frame(renderer, scene, f'{side} / 绕珠观察'))
                    captured = True
            if index == 0 and tick % 4 == 0:
                frames.append(frame(renderer, scene, f'局部弧线观察 / {tick/40:.1f}s'))
            if scene.behavior.completed_cycles == 1:
                break
        assert tick < 2599 and captured
        result['observation_ticks'] = tick+1
        scene.meditate()
        scene.behavior.duration = 2400
        for tick in range(1400):
            scene.step()
            result['max_arm_error'] = max(result['max_arm_error'], scene.arm.constraint_error)
            assert scene.arm.constraint_error < .025
            if tick % 30 == 0:
                check_pixels(renderer, scene)
                result['pixel_checks'] += 3
            if index == 0 and tick % 4 == 0:
                frames.append(frame(renderer, scene, f'停稳与冥想 / {tick/40:.1f}s'))
            if scene.appearance.sleeping and scene.arrived and scene.pose.settled and not scene.eyes.moving:
                break
        assert tick < 1399
        result['meditation_sleep_tick'] = tick+1
        poses.append(frame(renderer, scene, f'{side} / 冥想中休眠'))
        revisions = (scene.appearance.revision, scene.pearl.revision, scene.eyes.revision)
        positions = [p.position for p in scene.appearance.points]
        started = perf_counter()
        for _ in range(200):
            scene.step()
        result['rest_step_ms'] = (perf_counter()-started)*1000/200
        assert revisions == (scene.appearance.revision, scene.pearl.revision, scene.eyes.revision)
        assert positions == [p.position for p in scene.appearance.points]
        result['idle_rebuilds'] = 0
        metrics.append(result)
        print(result, flush=True)
    output = ROOT/'artifacts'
    output.mkdir(exist_ok=True)
    montage = Image.new('RGB', (640*2, 420*4))
    for i, pose in enumerate(poses):
        montage.paste(pose, ((i % 2)*640, (i//2)*420))
    montage.save(output/'oracle-observation-poses.png')
    frames[0].save(output/'oracle-observation-preview.gif', save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    window = OracleDebugWindow(config, load_atlas=True)
    window.timer.stop()
    window.scene = scene
    window.canvas.scene = scene
    window.canvas.renderer = renderer
    window.refresh()
    window.show()
    app.processEvents()
    window.grab().save(str(output/'oracle-observation-debug.png'))
    window.close()
    assert fingerprint == hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    (output/'oracle-observation-metrics.json').write_text(
        json.dumps(dict(cases=metrics, config_sha256=fingerprint), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
