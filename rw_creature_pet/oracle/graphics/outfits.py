"""按通用部件定义加载、定位和镜像素材，原图及翻转结果均复用缓存"""
from functools import lru_cache
from math import hypot

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QTransform

from ...shared.paths import PACKAGE_ROOT
from .outfit_definition import Slot


@lru_cache(maxsize=128)
def load_outfit_image(asset, mirrored=False):
    if mirrored:
        return load_outfit_image(asset).transformed(QTransform.fromScale(-1., 1.))
    path = PACKAGE_ROOT/asset
    image = QImage(str(path))
    if image.isNull():
        raise FileNotFoundError(f'Cannot load outfit image: {path}')
    return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def component_layers(component, density, *, anchor_y=0.):
    """返回局部坐标内的原图及矩形，不对外共享可变的 QRectF"""
    variant = component.variant(density)
    image = adjusted_outfit_image(variant.asset, component.color_adjustment)
    scale = variant.density
    width, height = image.width()/scale, image.height()/scale
    x, y = (value/scale for value in variant.offset)
    x -= component.image_origin[0]*width
    y += anchor_y-component.image_origin[1]*height
    x += component.offset[0]
    y += component.offset[1]
    layers = ((image, QRectF(x, y, width, height)),)
    if component.mirror:
        layers += ((adjusted_outfit_image(variant.asset, component.color_adjustment, True),
                    QRectF(-x-width, y, width, height)),)
    return layers


@lru_cache(maxsize=128)
def adjusted_outfit_image(asset, adjustment, mirrored=False):
    """仅在参数改变时调色，保持 alpha；中性参数直接复用原图"""
    if not any(adjustment):
        return load_outfit_image(asset, True) if mirrored else load_outfit_image(asset)
    if mirrored:
        return adjusted_outfit_image(asset, adjustment).transformed(QTransform.fromScale(-1., 1.))
    source = load_outfit_image(asset)
    image = source.copy()
    hue, saturation, brightness = adjustment
    for y in range(image.height()):
        for x in range(image.width()):
            color = source.pixelColor(x, y)
            if not color.alpha():
                continue
            h, s, v, a = color.getHsvF()
            # 无色像素保持无色，避免提高饱和度时给白色区域凭空指定红色
            if s > 0:
                h = (h+hue/360.) % 1.
                s = max(0., min(1., s+saturation/100.))
            v = max(0., min(1., v+brightness/100.))
            color.setHsvF(h, s, v, a)
            image.setPixelColor(x, y, color)
    return image


@lru_cache(maxsize=128)
def head_outfit_radius(definition, density, crown):
    return max((hypot(x, y) for slot in (Slot.BEHIND_HEAD, Slot.FRONT_HEAD)
                for part in definition.at(slot) for _, rect in component_layers(part, density, anchor_y=crown)
                for x in (rect.left(), rect.right()) for y in (rect.top(), rect.bottom())), default=0.)


def outfit_raster_key(definition, density):
    # 不带部件的常规外观不因倍率重录矢量指令；定义变化仍使缓存失效
    return definition, tuple(part.variant(density) for part in definition.components)
