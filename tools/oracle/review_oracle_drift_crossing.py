"""四角双向失重跨边：真实图集外形、机械臂、珍珠跟随与恢复休眠。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from review_oracle_autonomy import check_pixels, closeup


def overview(renderer, scene, label):
    image = QImage(680, 540, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#17232e'))
    painter = QPainter(image)
    try:
        painter.setFont(QFont('Microsoft YaHei UI', 11))
        painter.setPen(QColor('#e0e5e9'))
        painter.drawText(20, 25, label)
        painter.translate(20, 40)
        inner = scene.world.inner
        painter.fillRect(int(inner.left), int(inner.top), int(inner.right-inner.left),
                         int(inner.bottom-inner.top), QColor('#0b131c'))
        renderer.draw(painter, scene)
    finally:
        painter.end()
    return Image.frombytes('RGBA', (680, 540), bytes(image.constBits())).convert('RGB')


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    config = AppConfig.load(ROOT/'config.toml')
    fingerprint = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    atlas = Atlas(extract_atlas(config.game_dir))
    glyphs = load_pearl_glyphs(config.game_dir, atlas.root)
    poses, frames, metrics = [], [], []
    for source, side in enumerate(('top', 'right', 'bottom', 'left')):
        for sign in (-1, 1):
            settings = replace(config.oracle, world_width=640, world_height=480, arm_scale=.75,
                               base_side=side, base_fraction=.5)
            scene = OracleScene(settings)
            renderer = OracleRenderer(atlas, settings.colors, glyphs=glyphs)
            scene.drift()
            scene.behavior.drift_next_observation = 100000
            for _ in range(380):
                scene.step()
            destination = (source+sign) % 4
            scene.behavior.start_drift_crossing(scene, destination)
            deadline = scene.behavior.drift_duration
            result = dict(source=side, destination=destination, pixel_checks=0, max_arm_error=0.)
            captured = False
            for tick in range(3200):
                scene.step()
                result['max_arm_error'] = max(result['max_arm_error'], scene.arm.constraint_error)
                assert scene.arm.constraint_error < .025
                assert scene.pose.weightlessness == 1.
                assert scene.behavior.drift_duration == deadline
                if tick % 24 == 0:
                    check_pixels(renderer, scene)
                    result['pixel_checks'] += 3
                if not captured and not scene.navigator.region.boxes[source].contains(scene.body.chunks[0].position):
                    poses.append(closeup(renderer, scene, f'{side} → {destination} / 失重过角'))
                    captured = True
                if source == 0 and sign == 1 and tick % 4 == 0:
                    frames.append(overview(renderer, scene, f'失重跨边 1× / {tick/40:.1f}s'))
                if scene.behavior.state != Activity.DRIFT_CROSS_EDGE:
                    break
            assert tick < 3199 and captured
            assert scene.behavior.drift_edge == destination
            assert scene.navigator.region.boxes[destination].contains(scene.pearl.home)
            result['cross_ticks'] = tick+1
            # 到期平滑回正，真正停稳后仍能进入原来的低开销休眠。
            scene.behavior.drift_duration = scene.behavior.drift_ticks
            for tick in range(2000):
                scene.step()
                if scene.appearance.sleeping and scene.arrived and scene.pose.settled and scene.pearl.settled:
                    break
            assert tick < 1999 and not scene.behavior.drift_active
            assert scene.body.direction.y < -.9999
            result['sleep_ticks'] = tick+1
            revisions = (scene.appearance.revision, scene.pearl.revision, scene.eyes.revision)
            for _ in range(200):
                scene.step()
            assert revisions == (scene.appearance.revision, scene.pearl.revision, scene.eyes.revision)
            result['idle_rebuilds'] = 0
            metrics.append(result)
            print(result, flush=True)
    output = ROOT/'artifacts'
    output.mkdir(exist_ok=True)
    montage = Image.new('RGB', (760, 1360))
    for i, pose in enumerate(poses):
        montage.paste(pose, ((i % 2)*380, (i//2)*340))
    montage.save(output/'oracle-drift-crossing-poses.png')
    frames[0].save(output/'oracle-drift-crossing-preview.gif', save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    assert fingerprint == hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    (output/'oracle-drift-crossing-metrics.json').write_text(
        json.dumps(dict(cases=metrics, config_sha256=fingerprint), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
