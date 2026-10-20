"""Prince 多段弯折、真实拖拽和松手恢复的离屏预览，不读取用户配置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import sin, pi
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.graphics.raster import local_canvas, pixel_density
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.shared.geometry import Vec2
from tools.oracle.review_prince_posture import advance, make_scene


def draw(renderer, scene, title, *, skeleton=False, camera=None, pointer=False):
    scale, width, height = 4., 560, 560
    origin = scene.body.chunks[0].position
    camera = camera or origin
    bounds = QRectF(camera.x-width/(2*scale), camera.y-185/scale, width/scale, height/scale)
    density = pixel_density('adaptive', scale)
    layer, rect = local_canvas(bounds, density)
    painter = QPainter(layer)
    painter.scale(density, density)
    painter.translate(-rect.x(), -rect.y())
    renderer.draw_geometry(painter, scene, cache_body=True, arm=False, cords=False,
                           pearl=False, halo=False, raster_scale=scale)
    painter.end()
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('#e8e5df'))
    painter = QPainter(image)
    painter.drawImage(QRectF((rect.x()-bounds.x())*scale, (rect.y()-bounds.y())*scale,
                           rect.width()*scale, rect.height()*scale), layer)
    if skeleton:
        painter.setPen(QPen(QColor('#d78c39'), 1.))
        points = scene.prince_posture.frame(origin, scene.body.direction).points
        for a, b in zip(points, points[1:]):
            painter.drawLine(round((a.x-bounds.x())*scale), round((a.y-bounds.y())*scale),
                             round((b.x-bounds.x())*scale), round((b.y-bounds.y())*scale))
        painter.setBrush(QColor('#d78c39'))
        for p in points:
            painter.drawEllipse(QRectF((p.x-bounds.x())*scale-3, (p.y-bounds.y())*scale-3, 6, 6))
    if pointer and scene.drag.active:
        point = scene.drag.controller.pointer
        x, y = (point.x-bounds.x())*scale, (point.y-bounds.y())*scale
        painter.setPen(QPen(QColor('#9b3ea4'), 2.))
        painter.drawLine(round(x-5), round(y), round(x+5), round(y))
        painter.drawLine(round(x), round(y-5), round(x), round(y+5))
    painter.setFont(settings_font())
    painter.setPen(QColor('#34313f'))
    painter.drawText(20, 28, title+' / 4x')
    painter.end()
    return image


def lower_drag_preview(output):
    scenes = [make_scene(), make_scene()]
    renderers, cameras, starts = [], [], []
    for scene, index in zip(scenes, (1, 0)):
        scene.drag.set_enabled(True)
        for _ in range(400):
            scene.step()
        renderers.append(OracleRenderer(colors=scene.config.active_colors))
        cameras.append(scene.body.chunks[0].position)
        starts.append(scene.prince_posture.points[index].position)
    frames = []
    for tick in range(1000):
        for scene, start in zip(scenes, starts):
            if tick == 20:
                scene.drag.press(start, lambda _: True)
            if tick == 40:
                scene.drag.move(start+Vec2(4., 0.))
            if 200 <= tick < 260:
                scene.drag.move(start+Vec2(4., 0.)+Vec2(32., -12.)*((tick-199)/60))
            if tick == 680:
                scene.drag.release()
            scene.step()
        if tick % 4 == 0:
            pair = Image.new('RGB', (1120, 560))
            for i, (scene, renderer, camera, label) in enumerate(
                    zip(scenes, renderers, cameras, ('Waist', 'Lower hem'))):
                state = ('Moving' if 200 <= tick < 260 else 'Hold still') if scene.drag.active else (
                    'Recover' if scene.drag.recovering else 'Rest')
                frame = draw(renderer, scene, f'{label}: {state}', camera=camera,
                             pointer=True).convertToFormat(QImage.Format.Format_RGBA8888)
                pair.paste(Image.frombytes('RGBA', (560, 560), bytes(frame.constBits())).convert('RGB'),
                           (i*560, 0))
            frames.append(pair)
    frames[0].save(output/'prince-lower-drag.gif', save_all=True, append_images=frames[1:],
                   duration=100, loop=0, disposal=2)
    strip = Image.new('RGB', (1120*3, 560))
    for i, tick in enumerate((220, 600, 980)):
        strip.paste(frames[tick//4], (1120*i, 0))
    strip.save(output/'prince-lower-drag-frames.png')
    print(output/'prince-lower-drag.gif')


def gaze_height_preview(output, *, projection=False):
    cases = ((('Down left', Vec2(-.6, .8)), ('Near centre left', Vec2(-.2, .8)),
              ('Down centre', Vec2(0., .8)), ('Near centre right', Vec2(.2, .8)),
              ('Down right', Vec2(.6, .8))) if projection else
             (('Rest', Vec2()), ('Above', Vec2(.7, -.7)),
              ('Level', Vec2(.7, 0.)), ('Below', Vec2(.7, .7))))
    sheet = QImage(560*len(cases), 560*2, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#e8e5df'))
    painter = QPainter(sheet)
    for i, (title, gaze) in enumerate(cases):
        scene = make_scene()
        origin = scene.body.chunks[0].position
        for _ in range(400):
            advance(scene, origin, 0., gaze)
        renderer = OracleRenderer(colors=scene.config.active_colors)
        for row in range(2):
            painter.drawImage(i*560, row*560, draw(renderer, scene, title, skeleton=bool(row)))
    painter.end()
    name = 'prince-bow-projection' if projection else 'prince-gaze-height'
    sheet.save(str(output/f'{name}.png'))
    print(output/f'{name}.png')
    if projection:
        scene = make_scene()
        origin = scene.body.chunks[0].position
        renderer = OracleRenderer(colors=scene.config.active_colors)
        for _ in range(400):
            advance(scene, origin, 0., Vec2(-.6, .8))
        frames = []
        for tick in range(640):
            if tick < 360:
                t = max(0., min(1., (tick-60)/240))
                horizontal = -.6+1.2*t*t*(3-2*t)
            else:
                t = min(1., (tick-360)/120)
                horizontal = .6*(1-t*t*(3-2*t))
            advance(scene, origin, 0., Vec2(horizontal, .8))
            if tick % 4 == 0:
                frame = draw(renderer, scene, 'Downward sweep', skeleton=True).convertToFormat(
                    QImage.Format.Format_RGBA8888)
                frames.append(Image.frombytes('RGBA', (560, 560), bytes(frame.constBits())).convert('RGB'))
        frames[0].save(output/f'{name}.gif', save_all=True, append_images=frames[1:],
                       duration=100, loop=0, disposal=2)
        print(output/f'{name}.gif')


def main():
    app = QApplication.instance() or QApplication([])
    output = ROOT/'artifacts/prince'
    output.mkdir(parents=True, exist_ok=True)
    if '--lower-drag' in sys.argv:
        lower_drag_preview(output)
        return
    if '--gaze-height' in sys.argv:
        gaze_height_preview(output)
        return
    if '--bow-projection' in sys.argv:
        gaze_height_preview(output, projection=True)
        return
    sheet = QImage(560*4, 560*2, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#e8e5df'))
    painter = QPainter(sheet)
    cases = (('Rest', Vec2()), ('Side look', Vec2(.8, 0.)),
             ('Low side look', Vec2(.7, .7)), ('Down look', Vec2(0., 1.)))
    for i, (title, gaze) in enumerate(cases):
        scene = make_scene()
        origin = scene.body.chunks[0].position
        for _ in range(400):
            advance(scene, origin, 0., gaze)
        renderer = OracleRenderer(colors=scene.config.active_colors)
        for row in range(2):
            painter.drawImage(i*560, row*560, draw(renderer, scene, title, skeleton=bool(row)))
    painter.end()
    sheet.save(str(output/'prince-spine-poses.png'))

    scene = make_scene()
    scene.drag.set_enabled(True)
    renderer = OracleRenderer(colors=scene.config.active_colors)
    for _ in range(400):
        scene.step()
    start = scene.head.position
    frames = []
    for tick in range(780):
        if tick == 40:
            scene.drag.press(start, lambda _: True)
            # 微小初始不对称也不能在静止抓取中发展为颈部反弯
            scene.prince_posture.points[2].position += Vec2(.01, 0.)
        if 140 <= tick < 340:
            t = (tick-140)/200
            scene.drag.move(start+Vec2(45*sin(t*2*pi), 25*(1-sin(t*2*pi+pi/2))))
        if tick == 540:
            scene.drag.release()
        scene.step()
        if tick%2 == 0:
            title = ('Grab head' if 140 <= tick < 340 else 'Hold still') if scene.drag.active else (
                'Recover' if scene.drag.recovering else 'Rest')
            frame = draw(renderer, scene, title).convertToFormat(QImage.Format.Format_RGBA8888)
            frames.append(Image.frombytes('RGBA', (frame.width(), frame.height()), bytes(frame.constBits())).convert('RGB'))
    frames[0].save(output/'prince-spine-drag.gif', save_all=True, append_images=frames[1:],
                   duration=50, loop=0, disposal=2)
    strip = Image.new('RGB', (560*4, 560))
    for i, index in enumerate((90, 125, 250, 360)):
        strip.paste(frames[index], (560*i, 0))
    strip.save(output/'prince-spine-drag-frames.png')
    print(output/'prince-spine-poses.png')
    print(output/'prince-spine-drag.gif')


if __name__ == '__main__':
    main()
