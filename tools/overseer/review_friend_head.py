"""生成花冠各倍率、角度和转头动画，测量投影开销，不修改用户配置"""
from math import cos, pi, sin
from pathlib import Path
from statistics import mean, quantiles
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

from rw_creature_pet.overseer.friend_head import _project, head_image
from rw_creature_pet.overseer import friend
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.shared.geometry import Bounds, Vec2


OUT = ROOT/'artifacts/overseer'


def sample(angle, density, azimuth=0.):
    return head_image(Vec2(sin(angle)*cos(azimuth), sin(angle)*sin(azimuth)),
                      cos(angle), Vec2(0, -1), density)[0]


def pil_image(image):
    return Image.frombytes('RGBA', (image.width(), image.height()), bytes(image.constBits()))


def review_distance_curve():
    OUT.mkdir(parents=True, exist_ok=True)
    sheet = Image.new('RGB', (1000, 400), '#bcbcbc')
    model = Overseer(Bounds(0, 0, 1920, 1080))
    model.set_appearance('friend')
    model.show(anchor=Anchor(Edge.BOTTOM, .5))
    model.extended = model.last_extended = 1.
    for row, (axis, direction) in enumerate((('Width', Vec2(1920, 0)), ('Height', Vec2(0, -1080)))):
        for col, fraction in enumerate((.1, .2, .5, .75, .9)):
            for _ in range(12):
                model.previous_look = model.look_at = model.eye_position()+direction*fraction
            with patch.object(friend, 'HEAD_GAZE_NEAR_FRACTION', 0.):
                previous = model.head_gaze()
            for index, (label, gaze) in enumerate((('Previous', previous), ('New', model.head_gaze()))):
                image = pil_image(head_image(*gaze, model.eye_position()-model.root, 2.)[0])
                image = image.resize((image.width*3, image.height*3), Image.Resampling.NEAREST)
                x, y = col*200+index*100, row*200
                sheet.paste(image, (x+(100-image.width)//2, y+50), image)
                ImageDraw.Draw(sheet).text((x+8, y+150), label, fill='#222222')
            ImageDraw.Draw(sheet).text((col*200+10, row*200+15), f'{axis} {fraction:.0%} / 2x raster', fill='#222222')
    path = OUT/'friend-head-near-curve.png'
    sheet.save(path)
    print(f'Distance preview: {path}')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    review_distance_curve()
    sheet = Image.new('RGB', (1000, 690), '#bcbcbc')
    for row, density in enumerate((1., 1.5, 2.)):
        for col, angle in enumerate((0, 20, 40, 60, 90)):
            image = pil_image(sample(angle*pi/180, density))
            x, y = col*200+10, row*230+25
            sheet.paste(image, (x, y), image)
            zoomed = image.resize((image.width*4, image.height*4), Image.Resampling.NEAREST)
            sheet.paste(zoomed, (x, y+50), zoomed)
            ImageDraw.Draw(sheet).text((x, y-18), f'{density:g}x / {angle}deg / native + 4x', fill='#222222')
    sheet.save(OUT/'friend-torus-angles.png')

    frames = []
    for i in range(96):
        # 穿过正面、两侧以及斜向注视，检查花纹不会在正面突然翻转
        phase = i/96*2*pi
        angle = sin(phase)*pi/2
        canvas = Image.new('RGB', (480, 210), '#bcbcbc')
        for column, density in enumerate((1., 2.)):
            image = pil_image(sample(angle, density, .5*sin(phase*.5)))
            enlarged = image.resize((image.width*4, image.height*4), Image.Resampling.NEAREST)
            x = column*240+(240-enlarged.width)//2
            canvas.paste(enlarged, (x, 25), enlarged)
            ImageDraw.Draw(canvas).text((column*240+10, 5), f'{density:g}x raster / 4x inspection', fill='#222222')
        frames.append(canvas)
    frames[0].save(OUT/'friend-torus-motion.gif', save_all=True, append_images=frames[1:], duration=40, loop=0)

    # 暖启动、方向持续变化；不包含仿真、窗口合成与素材首次读取
    for density in (1., 1.5, 2., 4.):
        sample(.7, density)
        _project.cache_clear()
        times = []
        for i in range(600):
            start = perf_counter()
            sample(1.01, density, i*.073)
            times.append((perf_counter()-start)*1000)
        start = perf_counter()
        for _ in range(3000):
            sample(1.01, density, 599*.073)
        cached = (perf_counter()-start)*1000/3000
        print(f'{density:g}x changing view: mean {mean(times):.3f} ms, '
              f'p95 {quantiles(times, n=20)[18]:.3f} ms; cached {cached:.3f} ms')
    print(f'Previews: {OUT}')


if __name__ == '__main__':
    main()
