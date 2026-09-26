"""当前配色的固定珠/卫星真实图集回放，覆盖观察、四角和二级卫星。"""
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
    config = AppConfig.load(ROOT/'config.toml')
    digest = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    output = ROOT/'artifacts'
    output.mkdir(exist_ok=True)
    atlas = Atlas(extract_atlas(config.game_dir))
    renderer = OracleRenderer(atlas, config.oracle.colors, glyphs=load_pearl_glyphs(config.game_dir, atlas.root))
    results, frames, poses = [], [], []
    for side in ('top', 'right', 'bottom', 'left'):
        scene = OracleScene(replace(config.oracle, base_side=side, world_width=960, world_height=600))
        for _ in range(800):
            scene.step()
        check_pixels(renderer, scene)
        poses.append(snapshot(renderer, scene, label=f'{side} / matrix 7 + orbits 6 + fixed 2 + satellite 1'))
        if side == 'top':
            scene.observe_pearl('recall')
            for tick in range(1000):
                scene.step()
                if tick % 25 == 0:
                    check_pixels(renderer, scene)
                if tick % 4 == 0:
                    frames.append(snapshot(renderer, scene, label=f'固定珠观察与卫星跟随 / {scene.behavior.state.value}'))
                if scene.behavior.completed_cycles and scene.appearance.sleeping:
                    break
            assert tick < 999
            results.append(dict(kind='parent_observation', ticks=tick+1, pixel_checks=(tick//25+1)*3))
    sheet = Image.new('RGB', (1920, 1200))
    for i, pose in enumerate(poses):
        sheet.paste(pose, ((i % 2)*960, (i//2)*600))
    sheet.save(output/'oracle-fixed-satellites-edges.png')
    frames[0].save(output/'oracle-fixed-satellites.gif', save_all=True, append_images=frames[1:], duration=100, loop=0)
    for clockwise in (True, False):
        scene = OracleScene(replace(config.oracle, world_width=640, world_height=480, float_speed=2.,
                                   pearl_fixed_count=3, pearl_satellite_count=5))
        scene.start_lap(clockwise)
        for tick in range(6500):
            scene.step()
            if tick % 40 == 0:
                check_pixels(renderer, scene)
            if scene.arrived and scene.appearance.sleeping and scene.observation_pearls_settled:
                break
        assert tick < 6499
        before = scene.appearance.revision
        for _ in range(200):
            scene.step()
        assert scene.appearance.revision == before
        results.append(dict(kind='all_satellite_types_four_corners', clockwise=clockwise, ticks=tick+1,
                            pixel_checks=(tick//40+1)*3, sleeping_body_revision_changes=0))
    window = OracleDebugWindow(config, load_atlas=False)
    window.timer.stop()
    window.renderer = window.canvas.renderer = renderer
    window.assets.setText('本机原版图集 · 正式固定珠与卫星珠；调试单珠已移除')
    window.set_paused(True)
    for _ in range(800):
        window.scene.step()
    window.show()
    app.processEvents()
    window.grab().save(str(output/'oracle-fixed-satellites-debug.png'))
    window.close()
    assert hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest() == digest
    report = dict(config_sha256=digest, static_edge_checks=12, results=results)
    (output/'oracle-fixed-satellites-metrics.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
