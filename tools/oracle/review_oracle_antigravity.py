"""真实图集的四边整身漫游回放、插值帧像素边界与最终休眠检查。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import argparse
import hashlib
import json
from math import atan2, degrees
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from review_oracle_autonomy import check_pixels, closeup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=45., help='回放漫游秒数；默认 45，长时间检查可设 300')
    parser.add_argument('--sides', nargs='+', choices=('top', 'right', 'bottom', 'left'),
                        default=('top', 'right', 'bottom', 'left'))
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    config = AppConfig.load(ROOT/'config.toml')
    before = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    atlas = Atlas(extract_atlas(config.game_dir))
    glyphs = load_pearl_glyphs(config.game_dir, atlas.root)
    results, poses, frames = [], [], []
    gif_stride = 6
    for index, side in enumerate(args.sides):
        settings = replace(config.oracle, world_width=640, world_height=480,
                           arm_scale=.75, base_side=side, base_fraction=0.,
                           antigravity_duration_seconds=args.duration)
        scene = OracleScene(settings)
        scene.drift()
        limit = scene.behavior.drift_duration+3000
        frame_stride = max(6, (limit+299)//300)  # 长回放最多保存约 300 帧，不持续累积图片。
        if index == 0:
            gif_stride = frame_stride
        renderer = OracleRenderer(atlas, settings.colors, glyphs=glyphs)
        result = dict(side=side, duration_ticks=scene.behavior.drift_duration, pixel_checks=0,
                      max_angle=0., max_radius=0., max_arm_error=0., max_acceleration=0.,
                      max_drift_guide_speed=0., max_drift_body_speed=0., joined_paths=0, max_curve_count=0)
        observation_image = None
        elapsed = 0.
        for tick in range(limit):
            previous_route = scene.navigator.route
            previous_velocity = scene.body.chunks[0].velocity
            started = perf_counter()
            scene.step()
            elapsed += perf_counter()-started
            angle = abs(degrees(atan2(scene.body.direction.x, -scene.body.direction.y)))
            result['max_angle'] = max(result['max_angle'], angle)
            result['max_arm_error'] = max(result['max_arm_error'], scene.arm.constraint_error)
            result['max_acceleration'] = max(result['max_acceleration'],
                                            (scene.body.chunks[0].velocity-previous_velocity).length())
            result['max_curve_count'] = max(result['max_curve_count'], len(scene.navigator.route.curves))
            if scene.navigator.route is not previous_route and len(scene.navigator.route.curves) == 2:
                result['joined_paths'] += 1
            if scene.behavior.state == Activity.DRIFT:
                result['max_drift_guide_speed'] = max(result['max_drift_guide_speed'], scene.navigator.speed*40)
                result['max_drift_body_speed'] = max(result['max_drift_body_speed'], scene.body.chunks[0].velocity.length()*40)
            assert scene.arm.constraint_error < .025
            visual = scene.appearance
            result['max_radius'] = max(result['max_radius'],
                max((p.position-visual.upper).length() for p in
                    (visual.head, *visual.hands, *visual.feet, *visual.cloth, *visual.necklace)))
            if tick % 60 == 0:
                check_pixels(renderer, scene)
                result['pixel_checks'] += 3
            if tick == 450:
                poses.append(closeup(renderer, scene, f'{side} / 自由漂浮'))
            if scene.behavior.state == Activity.OBSERVE and observation_image is None:
                observation_image = closeup(renderer, scene, f'{side} / 失重观察')
            if index == 0 and tick % frame_stride == 0:
                frames.append(closeup(renderer, scene, f'自由漂浮与观察 / {tick/40:.1f}s'))
            if scene.behavior.state == Activity.IDLE and scene.arrived and visual.sleeping:
                break
        assert tick < limit-1, (side, scene.behavior.state, scene.pose.angle, visual.maximum_speed)
        assert scene.pose.settled and scene.pose.gravity_scale == 1.
        assert abs((scene.pose.angle+180.) % 360.-180.) < 1e-5
        assert scene.body.direction.y < -.9999
        result.update(sleep_tick=tick+1, mean_step_ms=1000*elapsed/(tick+1),
                      final_angle=scene.pose.angle, pearl_cycles=scene.behavior.completed_cycles)
        poses.append(observation_image or closeup(renderer, scene, f'{side} / 本轮无观察'))
        poses.append(closeup(renderer, scene, f'{side} / 恢复直立后停稳'))
        revision = visual.revision
        positions = [p.position for p in visual.points]
        for _ in range(200):
            scene.step()
        assert visual.revision == revision and positions == [p.position for p in visual.points]
        result['idle_rebuilds'] = visual.revision-revision
        results.append(result)
        print(result, flush=True)
    output = ROOT/'artifacts'
    output.mkdir(exist_ok=True)
    montage = Image.new('RGB', (380*len(results), 340*3))
    for i, pose in enumerate(poses):
        montage.paste(pose, ((i//3)*380, (i % 3)*340))
    montage.save(output/'oracle-antigravity-poses.png')
    frames[0].save(output/'oracle-antigravity-preview.gif', save_all=True,
                   append_images=frames[1:], duration=gif_stride*25, loop=0)
    window = OracleDebugWindow(config, load_atlas=True)
    window.timer.stop()
    window.canvas.renderer = OracleRenderer(atlas, config.oracle.colors, glyphs=glyphs)
    window.scene = scene
    window.canvas.scene = scene
    window.refresh()
    window.show()
    app.processEvents()
    window.grab().save(str(output/'oracle-antigravity-debug.png'))
    window.close()
    assert before == hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    (output/'oracle-antigravity-metrics.json').write_text(
        json.dumps(dict(cases=results, config_sha256=before), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
