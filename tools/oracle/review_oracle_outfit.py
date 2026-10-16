"""按 1/1.5/2 倍真实精度绘制头饰，再以整数倍放大检查。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import cos, radians, sin
from dataclasses import replace
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.graphics.appearance import OracleAppearance, perpendicular, rotate
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    config = AppConfig.load(ROOT/'config.toml')
    renderer = OracleRenderer(colors=config.oracle.colors)
    sheet = QImage(960, 960, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#17232e'))
    painter = QPainter(sheet)
    try:
        painter.setFont(settings_font())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        cases = (('Normal', 'normal', 0, Vec2()), ('Maid - front', 'maid', 0, Vec2()),
                 ('Maid - turn', 'maid', 30, Vec2(.7, -.4)), ('Maid - upside down', 'maid', 180, Vec2()))
        for row, (label, outfit, angle, look) in enumerate(cases):
            for col, density in enumerate((1., 1.5, 2.)):
                painter.setPen(QColor('#dce3e9'))
                painter.drawText(col*320+16, row*240+24, f'{label} / {density:g}x (4x inspection)')
                image = QImage(round(40*density), round(40*density), QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                local = QPainter(image)
                direction = Vec2(sin(radians(angle)), -cos(radians(angle)))
                try:
                    local.scale(density, density)
                    renderer.draw_head(local, Vec2(20, 20), Vec2(20, 20)-direction*14, direction, look,
                                       raster_scale=density, pixelated=True, outfit=outfit)
                finally:
                    local.end()
                w, h = image.width()*4, image.height()*4
                painter.drawImage(QRectF(col*320+160-w/2, row*240+140-h/2, w, h), image)
    finally:
        painter.end()
    out = ROOT/'artifacts'
    out.mkdir(exist_ok=True)
    assert sheet.save(str(out/'oracle-maid-head.png'))
    # 使用完整人偶绘制入口检查 V 领、花边、念珠的真实遮挡；先按原倍率
    # 光栅化，再整数放大，避免检查图的放大倍率被误用为贴图选择倍率。
    sheet = QImage(960, 1700, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#17232e'))
    painter = QPainter(sheet)
    try:
        painter.setFont(settings_font())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        for row, (label, outfit, angle, swing) in enumerate((('Normal', 'normal', 0, 0), ('Maid', 'maid', 0, 0),
                ('Maid - tilt', 'maid', 30, 0), ('Maid - inverted', 'maid', 180, 0),
                ('Maid - swung gown', 'maid', 0, 12))):
            scene = OracleScene(replace(config.oracle, outfit=outfit, hide_cords=True))
            origin = Vec2(400, 300)
            direction = rotate(Vec2(0, -1), radians(angle))
            for part, position in zip((*scene.body.chunks, scene.head),
                                      (origin, origin-direction*9, origin+direction*14)):
                part.position = part.previous_position = position
                part.velocity = Vec2()
            scene.look_direction = scene.previous_look_direction = Vec2()
            scene.appearance = OracleAppearance(scene)
            n = scene.appearance.CLOTH_DIVS
            for i, part in enumerate(scene.appearance.cloth):
                part.position += perpendicular(direction)*(swing*(i//n)/(n-1))
                part.previous_position = part.position
            for col, density in enumerate((1., 1.5, 2.)):
                painter.setPen(QColor('#dce3e9'))
                painter.drawText(col*320+16, row*340+24, f'{label} / {density:g}x (2x inspection)')
                size = round(72*density)
                image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                local = QPainter(image)
                try:
                    local.scale(density, density)
                    local.translate(36-origin.x, 36-origin.y)
                    renderer.draw_geometry(local, scene, arm=False, cords=False, pearl=False, halo=False,
                                           cache_body=True, include_head=False, raster_scale=density,
                                           include_front_outfit=False)
                    renderer.draw_scene_head(local, scene, 1., pixelated=True, raster_scale=density)
                    renderer.draw_front_outfit(local, scene, 1., raster_scale=density)
                finally:
                    local.end()
                w = size*2
                painter.drawImage(QRectF(col*320+160-w/2, row*340+180-w/2, w, w), image)
    finally:
        painter.end()
    assert sheet.save(str(out/'oracle-maid-ribbons.png'))
    with tempfile.TemporaryDirectory() as temp:
        dialog = OracleSettingsDialog(config, SettingsStore(Path(temp)/'settings.json'), first_run=True)
        dialog.tabs.setCurrentWidget(dialog.pages['appearance'])
        dialog.show()
        app.processEvents()
        assert dialog.grab().save(str(out/'oracle-outfit-settings.png'))
        dialog.close()
    print('Saved artifacts/oracle-maid-head.png, oracle-maid-ribbons.png and oracle-outfit-settings.png')


if __name__ == '__main__':
    main()
