"""触须绕转的正视/侧视离屏预览，独立于镜片旋转，延长观察仅用于对照"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.graphics.render import OverseerRenderer
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.shared.geometry import Bounds, Vec2
from tools.overseer.review_filament_observation import paint


def main():
    output = ROOT/'artifacts/overseer'
    output.mkdir(parents=True, exist_ok=True)
    scenes = []
    for appearance in ('standard', 'friend'):
        for view, look in (('front', Vec2(-50, 100)), ('side', Vec2(-240, 180))):
            model = Overseer(Bounds(0, 0, 640, 480), OverseerConfig(
                color='#000000' if appearance == 'friend' else '#72e6c4',
                observation_probability=1, observation_interval=999), seed=73)
            model.set_appearance(appearance)
            model.show(anchor=Anchor(Edge.TOP, .5))
            target = model.root+model.local_vector(look)
            for _ in range(100):
                model.step(target)
            model.lens.remaining = 20
            scenes.append((model, target, view, OverseerRenderer()))
    frames = []
    sheet = Image.new('RGB', (1280, 1376), '#20252b')
    for tick in range(560):
        frame = Image.new('RGB', (640, 688), '#20252b') if tick % 4 == 0 else None
        for index, (model, target, view, renderer) in enumerate(scenes):
            if tick == 450:
                model.lens.remaining = 0
            model.step(target)
            if frame is not None:
                pose = paint(model, renderer)
                x, y = (index % 2)*320, (index//2)*344
                frame.paste(pose, (x, y+24))
                label = f'{model.appearance} / {view} / {model.filament_motion.rotation.value*360%360:.0f} deg'
                ImageDraw.Draw(frame).text((x+8, y+6), label, fill='white')
                if tick in (80, 200, 320, 440):
                    col = (tick-80)//120
                    sheet.paste(pose, (col*320, index*344+24))
                    ImageDraw.Draw(sheet).text((col*320+8, index*344+6), label, fill='white')
        if frame is not None:
            frames.append(frame)
    sheet.save(output/'filament-rotation.png')
    frames[0].save(output/'filament-rotation.gif', save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    print(output/'filament-rotation.png')


if __name__ == '__main__':
    main()
