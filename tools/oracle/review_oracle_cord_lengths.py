"""长线调整的真实图集对照、四边回放和仿真开销；不修改用户配置。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)

from PIL import Image
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.cords import OracleCords
from rw_creature_pet.oracle.render import OracleRenderer


def before_class():
    name = 'rw_creature_pet._cord_lengths_before'
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name('fixtures')/'cords_before_lengths.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.OracleCords


def create_scene(config, cords):
    with patch('rw_creature_pet.oracle.appearance.OracleCords', cords):
        return OracleScene(config.oracle)


def settled_metrics(scene):
    a = scene.appearance
    return dict(sleeping=a.sleeping, fine_lengths=a.cords.fine_lengths,
                main_length=sum(a.cords.main.rest), main_tail_length=sum(a.cords.main.rest[60:]),
                junction_radius=(a.main_cord[-1].position-a.upper).length(),
                lowest_fine_below_upper=max(p.position.y-a.upper.y for c in a.small_cords for p in c),
                lowest_fine_below_head=max(p.position.y-a.head.position.y for c in a.small_cords for p in c))


def frame(scene, renderer, tick, font):
    image = QImage(960, 600, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#17232e'))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(960/scene.world.width, 600/scene.world.height)
    h = scene.world.inner
    p.fillRect(QRectF(h.left, h.top, h.right-h.left, h.bottom-h.top), QColor('#111923'))
    renderer.draw(p, scene)
    p.resetTransform()
    p.setPen(QColor('#d7e5ed'))
    p.setFont(font)
    p.drawText(QPointF(14, 25), f'{tick/40:.1f}s / '+('停留' if scene.arrived else '绕行'))
    p.end()
    return Image.frombytes('RGBA', (960, 600), bytes(image.constBits())).convert('RGB')


def main():
    app = QApplication.instance() or QApplication([])
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    font = QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 11)
    config = AppConfig.load(ROOT/'config.toml')
    digest = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    atlas = Atlas(extract_atlas(config.game_dir))
    result = dict(config_sha256=digest, note='40 Hz simulation timings exclude rendering; Qt offscreen previews.')
    comparison = QImage(1000, 550, QImage.Format.Format_RGBA8888)
    comparison.fill(QColor('#17232e'))
    painter = QPainter(comparison)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setFont(font)
    for column, (label, cls) in enumerate((('before', before_class()), ('after', OracleCords))):
        renderer = OracleRenderer(atlas, config.oracle.colors)
        scene = create_scene(config, cls)
        for _ in range(650):
            scene.step()
        result[label] = dict(settled=settled_metrics(scene))
        painter.setPen(QColor('#d7e5ed'))
        painter.drawText(QPointF(column*500+16, 28), '修改前 / 2.2×' if column == 0 else '修改后 / 2.2×')
        painter.save()
        painter.translate(column*500+205, 205)
        painter.scale(2.2, 2.2)
        painter.translate(-scene.appearance.upper.x, -scene.appearance.upper.y)
        renderer.draw(painter, scene)
        painter.restore()

        scene = create_scene(config, cls)
        scene.start_lap()
        times, frames = [], []
        metrics = dict(max_main_error=0., max_fine_error=0., max_junction_radius=0.,
                       max_fine_radius=0., max_central_penetration=0.)
        for tick in range(2400):
            start = perf_counter()
            scene.step()
            times.append(perf_counter()-start)
            a = scene.appearance
            metrics['max_junction_radius'] = max(metrics['max_junction_radius'], (a.main_cord[-1].position-a.upper).length())
            h = scene.world.inner
            for kind, ropes in (('main', [a.cords.main]), ('fine', a.cords.fine)):
                for rope in ropes:
                    metrics['max_'+kind+'_error'] = max(metrics['max_'+kind+'_error'],
                        max(abs((q.position-p.position).length()-r) for p, q, r in zip(rope.points, rope.points[1:], rope.rest)))
                    for node in rope.points:
                        p = node.position
                        metrics['max_central_penetration'] = max(metrics['max_central_penetration'],
                            min(p.x-h.left, h.right-p.x, p.y-h.top, h.bottom-p.y))
                        if kind == 'fine':
                            metrics['max_fine_radius'] = max(metrics['max_fine_radius'], (p-a.upper).length())
            if scene.arrived and 'arrived_tick' not in metrics:
                metrics['arrived_tick'] = tick+1
            if scene.arrived and a.sleeping and 'sleep_tick' not in metrics:
                metrics['sleep_tick'] = tick+1
            if label == 'after' and tick % 12 == 0:
                frames.append(frame(scene, renderer, tick, font))
            if (tick+1) % 600 == 0:
                print(label, tick+1, 'sleep', a.sleeping, flush=True)
        metrics.update(moving_step_mean_ms=statistics.mean(times[:1500])*1000,
                       idle_step_mean_ms=statistics.mean(times[-100:])*1000,
                       final=settled_metrics(scene))
        result[label]['lap'] = metrics
        if frames:
            frames[0].save(ROOT/'artifacts/oracle-cord-lengths-preview.gif', save_all=True,
                           append_images=frames[1:], duration=300, loop=0)
            frames[-1].save(ROOT/'artifacts/oracle-cord-lengths-overview.png')
    painter.end()
    comparison.save(str(ROOT/'artifacts/oracle-cord-lengths-comparison.png'))
    result['config_unchanged'] = digest == hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    (ROOT/'artifacts/oracle-cord-lengths-metrics.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)
    assert app is not None


if __name__ == '__main__':
    main()
