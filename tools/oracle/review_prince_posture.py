"""Prince 体态离屏预览，只写 artifacts，不读取本机设置或角色库"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import cos, sin
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.shared.geometry import Vec2


def make_scene():
    return OracleScene(replace(OracleConfig(), body_appearance='prince',
                              hide_cords=True, physics_backend='python', pearl_fixed_count=0,
                              pearl_matrix_enabled=False, pearl_orbits_enabled=False))


def advance(scene, origin, angle, look):
    direction = Vec2(sin(angle), -cos(angle))
    for p, target in zip(scene.body.chunks, (origin, origin-direction*9)):
        p.previous_position, p.velocity = p.position, target-p.position
        p.position = target
    scene.previous_look_direction, scene.look_direction = scene.look_direction, look
    scene.prince_posture.step(scene.head, origin, direction, look)
    scene.appearance.step(scene)


def draw(renderer, scene, scale=2.):
    image = QImage(320, 320, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('#b7b4b1'))
    painter = QPainter(image)
    try:
        painter.translate(160, 140)
        painter.scale(scale, scale)
        upper = scene.body.chunks[0].position
        painter.translate(-upper.x, -upper.y)
        renderer.draw_geometry(painter, scene, arm=False, cords=False, pearl=False, halo=False,
                               cache_body=True, raster_scale=scale)
    finally:
        painter.end()
    return image


def main():
    app = QApplication.instance() or QApplication([])
    directory = ROOT/'artifacts/prince'
    directory.mkdir(parents=True, exist_ok=True)
    sheet = QImage(960, 640, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#b7b4b1'))
    painter = QPainter(sheet)
    painter.setFont(settings_font())
    for i, (name, angle, gaze) in enumerate((('Front', 0., Vec2()), ('Left', 0., Vec2(-.75, 0.)),
            ('Right', 0., Vec2(.75, 0.)), ('Tilt', .6, Vec2(.8, 0.)),
            ('Horizontal', 1.57, Vec2(0., .8)), ('Inverted', 3.14, Vec2(-.8, 0.)))):
        scene = make_scene()
        origin = scene.body.chunks[0].position
        for _ in range(400):
            advance(scene, origin, angle, gaze)
        renderer = OracleRenderer(colors=scene.config.active_colors)
        x, y = (i%3)*320, (i//3)*320
        painter.drawImage(x, y, draw(renderer, scene))
        painter.setPen(QColor('#34313f'))
        painter.drawText(x+16, y+28, name+' / 2x')
    painter.end()
    sheet.save(str(directory/'prince-posture.png'))

    scene = make_scene()
    origin = scene.body.chunks[0].position
    renderer = OracleRenderer(colors=scene.config.active_colors)
    frames = []
    for tick in range(480):
        gaze = Vec2(0. if tick < 80 or tick >= 340 else (.75 if tick < 210 else -.75), 0.)
        shift = 0. if tick < 80 or tick >= 340 else 7*sin((tick-80)/260*6.283185)
        advance(scene, origin+Vec2(shift, 0.), shift*.035, gaze)
        if tick%2 == 0:
            image = draw(renderer, scene, 4.).convertToFormat(QImage.Format.Format_RGBA8888)
            frames.append(Image.frombytes('RGBA', (320, 320), bytes(image.constBits())).convert('RGB'))
    frames[0].save(directory/'prince-posture-motion.gif', save_all=True, append_images=frames[1:],
                   duration=50, loop=0, disposal=2)
    print(directory/'prince-posture.png')
    print(directory/'prince-posture-motion.gif')


if __name__ == '__main__':
    main()
