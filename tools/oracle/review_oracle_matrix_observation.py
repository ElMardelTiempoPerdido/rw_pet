"""使用当前用户配色回放矩阵抽取，检查插值像素边界、完整归位及休眠。"""
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
from rw_creature_pet.oracle.behavior import Activity
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
    settings = replace(config.oracle, pearl_matrix_enabled=True)
    atlas = Atlas(extract_atlas(config.game_dir))
    renderer = OracleRenderer(atlas, settings.colors, glyphs=load_pearl_glyphs(config.game_dir, atlas.root))
    results, frames, stages = [], [], []
    for side in ('top', 'right', 'bottom', 'left'):
        scene = OracleScene(replace(settings, base_side=side, world_width=640, world_height=480))
        for _ in range(650):
            scene.step()
        scene.observe_matrix_pearl((1, 3))
        member, selected = scene.pearl_matrix.extracted_member, scene.observed_pearl
        checks, seen = 0, set()
        for tick in range(2200):
            scene.step()
            state = scene.behavior.state
            if tick % 20 == 0:
                check_pixels(renderer, scene)
                checks += 3
            if side == 'top':
                label = f'{state.value} / 槽位 {member.slot} / {tick/40:.1f}s / 2x'
                if tick % 4 == 0:
                    frames.append(snapshot(renderer, scene, closeup=True, label=label))
                if state not in seen:
                    stages.append(snapshot(renderer, scene, closeup=True, label=label))
                    seen.add(state)
            if scene.behavior.completed_cycles and scene.pearls_settled and scene.appearance.sleeping:
                break
        assert tick < 2199
        assert scene.pearl_matrix.extracted is None
        error = (selected.position-scene.pearl_matrix.anchor.position-member.offset).length()
        assert error < 1e-6
        revisions = (scene.pearl_visual_revision, scene.appearance.revision, scene.eyes.revision)
        for _ in range(200):
            scene.step()
        assert revisions == (scene.pearl_visual_revision, scene.appearance.revision, scene.eyes.revision)
        results.append(dict(side=side, ticks=tick+1, pixel_checks=checks, slot_error=error,
                            stable_idle_ticks=200, idle_revision_changes=0))
    frames[0].save(output/'oracle-matrix-observation.gif', save_all=True, append_images=frames[1:], duration=100, loop=0)
    sheet = Image.new('RGB', (480*3, 520*2), '#17232e')
    for i, stage in enumerate(stages):
        sheet.paste(stage, (480*(i % 3), 520*(i//3)))
    sheet.save(output/'oracle-matrix-observation-stages.png')
    window = OracleDebugWindow(replace(config, oracle=settings), load_atlas=False)
    window.timer.stop()
    window.renderer = window.canvas.renderer = renderer
    window.asset_message = '本机原版图集与缓存字形 · 矩阵抽取观察'
    window.assets.setText(window.asset_message)
    window.set_paused(True)
    window.observe_matrix_pearl()
    window.show()
    app.processEvents()
    window.grab().save(str(output/'oracle-matrix-observation-debug.png'))
    window.close()
    assert hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest() == digest
    report = dict(config_sha256=digest, cases=results)
    (output/'oracle-matrix-observation-metrics.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
