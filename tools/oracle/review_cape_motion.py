"""定时姿态驱动的斗篷回摆预览，使用真实 CapeMotion，不读取或修改用户配置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import pi
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.graphics.appearance import rotate
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.motion.cape import smooth
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.shared.geometry import Vec2
from tools.oracle.review_cape import pose_scene


def pose(tick):
    x = .8*max(0, min(30, tick-20))
    angle = pi/3*smooth((tick-135)/22)*(1-smooth((tick-180)/22))
    lift = smooth((tick-245)/16)*(1-smooth((tick-290)/16))
    if tick < 20:
        label = '静止'
    elif tick < 50:
        label = '向右移动 - 下摆滞后'
    elif tick < 135:
        label = '停止 - 惯性回摆'
    elif tick < 230:
        label = '转身 - 下摆跟随与回摆'
    elif tick < 320:
        label = '单侧抬手与放下'
    else:
        label = '回摆收敛'
    return Vec2(x-12, 0), angle, lift, label


def main():
    app = QApplication.instance() or QApplication([])
    directory = ROOT/'artifacts/cape'
    directory.mkdir(parents=True, exist_ok=True)
    entries = []
    for length in (18., 34.):
        scene, upper, direction = pose_scene(length)
        renderer = OracleRenderer()
        renderer.colors = scene.config.active_colors
        points = (*scene.body.chunks, *scene.appearance.body_points)
        entries.append((scene, renderer, upper, points, tuple(p.position-upper for p in points)))
    frames, captures = [], []
    for tick in range(420):
        shift, angle, lift, label = pose(tick)
        sheet = QImage(560, 320, QImage.Format.Format_RGBA8888)
        sheet.fill(QColor('#dde1e1'))
        canvas = QPainter(sheet)
        canvas.setFont(settings_font())
        canvas.setPen(QColor('#26373a'))
        canvas.drawText(12, 20, label)
        for col, (scene, renderer, rest, points, local_points) in enumerate(entries):
            upper = rest+shift
            direction = rotate(Vec2(0, -1), angle)
            for p, local in zip(points, local_points):
                p.position = p.previous_position = upper+rotate(local, angle)
            scene.appearance.hands[1].position = scene.appearance.hands[1].previous_position = (
                upper+rotate(Vec2(5.267, 14.045).lerp(Vec2(18, 0), lift), angle))
            scene.appearance.upper, scene.appearance.direction = upper, direction
            if tick == 0:
                # 首帧从当前姿态初始化，避免预览摆放造成伪惯性
                motion = scene.appearance.cape_motion
                motion.targets = motion.reference_points(upper, direction, tuple(h.position for h in scene.appearance.hands))
            scene.appearance.cape_motion.step(upper, direction, tuple(h.position for h in scene.appearance.hands))
            scene.appearance.revision += 1
            tile = QImage(140, 140, QImage.Format.Format_ARGB32_Premultiplied)
            tile.fill(0)
            painter = QPainter(tile)
            painter.scale(2, 2)
            painter.translate(35-rest.x, 25-rest.y)
            renderer.draw_geometry(painter, scene, arm=False, cords=False, pearl=False,
                                   halo=False, cache_body=True, raster_scale=2.)
            painter.end()
            canvas.drawImage(QRectF(col*280, 30, 280, 280), tile)
            canvas.drawText(col*280+12, 42, f'{scene.config.custom_appearance.cape.length:g} px')
        canvas.end()
        if tick % 2 == 0:
            frames.append(Image.frombytes('RGBA', (sheet.width(), sheet.height()), bytes(sheet.bits())).convert('RGB'))
        if tick in (0, 26, 56, 66, 90, 156, 190, 268, 302, 419):
            captures.append(sheet.copy())
    frames[0].save(directory/'inertia.gif', save_all=True, append_images=frames[1:],
                   duration=50, loop=0, disposal=2, optimize=False)
    contact = QImage(560*2, 320*5, QImage.Format.Format_RGBA8888)
    contact.fill(QColor('#dde1e1'))
    painter = QPainter(contact)
    for i, capture in enumerate(captures):
        painter.drawImage((i%2)*560, (i//2)*320, capture)
    painter.end()
    contact.save(str(directory/'inertia-frames.png'))
    print(directory/'inertia.gif')
    print(directory/'inertia-frames.png')


if __name__ == '__main__':
    main()
