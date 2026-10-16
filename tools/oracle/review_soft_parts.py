"""柔性带指定姿态与翻转预览；身体按给定角度旋转，带状部件独立模拟"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import replace
from math import cos, pi, sin
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.graphics.appearance import rotate
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.graphics.soft_mesh import rasterize_strip
from rw_creature_pet.oracle.motion.soft_parts import SoftStrip
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.soft_part_config import SoftPart, SOFT_SHAPES
from rw_creature_pet.oracle.ui.soft_parts_debug import demo_shape
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.geometry import Vec2


def review_scales(scene, renderer, output, font):
    """使用正式渲染入口比较实际显示倍率与附件柔光，不改变用户配置"""
    original = scene.config
    sheet = QImage(960, 640, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#182630'))
    painter = QPainter(sheet)
    painter.setFont(font)
    painter.setPen(QColor('#dce3e9'))
    try:
        for index, (scale, coarse) in enumerate(((1., False), (1.5, False), (2., False),
                                                (3., False), (4., False), (4., True))):
            x, y = index % 3*320, index // 3*320
            painter.save()
            try:
                painter.setClipRect(QRectF(x, y, 320, 320))
                title = f'{scale:g}x' + (' / coarse' if coarse else '')
                painter.drawText(x+16, y+24, title)
                scene.config = replace(original, glow_enabled=True, glow_color='#ddeeff',
                                       glow_radius=4., glow_opacity=.4, coarse_pixels_4x=coarse)
                painter.translate(x+160, y+110)
                painter.scale(scale, scale)
                painter.translate(-scene.appearance.upper.x, -scene.appearance.upper.y)
                renderer.draw(painter, scene, 1., raster_scale=scale)
            finally:
                painter.restore()
    finally:
        scene.config = original
        painter.end()
    sheet.save(str(output/'pixel-glow-scales.png'))


def main():
    app = QApplication.instance() or QApplication([])
    app.setFont(settings_font())
    cfg = AppConfig.load(ROOT/'config.toml')
    output = ROOT/'artifacts/soft-parts'
    output.mkdir(parents=True, exist_ok=True)
    # 仅用于观察纹理方向和连续性的示例 PNG，不写入用户贴图目录
    texture = QImage(12, 64, QImage.Format.Format_ARGB32_Premultiplied)
    texture.fill(QColor('#e4cda9'))
    p = QPainter(texture)
    for row in range(8, 64, 12):
        p.fillRect(0, row, 12, 3, QColor('#b45c6e'))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    p.fillRect(4, 56, 4, 8, QColor(0, 0, 0, 0))
    p.end()
    source = output/'sample-scarf.png'
    texture.save(str(source))
    shape = demo_shape(cfg.oracle.custom_appearance)
    shape = replace(shape, soft_part_1=replace(shape.soft_part_1, kind='png', width=6.,
        image_path=str(source), image_name=source.name),
        soft_part_2=replace(shape.soft_part_2, kind='trapezoid', layer='back'))
    config = replace(cfg.oracle, body_appearance='custom', outfit='normal', hide_cords=True,
        halo_enabled=False, pearl_matrix_count=0, pearl_inner_count=0, pearl_outer_count=0,
        pearl_fixed_count=0, pearl_satellite_count=0, custom_appearance=shape)
    scene = OracleScene(config)
    for _ in range(400):
        scene.step()
    renderer = OracleRenderer(Atlas(extract_atlas(cfg.game_dir)), config.active_colors)
    review_scales(scene, renderer, output, app.font())
    appearance = scene.appearance
    origin = appearance.upper
    nodes = [*scene.body.chunks, *appearance.body_points]
    positions = [p.position for p in nodes]
    lower, direction = appearance.lower, appearance.direction
    gallery = QImage(864, 220, QImage.Format.Format_ARGB32_Premultiplied)
    gallery.fill(QColor('#182630'))
    p = QPainter(gallery)
    p.setFont(app.font())
    p.setPen(QColor('#dce3e9'))
    for index, kind in enumerate(SOFT_SHAPES):
        part = SoftStrip(SoftPart(enabled=True, kind=kind, width=12., length=56.,
                                  image_path=str(source) if kind == 'png' else ''), Vec2(), Vec2(0, 1), 1.)
        for tick in range(55):
            part.step(Vec2(10*sin(tick*.1), 0), Vec2(0, 1), 1.)
        image, rect = rasterize_strip(part, 1., 2., texture if kind == 'png' else None)
        p.drawText(index*144+10, 20, kind)
        p.save()
        p.translate(index*144+65, 50)
        p.scale(2., 2.)
        p.drawImage(rect, image)
        p.restore()
    p.end()
    gallery.save(str(output/'shapes.png'))

    def pose(angle):
        for node, position in zip(nodes, positions):
            node.position = origin+rotate(position-origin, angle)
            node.previous_position = node.position
        appearance.lower = origin+rotate(lower-origin, angle)
        appearance.direction = rotate(direction, angle)
        scene.soft_parts.step(scene)

    def render():
        image = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('#182630'))
        painter = QPainter(image)
        painter.scale(2., 2.)
        painter.translate(64-origin.x, 54-origin.y)
        renderer._soft_parts_renderer.draw(painter, scene.soft_parts, 1., 2., layer='back')
        renderer.draw_geometry(painter, scene, cache_body=True, arm=False, cords=False,
                               pearl=False, halo=False, raster_scale=2.)
        renderer._soft_parts_renderer.draw(painter, scene.soft_parts, 1., 2.)
        painter.end()
        return image

    sheet = QImage(768, 280, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#182630'))
    painter = QPainter(sheet)
    painter.setFont(app.font())
    painter.setPen(QColor('#dce3e9'))
    for index, (label, angle) in enumerate((('Upright / settled', 0.), ('Side / settled', pi/2),
                                          ('Inverted / settled', pi))):
        for _ in range(700):
            pose(angle)
        painter.drawText(index*256+12, 20, label)
        painter.drawImage(QRectF(index*256, 24, 256, 256), render())
    painter.end()
    sheet.save(str(output/'textured-poses.png'))

    for _ in range(700):
        pose(0.)
    frames = []
    for tick in range(480):
        # 先翻至倒立并停留，再转回正立；并非修改原有漫游朝向逻辑
        if tick < 120:
            angle = pi*(1-cos(pi*tick/120))/2
        elif tick < 240:
            angle = pi
        elif tick < 360:
            angle = pi*(1+cos(pi*(tick-240)/120))/2
        else:
            angle = 0.
        pose(angle)
        if tick % 2 == 0:
            image = render().convertToFormat(QImage.Format.Format_RGBA8888)
            frames.append(Image.frombytes('RGBA', (256, 256), bytes(image.constBits())).convert('RGB'))
    frames[0].save(output/'textured-turning.gif', save_all=True, append_images=frames[1:], duration=50,
                   loop=0, disposal=2)
    print(output/'pixel-glow-scales.png')
    print(output/'shapes.png')
    print(output/'textured-poses.png')
    print(output/'textured-turning.gif')


if __name__ == '__main__':
    main()
