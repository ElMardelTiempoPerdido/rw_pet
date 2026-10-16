"""使用本机原版两帧素材检查指图动作、投影缩放及设置页；不改用户配置。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.config import DragReactionConfig
from rw_creature_pet.oracle.effects.projection_assets import prepare_projection
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.atlas import Atlas, extract_atlas


def paint(renderer, scene, scale):
    image = QImage(round(380*scale), round(250*scale), QImage.Format.Format_RGBA8888)
    image.fill(QColor('#19282d'))
    painter = QPainter(image)
    painter.scale(scale, scale)
    painter.translate(190-scene.world.width/2, 65)
    renderer.draw(painter, scene, cords=False)
    painter.end()
    return Image.frombytes('RGBA', (image.width(), image.height()), bytes(image.constBits())).convert('RGB')


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = AppConfig.load(ROOT/'config.toml')
    renderer = OracleRenderer(Atlas(extract_atlas(config.game_dir)), config.oracle.colors)
    error = prepare_projection(config.game_dir, renderer)
    if error:
        raise RuntimeError(error)
    settings = replace(config.oracle, base_side='top', base_fraction=.5, hide_cords=True,
                       halo_enabled=False, pearl_fixed_count=0, pearl_matrix_enabled=False, pearl_orbits_enabled=False,
                       drag_projection_probability=1., drag_projection_cooldown_seconds=45.,
                       drag_reactions=DragReactionConfig(gesture_probability=0., voice_probability=0.))
    scene = OracleScene(settings)
    for _ in range(100):
        scene.step()
    scene.projection.available = True
    scene.drag.set_enabled(True)
    scene.drag.press(scene.head.position, lambda _: True)
    scene.drag_reactions.start_gesture('alternating', scene)
    scene.drag_reactions.duration = .8
    scene.drag_reactions.gesture_wait = .3
    output = ROOT/'artifacts'
    output.mkdir(exist_ok=True)
    frames, samples = [], {}
    for tick in range(440):
        scene.step()
        if tick % 2 == 0:
            frame = paint(renderer, scene, 2.)
            label = ImageDraw.Draw(frame)
            p = scene.projection
            label.text((8, 8), f'{tick/40:.2f}s   {scene.drag_reactions.gesture or p.state}   hand={p.hand_index}', fill='white')
            frames.append(frame)
        if tick in (42, 100, 240, 435):
            samples[tick] = [paint(renderer, scene, scale) for scale in (1., 1.5, 2.)]
    frames[0].save(output/'oracle-projection.gif', save_all=True, append_images=frames[1:], duration=50, loop=0)
    sheet = Image.new('RGB', (1140, 1080), '#19282d')
    text = ImageDraw.Draw(sheet)
    for row, (tick, images) in enumerate(samples.items()):
        for col, (scale, image) in enumerate(zip((1., 1.5, 2.), images)):
            image.save(output/f'oracle-projection-{tick}-{scale:g}x.png')
            # 对照表只是缩略图，平均采样保留细线；实际倍率另存原尺寸 PNG 检查。
            sheet.paste(image.resize((380, 250), Image.Resampling.BOX), (col*380, row*270+20))
            text.text((col*380+8, row*270+4), f'{tick/40:.2f}s / {scale:g}x', fill='white')
    sheet.save(output/'oracle-projection-scales.png')
    with tempfile.TemporaryDirectory() as temp:
        dialog = OracleSettingsDialog(config, SettingsStore(Path(temp)/'settings.json'),
                                      assets=OracleAssets(renderer, '', {}, ''))
        dialog.tabs.setCurrentWidget(dialog.pages['projection'])
        dialog.show()
        for language in ('zh', 'en'):
            language_manager().set_language(language)
            app.processEvents()
            dialog.grab().save(str(output/f'oracle-projection-settings-{language}.png'))
        dialog.close()
    print('Saved projection GIF, scale comparison, and Chinese/English settings previews in artifacts/')


if __name__ == '__main__':
    main()
