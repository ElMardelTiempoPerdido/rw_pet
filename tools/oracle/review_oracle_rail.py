"""读取当前配置，输出一次完整四边绕行的真实图集预览和运动测量。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)

from PIL import Image
from PySide6.QtGui import QFont, QFontDatabase, QImage
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.debug_window import OracleDebugWindow


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    config_path = ROOT / 'config.toml'
    window = OracleDebugWindow(AppConfig.load(config_path), config_path)
    window.timer.stop()
    window.pause_button.setChecked(True)
    window.sliding_box.setChecked(True)
    window.resize(1220, 870)
    window.show()
    window.start_lap(True)
    window.refresh()
    app.processEvents()
    output = ROOT / 'artifacts'
    window.grab().save(str(output / 'oracle-rail-debug.png'))
    scene = window.scene
    frames, corners = [], []
    metrics = dict(max_arm_error=0., max_joint_displacement=0., max_body_acceleration=0.,
                   max_base_acceleration=0., max_support_distance=0., corner_frames=0,
                   path_length=scene.navigator.route.length,
                   config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest())
    old_body_velocity = scene.body.chunks[0].velocity
    old_base_velocity = 0.
    for tick in range(5000):
        scene.step()
        upper = scene.body.chunks[0]
        metrics['max_arm_error'] = max(metrics['max_arm_error'], scene.arm.constraint_error)
        metrics['max_joint_displacement'] = max(metrics['max_joint_displacement'], max(j.velocity.length() for j in scene.arm.joints))
        metrics['max_body_acceleration'] = max(metrics['max_body_acceleration'], (upper.velocity - old_body_velocity).length())
        metrics['max_base_acceleration'] = max(metrics['max_base_acceleration'], abs(scene.navigator.base.velocity - old_base_velocity))
        metrics['max_support_distance'] = max(metrics['max_support_distance'], (upper.position - scene.base).length())
        old_body_velocity, old_base_velocity = upper.velocity, scene.navigator.base.velocity
        normal = scene.base_normal()
        on_corner = abs(normal.x) > .55 and abs(normal.y) > .55
        if on_corner:
            metrics['corner_frames'] += 1
        if tick % 12 == 0:
            window.refresh()
            app.processEvents()
            qimage = window.canvas.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            frame = Image.frombytes('RGBA', (qimage.width(), qimage.height()), bytes(qimage.constBits())).convert('RGB')
            frames.append(frame)
            if on_corner and (not corners or tick - corners[-1][0] > 60):
                corners.append((tick, frame.copy()))
        if scene.arrived:
            metrics['arrived_tick'] = tick + 1
            break
    metrics['arrived'] = scene.arrived
    metrics['base_reversals'] = scene.navigator.base.reversals
    metrics['base_starts'] = scene.navigator.base.starts
    metrics['reachable_radius'] = scene.arm.maximum_reach
    frames[0].save(output / 'oracle-rail-preview.gif', save_all=True, append_images=frames[1:],
                   duration=300, loop=0, optimize=False)
    if corners:
        sheet = Image.new('RGB', (1000, 760), '#17232e')
        for i, (_, frame) in enumerate(corners[:4]):
            frame.thumbnail((500, 380))
            sheet.paste(frame, ((i % 2)*500, (i // 2)*380))
        sheet.save(output / 'oracle-rail-corners.png')
    (output / 'oracle-rail-metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    print(json.dumps(metrics, indent=2))
    window.close()


if __name__ == '__main__':
    main()
