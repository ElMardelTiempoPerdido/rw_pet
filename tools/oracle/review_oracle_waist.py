"""固定身体朝向往返移动，对照腰腿跟随开关，并检查停稳后的休眠。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import cos, degrees, pi, radians
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.appearance import OracleAppearance, perpendicular, rotate
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene


def place(scene, origin, axis):
    for p, position in zip((*scene.body.chunks, scene.head),
                           (origin, origin-axis*9, origin+axis*14)):
        p.previous_position = p.position
        p.position = position
        p.velocity = p.position-p.previous_position


def make_scene(config, angle, follow):
    scene = OracleScene(config.oracle)
    axis = rotate(Vec2(0, -1), radians(angle))
    place(scene, Vec2(400, 300), axis)
    for p in (*scene.body.chunks, scene.head):
        p.previous_position = p.position
        p.velocity = Vec2()
    scene.pose.weightlessness = 1.
    scene.look_direction = scene.previous_look_direction = Vec2()
    scene.appearance = OracleAppearance(scene)
    if not follow:
        scene.appearance.WAIST_FOLLOW = 0.
    for _ in range(700):
        scene.appearance.step(scene)
    return scene


def paint(renderer, scene, bare):
    scale = 1.5
    image = QImage(96, 96, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#17232e'))
    painter = QPainter(image)
    a = scene.appearance
    painter.scale(scale, scale)
    painter.translate(32-a.upper.x, 32-a.upper.y)
    try:
        if bare:
            lower_direction = a.waist_direction(a.direction)
            renderer.draw_limbs(painter, scene, 1., a.upper, a.lower, lower_direction, False)
            renderer.draw_inner_robe(painter, a.upper, a.lower, a.direction, a.head.position,
                                     lower_direction=lower_direction)
            renderer.draw_head(painter, a.head.position, a.upper, a.direction, Vec2(),
                               0., raster_scale=scale)
        else:
            renderer.draw_geometry(painter, scene, 1., arm=False, cords=False,
                                   pearl=False, halo=False)
    finally:
        painter.end()
    return Image.frombytes('RGBA', (96, 96), bytes(image.constBits())).convert('RGB').resize(
        (288, 288), Image.Resampling.NEAREST)


def main():
    app = QApplication.instance() or QApplication([])
    config = AppConfig.load(ROOT/'config.toml')
    atlas = Atlas(extract_atlas(config.game_dir))
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 15)
    sheet = Image.new('RGB', (1152, 960), '#17232e')
    labels = ('Before / torso', 'Follow / torso', 'Before / full', 'Follow / full')
    frames, metrics = [], []
    for row, angle in enumerate((0, 90, 180)):
        scenes = [make_scene(config, angle, follow) for follow in (False, True)]
        renderers = [OracleRenderer(atlas, config.oracle.colors) for _ in scenes]
        axis = scenes[0].body.direction
        side = perpendicular(axis)
        best = -1.
        max_step = 0.
        for tick in range(1600):
            offset = 24*(1-cos(2*pi*min(tick, 160)/160))
            for scene in scenes:
                place(scene, Vec2(400, 300)+side*offset, axis)
                scene.appearance.step(scene)
            a = scenes[1].appearance
            max_step = max(max_step, abs(a.waist_velocity))
            current = abs(a.waist_angle)
            capture = tick < 240 and current > best
            animate = angle == 180 and tick < 320 and tick % 4 == 0
            if capture or animate:
                images = [paint(renderers[i], scenes[i], bare)
                          for bare in (True, False) for i in (0, 1)]
                strip = Image.new('RGB', (1152, 320), '#17232e')
                draw = ImageDraw.Draw(strip)
                for column, (image, label) in enumerate(zip(images, labels)):
                    draw.text((column*288+10, 8), f'{angle} deg | {label}', font=font, fill='#d7e5ed')
                    strip.paste(image, (column*288, 32))
                if capture:
                    best = current
                    sheet.paste(strip, (0, row*320))
                if animate:
                    frames.append(strip)
            if tick >= 320 and all(scene.appearance.sleeping for scene in scenes):
                break
        assert scenes[1].appearance.sleeping, angle
        metrics.append(dict(angle=angle, max_waist_degrees=degrees(best),
                            max_step_degrees=degrees(max_step), sleep_tick=tick, sleeping=True))
    out = ROOT/'artifacts'
    out.mkdir(exist_ok=True)
    sheet.save(out/'oracle-waist-follow-poses.png')
    frames[0].save(out/'oracle-waist-follow-preview.gif', save_all=True,
                   append_images=frames[1:], duration=100, loop=0, optimize=False)
    (out/'oracle-waist-follow-metrics.json').write_text(json.dumps(metrics, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(metrics), flush=True)


if __name__ == '__main__':
    main()
