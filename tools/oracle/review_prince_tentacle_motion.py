"""真实场景的 Prince 触手移动预览，不读取或写入用户设置/角色文件"""
import argparse
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.prince_tentacles import DEFAULT_CONFIG, load_study
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--scenario', choices=('walk', 'corner', 'drag', 'stretch', 'autonomy', 'horizontal', 'hold'), default='walk')
    parser.add_argument('--side', choices=('top', 'right', 'bottom', 'left'), default='right')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--scale', type=float, choices=(1, 1.5, 2, 3, 4), default=2)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    wide = args.scenario in ('autonomy', 'horizontal', 'hold')
    size = (1200, 900) if args.scenario == 'hold' else (960, 640) if wide else (640, 480)
    scene = OracleScene(OracleConfig(body_appearance='prince', physics_backend='auto',
        world_width=size[0], world_height=size[1],
        edge_fraction=.499 if wide else .35, base_side=args.side,
        base_fraction=.5 if args.scenario == 'hold' else .6, halo_enabled=False, pearl_matrix_enabled=False,
        pearl_orbits_enabled=False, pearl_fixed_count=0), prince_study=load_study(args.config))
    scene.behavior.enabled = False
    renderer = OracleRenderer(colors=scene.config.active_colors)
    for _ in range(200):
        scene.step()
    start = scene.body.chunks[0].position
    inward = scene.base_normal()
    tangent = Vec2(-inward.y, inward.x)
    frames = []
    scale = args.scale
    camera = QRectF(0, 0, scene.world.width, scene.world.height)
    width, height = round(camera.width()*scale), round(camera.height()*scale)
    suffix = '' if args.side == 'right' else f'-{args.side}'
    output = args.output or ROOT/f'artifacts/prince/tentacles-{args.scenario}{suffix}.gif'
    peak = None
    for tick in range(1500 if args.scenario == 'hold' else 900):
        if args.scenario == 'autonomy':
            if tick == 40:
                scene.set_target(start+inward*300)
            elif tick == 500:
                scene.set_target(start+tangent*60)
        elif args.scenario == 'walk':
            if tick == 40:
                scene.set_target(start+tangent*120)
            elif tick == 460:
                scene.set_target(start-tangent*40)
        elif args.scenario == 'corner':
            if tick == 40:
                scene.set_target({'right': Vec2(390, 420), 'bottom': Vec2(60, 200),
                                  'left': Vec2(300, 60), 'top': Vec2(580, 300)}[args.side])
        else:
            if tick == 40:
                scene.drag.set_enabled(True)
                scene.drag.press(scene.head.position, lambda _: True)
                pointer = scene.head.position
            if 40 < tick <= 180:
                offset = inward*(900 if args.scenario in ('stretch', 'horizontal', 'hold') else 90)
                if args.scenario not in ('horizontal', 'hold'):
                    offset += tangent*45
                scene.drag.move(pointer+offset*((tick-40)/140))
            if tick == (1100 if args.scenario == 'hold' else 300):
                scene.drag.release()
        if not scene.drag.active:
            scene.look_target = scene.body.chunks[0].position+Vec2(-60, 0)
        scene.step()
        if tick % 4:
            continue
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('#E8E5DF'))
        painter = QPainter(image)
        try:
            painter.scale(scale, scale)
            painter.translate(-camera.x(), -camera.y())
            painter.setPen(QPen(QColor('#AEA9A2'), 1.))
            painter.drawRect(QRectF(.5, .5, scene.world.width-1, scene.world.height-1))
            renderer.draw(painter, scene, raster_scale=scale)
        finally:
            painter.end()
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        frame = Image.frombytes('RGBA', (width, height), bytes(rgba.constBits())).convert('RGB')
        frames.append(frame)
        if args.scenario == 'autonomy':
            capture = tick >= 400
        elif args.scenario in ('horizontal', 'hold'):
            capture = tick >= (800 if args.scenario == 'hold' else 180)
        else:
            capture = any(p.transferring for p in scene.prince_tentacles.parts)
        if peak is None and capture:
            peak = frame.copy()
    output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(output, save_all=True, append_images=frames[1:], duration=100, loop=0, disposal=2)
    (peak or frames[0]).save(output.with_suffix('.png'))
    print(output)
    return app


if __name__ == '__main__':
    main()
