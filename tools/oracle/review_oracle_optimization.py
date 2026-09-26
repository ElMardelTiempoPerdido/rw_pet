"""Compare current movement and real-asset pixels with a pre-optimization snapshot."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import importlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
from PIL import Image
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.render import OracleRenderer


def pixels(renderer, scene, *, scale=1., dpr=1.):
    image = QImage(round(960*scale), round(600*scale), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    image.setDevicePixelRatio(dpr)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(scale/dpr, scale/dpr)
    if isinstance(renderer, OracleRenderer):
        # 对照历史性能优化时的矢量外观；像素化另有专门的检查脚本。
        renderer.draw(p, scene, .5, pixelated=False)
    else:
        renderer.draw(p, scene, .5)
    p.end()
    return image


def difference(a, b):
    aa, bb = [np.frombuffer(v.constBits(), dtype=np.uint8).astype(np.int16) for v in (a, b)]
    delta = np.abs(aa-bb)
    return dict(max_channel_difference=int(delta.max()), changed_pixels=int(np.count_nonzero(delta.reshape(-1,4).max(axis=1))),
                over_3_pixels=int(np.count_nonzero(delta.reshape(-1,4).max(axis=1)>3)))


def main():
    app = QApplication.instance() or QApplication([])
    directory = ROOT/'artifacts/performance-round-baseline/rw_creature_pet'
    if not (directory/'__init__.py').exists():
        raise SystemExit('Requires the pre-optimization snapshot in artifacts/performance-round-baseline.')
    spec = importlib.util.spec_from_file_location('baseline_pet', directory/'__init__.py',
                                                 submodule_search_locations=[str(directory)])
    package = importlib.util.module_from_spec(spec)
    sys.modules['baseline_pet'] = package
    spec.loader.exec_module(package)
    old_config = importlib.import_module('baseline_pet.config').AppConfig.load(directory.parent/'config.toml')
    old_scene = importlib.import_module('baseline_pet.oracle.scene').OracleScene
    old_renderer = importlib.import_module('baseline_pet.oracle.render').OracleRenderer
    config = AppConfig.load(ROOT/'config.toml')
    atlas = Atlas(extract_atlas(config.game_dir))
    glyphs = load_pearl_glyphs(config.game_dir, atlas.root)
    before, after = old_scene(old_config.oracle), OracleScene(config.oracle)
    renderers = [old_renderer(atlas, config.oracle.colors, glyphs=glyphs),
                 OracleRenderer(atlas, config.oracle.colors, glyphs=glyphs)]
    for scene in (before, after):
        scene.start_lap()
    result, poses, max_error = [], [], 0.
    for tick in range(2800):
        before.step(); after.step()
        error = max(((a.position.x-b.position.x)**2+(a.position.y-b.position.y)**2)**.5
                    for a,b in zip(before.appearance.points, after.appearance.points))
        max_error = max(max_error, error)
        assert error < 1e-6, (tick, error)
        assert before.appearance.sleeping == after.appearance.sleeping, tick
        if tick in (0, 100, 300, 600, 900, 1200, 1600, 2300, 2799):
            a, b = pixels(renderers[0], before), pixels(renderers[1], after)
            diff = difference(a,b)
            result.append(dict(tick=tick, sleeping=after.appearance.sleeping, **diff))
            assert diff['over_3_pixels'] < 8, (tick,diff)
            if tick in (300, 900, 2300):
                for v in (a,b):
                    converted = v.convertToFormat(QImage.Format.Format_RGBA8888)
                    poses.append(Image.frombytes('RGBA', (v.width(), v.height()), bytes(converted.constBits())))
    assert after.appearance.sleeping
    scale_checks = []
    for scale, dpr in ((.5, 1.), (1., 1.25), (1., 1.5), (2., 2.), (4., 1.5)):
        a, b = pixels(renderers[0], before, scale=scale,dpr=dpr), pixels(renderers[1], after,scale=scale,dpr=dpr)
        diff = difference(a,b)
        scale_checks.append(dict(scale=scale,dpr=dpr,**diff))
        assert diff['over_3_pixels'] < 8, (scale,dpr,diff)
    sheet = Image.new('RGBA', (1920,1800), '#17232e')
    for i, pose in enumerate(poses):
        sheet.alpha_composite(pose,((i%2)*960,(i//2)*600))
    sheet.convert('RGB').save(ROOT/'artifacts/oracle-optimization-comparison.png')
    report = dict(maximum_point_error=max_error, sampled_frames=result, vector_scale_checks=scale_checks)
    (ROOT/'artifacts/oracle-optimization-comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)


if __name__ == '__main__':
    main()
