"""真实图集回放：跨边跟随、召近、送回新悬浮点与完全静止。"""
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
(ROOT/'artifacts').mkdir(exist_ok=True)
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from review_oracle_autonomy import check_pixels


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    config = AppConfig.load(ROOT/'config.toml')
    digest = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    config = replace(config, oracle=replace(config.oracle, world_width=960, world_height=600,
                                           base_side='top', base_fraction=.5, float_speed=2.))
    window = OracleDebugWindow(config)
    window.timer.stop()
    window.show()
    app.processEvents()
    scene, renderer = window.scene, window.renderer
    assert renderer.atlas is not None and renderer.glyphs is not None
    pearl, old_home = scene.pearl, scene.pearl.home
    scene.behavior.start_roam(scene, adjacent=True, target_edge=1)
    replans, checks, peak, route = 0, 0, [0., 0.], pearl.route
    for tick in range(2400):
        scene.step()
        center = scene.body.chunks[0].position
        peak = [max(peak[0], abs(center.x-pearl.position.x)), max(peak[1], abs(center.y-pearl.position.y))]
        if route is not pearl.route:
            replans += 1
            route = pearl.route
        if tick % 80 == 0:
            check_pixels(renderer, scene)
            checks += 3
        if scene.behavior.state == Activity.IDLE and scene.arrived and pearl.settled:
            break
    assert tick < 2399 and pearl.home != old_home
    home = pearl.home
    window.set_paused(True)
    window.refresh()
    app.processEvents()
    window.grab().save(str(ROOT/'artifacts/oracle-pearl-follow-debug.png'))
    scene.observe_pearl('recall')
    for observe_tick in range(2000):
        scene.step()
        if observe_tick % 100 == 0:
            check_pixels(renderer, scene)
            checks += 3
        if scene.behavior.completed_cycles:
            break
    assert observe_tick < 1999 and pearl.position == home
    for _ in range(1500):
        scene.step()
        if scene.appearance.sleeping and scene.pose.settled and pearl.settled:
            break
    assert scene.appearance.sleeping and pearl.settled
    revisions = (scene.appearance.revision, pearl.revision, scene.eyes.revision)
    renderer_image = renderer._frame
    for _ in range(200):
        scene.step()
    assert revisions == (scene.appearance.revision, pearl.revision, scene.eyes.revision)
    # 单独测跟随范围维护，避开渲染和完整仿真的成本；静止不得规划路径。
    center = scene.body.chunks[0].position
    start = perf_counter()
    for _ in range(10000):
        pearl.follow_home(center, 360, 280)
    follow_us = (perf_counter()-start)*100
    assert pearl.revision == revisions[1] and renderer._frame is renderer_image
    metrics = dict(movement_ticks=tick+1, observe_ticks=observe_tick+1, replans=replans,
                   pixel_checks=checks, max_offset=peak,
                   old_home=[old_home.x, old_home.y], home=[home.x, home.y],
                   idle_revision_changes=0, idle_follow_microseconds=follow_us, config_sha256=digest)
    assert digest == hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    (ROOT/'artifacts/oracle-pearl-follow-metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    window.close()
    print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    main()
