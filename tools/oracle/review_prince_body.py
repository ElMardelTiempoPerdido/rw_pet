"""Prince 普通移动和反重力漫游的身体预览，不读取或修改用户配置"""
import argparse
import importlib.util
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, help='可选的修改前源文件快照目录，仅供离屏对照')
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/prince/body-curve')
    parser.add_argument('--mode', choices=('ordinary', 'drift'), default='drift')
    args = parser.parse_args()
    if args.baseline:
        import importlib
        for suffix in ('motion.prince_spine', 'motion.prince', 'motion.prince_robe', 'graphics.appearance'):
            name = 'rw_creature_pet.oracle.'+suffix
            importlib.import_module(name.rsplit('.', 1)[0])
            spec = importlib.util.spec_from_file_location(name, args.baseline/Path(*name.split('.')).with_suffix('.py'))
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        # 早期快照没有独立失重力度入口，允许继续用同一场景做离屏对照
        from inspect import signature
        posture = sys.modules['rw_creature_pet.oracle.motion.prince'].PrincePosture
        old_step = posture.step
        if 'weightlessness' not in signature(old_step).parameters:
            def baseline_step(self, *args, weightlessness=0., **kwargs):
                return old_step(self, *args, **kwargs)
            posture.step = baseline_step

    from PIL import Image
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    from rw_creature_pet.oracle.config import OracleConfig
    from rw_creature_pet.oracle.graphics.render import OracleRenderer
    from rw_creature_pet.oracle.scene import OracleScene
    from rw_creature_pet.shared.geometry import Vec2

    app = QApplication.instance() or QApplication([])
    scene = OracleScene(OracleConfig(body_appearance='prince', physics_backend='auto',
        world_width=1200, world_height=900, edge_fraction=.499, base_side='right', base_fraction=.5,
        pearl_matrix_enabled=False, pearl_orbits_enabled=False, pearl_fixed_count=0, halo_enabled=False))
    for _ in range(250):
        scene.step()
    origin = scene.body.chunks[0].position
    renderer = OracleRenderer(colors=scene.config.active_colors)
    frames, peaks = [], []
    for tick in range(1000):
        if args.mode == 'drift':
            if tick == 20:
                scene.behavior.start_drift(scene)
                scene.behavior.drift_next_move = 0
        elif tick in (20, 300, 600):
            shift = {20: Vec2(-100, -120), 300: Vec2(-40, 120), 600: Vec2()}[tick]
            scene.set_target(origin+shift)
        scene.step()
        if tick % 4:
            continue
        image = QImage(560, 600, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('#e8e5df'))
        painter = QPainter(image)
        try:
            painter.translate(280, 270)
            painter.scale(4, 4)
            upper = scene.body.chunks[0].position
            painter.translate(-upper.x, -upper.y)
            renderer.draw_geometry(painter, scene, arm=False, cords=False, pearl=False,
                                   halo=False, raster_scale=4, cache_body=True)
        finally:
            painter.end()
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        frames.append(Image.frombytes('RGBA', (560, 600), bytes(rgba.constBits())).convert('RGB'))
        if tick in (120, 360, 600, 840):
            peaks.append(frames[-1])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output = args.output.with_name(args.output.name+'-'+args.mode)
    frames[0].save(output.with_suffix('.gif'), save_all=True, append_images=frames[1:],
                   duration=100, loop=0, disposal=2)
    strip = Image.new('RGB', (560*len(peaks), 600))
    for i, peak in enumerate(peaks):
        strip.paste(peak, (560*i, 0))
    strip.save(output.with_suffix('.png'))
    print(output.with_suffix('.gif'))
    return app


if __name__ == '__main__':
    main()
