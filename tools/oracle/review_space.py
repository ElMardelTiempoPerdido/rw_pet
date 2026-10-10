"""真实图集与次级物理的宽活动带回放；仅写 artifacts 和临时配置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import check_small_world as audit
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.oracle.ui.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.test_desktop import FakeScreen


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setQuitOnLastWindowClosed(False)
    audit.OUT = ROOT/'artifacts/space-review'
    audit.OUT.mkdir(exist_ok=True)
    atlas = audit.Atlas(audit.extract_atlas(audit.BASE.game_dir))
    audit.RENDERER = audit.OracleRenderer(atlas, audit.BASE.oracle.colors,
        glyphs=audit.load_pearl_glyphs(audit.BASE.game_dir, atlas.root))
    results = []
    for width, height, arm, fraction, edges in (
            (640, 385, .75, .3, ('top', 'right', 'bottom', 'left')),
            (640, 385, .75, .499, ('top', 'right', 'bottom', 'left')),
            (385, 640, .75, .499, ('top', 'right', 'bottom', 'left')),
            (240, 200, .6, .499, ('top', 'right', 'bottom', 'left')),
            (640, 200, .75, .2, ('left',))):
        name = f'{width}x{height}-arm{arm}-band{fraction}-{edges[0]}'
        config = replace(audit.BASE.oracle,
            arm_scale=arm, edge_fraction=fraction, allowed_edges=edges, base_side=edges[0],
            pearl_matrix_enabled=True, pearl_orbits_enabled=True, pearl_fixed_count=2,
            pearl_satellite_count=1, hide_cords=False, pearl_playback_probability=0.,
            antigravity_duration_seconds=45.)
        motion = OracleDesktopMotion(config, OracleDesktopViewport(0, 0, width, height))
        scene = motion.scene
        scene.set_autonomous(False)
        test = audit.Audit(scene, name)
        test.run(300)
        scene.start_lap()
        lap = test.run(4000, lambda: scene.arrived)
        test.run(300)
        scene.observe_matrix_pearl(scene.pearl_matrix.pearls[0].slot)
        reading = test.run(7000, lambda: scene.behavior.completed_cycles > 0 and scene.pearl_matrix.extracted is None)
        scene.drag.set_enabled(True)
        assert scene.drag.press(scene.body.chunks[0].position, lambda _: True)
        scene.drag.move(audit.Vec2(scene.world.width/2, scene.world.height/2))
        test.run(120)
        scene.drag.release()
        drag = test.run(2000, lambda: not scene.drag.controlling)
        test.run(300)
        scene.drift()
        drift = test.run(6000, lambda: not scene.behavior.drift_active and scene.pose.settled and scene.arrived)
        test.run(900)
        audit.snapshot(scene, name)
        result = dict(test.result(), name=name, world_size=(scene.world.width, scene.world.height),
                      actual_scale=motion.viewport.physical_scale, lap_complete=lap, reading_complete=reading,
                      drag_complete=drag, drift_complete=drift)
        results.append(result)
        print(name, json.dumps(result, ensure_ascii=True), flush=True)
        (audit.OUT/'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    screen = FakeScreen(QRect(0, 0, 1707, 1027), 1.5)
    with tempfile.TemporaryDirectory() as temp, patch('rw_creature_pet.oracle.ui.settings.selected_screen', return_value=screen):
        config = replace(audit.BASE, desktop=replace(audit.BASE.desktop, scale=4.),
                         oracle=replace(audit.BASE.oracle, arm_scale=.75, edge_fraction=.2))
        dialog = OracleSettingsDialog(config, SettingsStore(Path(temp)/'settings.json'),
                                      assets=OracleAssets(audit.RENDERER, '', {}, ''))
        try:
            dialog.show()
            dialog.show_space_settings()
            for language in ('zh', 'en'):
                language_manager().set_language(language)
                app.processEvents()
                dialog.grab().save(str(audit.OUT/f'settings-{language}.png'))
            dialog.fill_space_recommendation()
            app.processEvents()
            dialog.grab().save(str(audit.OUT/'settings-recommended.png'))
            assert dialog.candidate().oracle.edge_fraction == .3
        finally:
            dialog.shutdown()
            dialog.close()
    assert hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest() == audit.CONFIG_HASH
    assert all(not r['errors'] and all(r[k] for k in ('lap_complete', 'reading_complete',
               'drag_complete', 'drift_complete')) for r in results), 'See space-review/results.json'


if __name__ == '__main__':
    main()
