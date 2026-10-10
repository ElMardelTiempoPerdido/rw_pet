"""衣装附件的本地贴图，按显示倍率选原图，目前不改变人偶物理"""
from functools import lru_cache

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QTransform

from ...shared.paths import PACKAGE_ROOT

MAID_DIRECTORY = PACKAGE_ROOT/'skin/maid'
MAID_HEAD_OFFSETS = {1.: 3., 1.5: 4., 2.: 5.}  # 当前倍率下的显示像素，不再乘系统 DPI
MAID_LACE_OFFSETS = {1.: (1., 0.), 1.5: (2., 1.), 2.: (2., 1.)}  # 内侧距中轴、顶部低于内搭领口
MAID_APRON_OFFSETS = {1.: 1., 1.5: 3., 2.: 4.}  # 顶部低于内搭领口的显示像素
MAID_RIBBON_UP_OFFSETS = {1.: (0., 1.), 1.5: (1., 2.), 2.: (2., 2.)}  # 左缘距头部中轴、顶部高于头顶
MAID_RIBBON_DOWN_OFFSETS = {1.: 7., 1.5: 12., 2.: 14.}  # 顶部低于内搭领口的显示像素


def maid_scale(density):
    # 正常入口精确命中 1/1.5/2；调试放大仍沿用最近一档原图
    return min(MAID_HEAD_OFFSETS, key=lambda value: abs(value-density))


@lru_cache(maxsize=15)
def _load_maid_image(part, scale):
    path = MAID_DIRECTORY/f'maid_{part}_{scale:g}x.png'
    image = QImage(str(path))
    if image.isNull():
        raise FileNotFoundError(f'Cannot load outfit image: {path}')
    return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def load_maid_head(scale):
    return _load_maid_image('head', scale)


@lru_cache(maxsize=3)
def load_maid_lace(scale):
    left = _load_maid_image('lace', scale)
    return left, left.transformed(QTransform.fromScale(-1., 1.))


def maid_head_layer(density, crown_y):
    scale = maid_scale(density)
    image = load_maid_head(scale)
    width, height = image.width()/scale, image.height()/scale
    return image, QRectF(-width/2, crown_y-MAID_HEAD_OFFSETS[scale]/scale, width, height)


def maid_lace_layers(density):
    """身体局部坐标：原点在中轴的领口高度，x 向右、y 向脚。"""
    scale = maid_scale(density)
    left, right = load_maid_lace(scale)
    gap, down = (value/scale for value in MAID_LACE_OFFSETS[scale])
    width, height = left.width()/scale, left.height()/scale
    return ((left, QRectF(-gap-width, down, width, height)),
            (right, QRectF(gap, down, width, height)))


def maid_apron_layer(density):
    scale = maid_scale(density)
    image = _load_maid_image('apron', scale)
    width, height = image.width()/scale, image.height()/scale
    return image, QRectF(-width/2, MAID_APRON_OFFSETS[scale]/scale, width, height)


def maid_ribbon_up_layer(density, crown_y):
    scale = maid_scale(density)
    image = _load_maid_image('ribbon_up', scale)
    right, rise = MAID_RIBBON_UP_OFFSETS[scale]
    return image, QRectF(right/scale, crown_y-rise/scale, image.width()/scale, image.height()/scale)


def maid_ribbon_down_layer(density):
    scale = maid_scale(density)
    image = _load_maid_image('ribbon_down', scale)
    width, height = image.width()/scale, image.height()/scale
    return image, QRectF(-width/2, MAID_RIBBON_DOWN_OFFSETS[scale]/scale, width, height)
