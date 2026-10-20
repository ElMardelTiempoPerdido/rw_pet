"""输出短/长斗篷的六种静态姿态，不读取或修改用户的角色配置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import radians
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.oracle.cape_config import Cape
from rw_creature_pet.oracle.config import CustomAppearance, OracleColors, OracleConfig
from rw_creature_pet.oracle.graphics.appearance import OracleAppearance, rotate
from rw_creature_pet.oracle.graphics.cape import cape_geometry
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.shared.geometry import Vec2


def pose_scene(length=18., pose='rest', angle=0., **cape_values):
    shape = CustomAppearance(cape=Cape(enabled=True, length=length, **cape_values),
                             sleeve_root_width=8., sleeve_cuff_width=8.,
                             inner_collar_top_width=12., inner_collar_bottom_width=12.,
                             inner_collar_height=5., neckline_depth=4., neckline_width=8.)
    colors = replace(OracleColors(), skin='#88a9a2', eyes='#171c25', inner_robe='#ac9bd1',
                     robe_top='#494958', robe_bottom='#292a35', collar_trim='#494958')
    scene = OracleScene(OracleConfig(body_appearance='custom', custom_appearance=shape,
                                    custom_colors=colors, hide_cords=True, halo_enabled=False,
                                    pearl_matrix_enabled=False, pearl_orbits_enabled=False,
                                    pearl_fixed_count=0, physics_backend='python'))
    direction = rotate(Vec2(0, -1), radians(angle))
    upper = Vec2(400, 300)
    for p, v in zip((*scene.body.chunks, scene.head), (upper, upper-direction*9, upper+direction*14)):
        p.position = p.previous_position = v
        p.velocity = Vec2()
    scene.look_direction = scene.previous_look_direction = Vec2()
    scene.appearance = OracleAppearance(scene)
    for i, hand in enumerate(scene.appearance.hands):
        if pose == 'both' or (pose == 'single' and i == 1):
            hand.position = hand.previous_position = upper+rotate(Vec2((-1 if i == 0 else 1)*18, 0), radians(angle))
        elif angle:
            # 固定姿态围绕身体旋转，不采用世界重力重新生成的垂手方向
            hand.position = hand.previous_position = upper+rotate(Vec2((-1 if i == 0 else 1)*5.267, 14.045), radians(angle))
    return scene, upper, direction


def main():
    app = QApplication.instance() or QApplication([])
    directory = ROOT/'artifacts/cape'
    directory.mkdir(parents=True, exist_ok=True)
    sheet = QImage(560, 900, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#dde1e1'))
    canvas = QPainter(sheet)
    canvas.setFont(settings_font())
    try:
        for row, pose in enumerate(('rest', 'both', 'single')):
            for col, length in enumerate((18., 34.)):
                scene, upper, direction = pose_scene(length, pose)
                renderer = OracleRenderer()
                renderer.colors = scene.config.active_colors
                tile = QImage(140, 140, QImage.Format.Format_ARGB32_Premultiplied)
                tile.fill(0)
                painter = QPainter(tile)
                try:
                    painter.scale(2., 2.)
                    painter.translate(35-upper.x, 25-upper.y)
                    renderer.draw_geometry(painter, scene, arm=False, cords=False, pearl=False,
                                           halo=False, cache_body=True, raster_scale=2.)
                finally:
                    painter.end()
                tile.save(str(directory/f'{pose}-{length:g}.png'))
                canvas.drawImage(QRectF(col*280, row*300+20, 280, 280), tile)
                canvas.setPen(QColor('#26373a'))
                label = {'rest': '双臂下垂', 'both': '双臂抬起', 'single': '单臂抬起'}[pose]
                canvas.drawText(col*280+12, row*300+22, f'{label} / {length:g} px')
                sleeves = tuple(renderer.body_sleeve_edges(scene, 1., upper, direction, i) for i in range(2))
                geometry = cape_geometry(upper, direction, tuple(h.position for h in scene.appearance.hands),
                                         sleeves, scene.config.custom_appearance)
                print(pose, length, 'bottom:', geometry.lowest-upper, 'lift:', geometry.lift)
    finally:
        canvas.end()
    path = directory/'static-poses.png'
    sheet.save(str(path))
    print(path)


if __name__ == '__main__':
    main()
