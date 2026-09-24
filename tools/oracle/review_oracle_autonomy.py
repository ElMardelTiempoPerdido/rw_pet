"""邻边绕角和自主侧倾的真实图集回放、像素边界检查及停稳检查。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import hashlib
import json
from math import atan2, degrees
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.scene import OracleScene, dot
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.render import OracleRenderer


def check_pixels(renderer, scene):
    w, h = int(scene.world.width), int(scene.world.height)
    for alpha in (0., .5, 1.):
        image = QImage(w+40, h+40, QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image)
        p.translate(20, 20)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.draw(p, scene, alpha, cords=False)
        p.end()
        mask = Image.frombytes('RGBA', (w+40, h+40), bytes(image.constBits())).getchannel('A')
        inner = scene.world.inner
        assert mask.crop((int(inner.left)+20, int(inner.top)+20,
                          int(inner.right)+20, int(inner.bottom)+20)).getbbox() is None
        for rect in ((0, 0, w+40, 20), (0, h+20, w+40, h+40), (0, 20, 20, h+20), (w+20, 20, w+40, h+20)):
            assert mask.crop(rect).getbbox() is None


def closeup(renderer, scene, label):
    image = QImage(380, 340, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#17232e'))
    p = QPainter(image)
    try:
        p.setPen(QColor('#e0e5e9'))
        p.setFont(QFont('Microsoft YaHei UI', 10))
        p.drawText(12, 25, label)
        p.drawText(12, 48, f'{scene.behavior.state.value} / 自主侧倾 {scene.pose.angle:+.1f}° / 4×')
        p.setClipRect(0, 55, 380, 285)
        p.translate(175, 160)
        p.scale(4, 4)
        upper = scene.body.chunks[0].position
        p.translate(-upper.x, -upper.y)
        renderer.draw(p, scene)
    finally:
        p.end()
    return Image.frombytes('RGBA', (380, 340), bytes(image.constBits())).convert('RGB')


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    config = AppConfig.load(ROOT/'config.toml')
    fingerprint = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    atlas = Atlas(extract_atlas(config.game_dir))
    glyphs = load_pearl_glyphs(config.game_dir, atlas.root)
    metrics, poses, frames = [], [], []
    sides = ('top', 'right', 'bottom', 'left')
    for i in range(4):
        settings = replace(config.oracle, base_side=sides[i], base_fraction=.5,
                           world_width=640, world_height=480, arm_scale=.75)
        scene = OracleScene(settings)
        renderer = OracleRenderer(atlas, settings.colors, glyphs=glyphs)
        destination = (i+1) % 4
        scene.behavior.start_roam(scene, adjacent=True, target_edge=destination)
        route = scene.navigator.route
        result = dict(source=sides[i], destination=sides[destination], path_length=route.length,
                      max_lean=0., max_angular_step=0., max_acceleration=0., pixel_checks=0)
        captured = False
        for tick in range(2200):
            old_dir, old_v = scene.body.direction, scene.body.chunks[0].velocity
            scene.step()
            axis = scene.body.direction
            angle = abs(degrees(atan2(old_dir.x*axis.y-old_dir.y*axis.x, dot(old_dir, axis))))
            result['max_angular_step'] = max(result['max_angular_step'], angle)
            result['max_lean'] = max(result['max_lean'], abs(scene.pose.angle))
            result['max_acceleration'] = max(result['max_acceleration'], (scene.body.chunks[0].velocity-old_v).length())
            if tick % 80 == 0:
                check_pixels(renderer, scene)
                result['pixel_checks'] += 3
            if not captured and scene.navigator.distance > route.length*.5:
                poses.append(closeup(renderer, scene, f'{sides[i]} → {sides[destination]}'))
                captured = True
            if i == 0 and tick % 6 == 0:
                frames.append(closeup(renderer, scene, f'上边 → 右边 / {tick/40:.1f}s'))
            if scene.behavior.state == Activity.IDLE and 'arrived_tick' not in result:
                result['arrived_tick'] = tick+1
            if 'arrived_tick' in result and scene.appearance.sleeping and scene.pose.settled:
                break
        assert scene.arrived and scene.appearance.sleeping and scene.pose.angle == 0., (i, result)
        result['sleep_tick'] = tick+1
        positions = [p.position for p in scene.appearance.points]
        revision = scene.appearance.revision
        for _ in range(200):
            scene.step()
        result['idle_rebuilds'] = scene.appearance.revision-revision
        result['idle_drift'] = max((p.position-q).length() for p, q in zip(scene.appearance.points, positions))
        assert result['idle_rebuilds'] == 0 and result['idle_drift'] == 0.
        metrics.append(result)
        print('Edge complete:', result, flush=True)
    # 珍珠旁转身观察与最终回正。
    scene = OracleScene(config.oracle)
    renderer = OracleRenderer(atlas, config.oracle.colors, glyphs=glyphs)
    scene.observe_pearl('recall')
    for _ in range(150):
        scene.step()
    poses.append(closeup(renderer, scene, '独立头部注视珍珠，躯干侧倾'))
    scene.stop()
    for _ in range(700):
        scene.step()
    assert scene.appearance.sleeping
    poses.append(closeup(renderer, scene, '结束行动，身体平滑回正'))
    sheet = Image.new('RGB', (1140, 680))
    for i, pose in enumerate(poses):
        sheet.paste(pose, ((i % 3)*380, (i//3)*340))
    sheet.save(ROOT/'artifacts/oracle-autonomy-poses.png')
    frames[0].save(ROOT/'artifacts/oracle-autonomy-preview.gif', save_all=True,
                   append_images=frames[1:], duration=150, loop=0)
    window = OracleDebugWindow(config)
    window.timer.stop()
    window.cross_edge_button.click()
    for _ in range(130):
        window.scene.step()
    window.set_paused(True)
    window.show()
    window.refresh()
    app.processEvents()
    window.grab().save(str(ROOT/'artifacts/oracle-autonomy-debug.png'))
    window.close()
    result = dict(edges=metrics, config_unchanged=fingerprint == hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest())
    (ROOT/'artifacts/oracle-autonomy-metrics.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
