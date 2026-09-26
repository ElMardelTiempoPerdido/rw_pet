"""环绕珠真实图集近景、数量对照、四角迁移及静止身体缓存检查。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from review_oracle_autonomy import check_pixels
from review_oracle_pearl_matrix import snapshot


def main():
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    output = ROOT/'artifacts'
    output.mkdir(exist_ok=True)
    digest = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    config = AppConfig.load(ROOT/'config.toml')
    settings = replace(config.oracle, pearl_matrix_enabled=True, pearl_orbits_enabled=True)
    atlas = Atlas(extract_atlas(config.game_dir))
    renderer = OracleRenderer(atlas, settings.colors, glyphs=load_pearl_glyphs(config.game_dir, atlas.root))
    poses, frames, results = [], [], []
    for counts in ((4, 3, 1), (8, 4, 2), (14, 6, 2), (28, 12, 6)):
        scene = OracleScene(replace(settings, pearl_matrix_count=counts[0], pearl_inner_count=counts[1],
                                   pearl_outer_count=counts[2], world_width=960, world_height=600))
        for _ in range(800):
            scene.step()
        for _ in range(10):
            for _ in range(12):
                scene.step()
            check_pixels(renderer, scene)
        poses.append(snapshot(renderer, scene, closeup=True, label=f'矩阵 / 内圈 / 外圈：{counts} · 2x'))
        if counts == (8, 4, 2):
            revision = scene.appearance.revision
            for tick in range(480):
                scene.step()
                if tick % 4 == 0:
                    frames.append(snapshot(renderer, scene, closeup=True, label='内外圈反向环绕 · 身体休眠 · 2x'))
            assert scene.appearance.revision == revision
            group = scene.pearl_orbits
            center = scene.body.chunks[0].position
            with_center = scene.orbit_center
            start = perf_counter()
            for _ in range(2000):
                group.step(center, with_center)
            results.append(dict(kind='stationary_body', orbit_tick_microseconds=(perf_counter()-start)*500,
                                body_revision_changes=0, orbiting_ticks=480))
    sheet = Image.new('RGB', (960, 1040), '#17232e')
    for i, pose in enumerate(poses):
        sheet.paste(pose, ((i % 2)*480, (i//2)*520))
    sheet.save(output/'oracle-pearl-quantity-poses.png')
    frames[0].save(output/'oracle-pearl-orbits.gif', save_all=True, append_images=frames[1:], duration=100, loop=0)
    for clockwise in (True, False):
        scene = OracleScene(replace(settings, world_width=640, world_height=480,
                                   pearl_matrix_count=8, pearl_inner_count=4, pearl_outer_count=2, float_speed=2.))
        scene.start_lap(clockwise)
        checks = 0
        for tick in range(6000):
            scene.step()
            if tick % 50 == 0:
                check_pixels(renderer, scene)
                checks += 3
            if scene.arrived and scene.appearance.sleeping and scene.observation_pearls_settled and scene.pearl_orbits.anchor.settled:
                break
        assert tick < 5999
        results.append(dict(kind='four_corners', clockwise=clockwise, ticks=tick+1, pixel_checks=checks))
    window = OracleDebugWindow(replace(config, oracle=settings), load_atlas=False)
    window.timer.stop()
    window.renderer = window.canvas.renderer = renderer
    window.assets.setText('本机原版图集与字形缓存 · 数量与环绕预览')
    window.set_paused(True)
    for _ in range(700):
        window.scene.step()
    window.show()
    app.processEvents()
    window.grab().save(str(output/'oracle-pearl-orbits-debug.png'))
    window.close()
    assert hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest() == digest
    report = dict(config_sha256=digest, quantity_pixel_checks=120, results=results)
    (output/'oracle-pearl-orbits-metrics.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
