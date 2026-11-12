"""圆形眼睛保持屏幕像素形状，其余眼形用局部半透明采样保留旋转笔画"""
from dataclasses import dataclass
from functools import lru_cache
from math import atan2, ceil, degrees, floor, hypot

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QTransform

from .eyes import EYE_PIXELS, PixelEye, draw_eye_ink


@dataclass(frozen=True)
class EyeStamp:
    image: QImage
    origin: QPointF
    center: QPointF
    outline: QPainterPath | None
    color: int


@lru_cache(maxsize=256)
def eye_stamp(kind, sign, width, height, opened, lower, smooth_lid, color, density, phase):
    """缓存当前密度的正视像素图，转头时只变换这张小图，不逐格重采样"""
    if kind == 'normal':
        box = QRectF(-width/2, -height/2, width, height).united(
            QRectF(-width/2, float(lower)-.5, width, 1.))
        center = QPointF(0., float(lower)*(1.-opened))
    else:
        cells = EYE_PIXELS[kind][0 if sign < 0 else 1]
        box = QRectF(-width/2, -height/2, (max(x for x, y in cells)+1)*width/2,
                     max(y for x, y in cells)+1)
        center = box.center()
    left, top = floor(box.left()*density+phase[0])-2, floor(box.top()*density+phase[1])-2
    right, bottom = ceil(box.right()*density+phase[0])+2, ceil(box.bottom()*density+phase[1])+2
    image = QImage(right-left, bottom-top, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    origin = QPointF(phase[0]-left, phase[1]-top)
    painter = QPainter(image)
    try:
        painter.translate(origin)
        painter.scale(density, density)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        draw_eye_ink(painter, kind, sign, width, height, opened, lower, smooth_lid, color)
    finally:
        painter.end()
    alpha = np.frombuffer(image.constBits(), dtype=np.uint32).reshape(
        image.height(), image.bytesPerLine()//4) >> 24
    outline = None
    if np.all((alpha == 0) | (alpha == 255)):
        # 完整笔画按真实覆盖率抗锯齿，不用双线性滤镜把整个细眼形一起模糊
        outline = QPainterPath()
        for y, row in enumerate(alpha):
            start = None
            for x in range(image.width()+1):
                filled = x < image.width() and row[x] != 0
                if filled and start is None:
                    start = x
                elif not filled and start is not None:
                    outline.addRect(QRectF(start, y, x-start, 1))
                    start = None
        outline = outline.simplified()
    return EyeStamp(image, origin, center, outline, color)


def draw_stamp(painter, stamp, matrix, *, smooth):
    painter.setWorldTransform(matrix, True)
    if smooth and stamp.outline is not None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(stamp.color))
        painter.drawPath(stamp.outline)
    else:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
        painter.drawImage(QPointF(), stamp.image)


class ShapeAwareEye(PixelEye):
    """复用旧版的眼形参数；不改变表情、物理状态及头部其他部件"""
    def replay(self, painter):
        transform = painter.deviceTransform()
        density = round(hypot(transform.m11(), transform.m12()), 6)
        origin = transform.map(QPointF())
        phase = (round((origin.x()+self.sign*2.5*density) % 1., 6),
                 round((origin.y()+2.*density) % 1., 6))
        # 固定眼型不让无关的开度更新挤占小图缓存
        normal = self.kind == 'normal'
        stamp = eye_stamp(self.kind, self.sign, self.width, self.height,
                          self.opened if normal else 1., self.lower if normal else False,
                          self.smooth_lid if normal else False, self.color.rgba(), density, phase)
        center = transform.map(QPointF(self.eye.x+stamp.center.x(), self.eye.y+stamp.center.y()))
        fixed = QTransform.fromTranslate(
            floor(center.x()-stamp.origin.x()-stamp.center.x()*density+.5),
            floor(center.y()-stamp.origin.y()-stamp.center.y()*density+.5))
        anchor = transform.map(QPointF(self.eye.x, self.eye.y))
        soft = QTransform().translate(anchor.x(), anchor.y())
        soft.rotate(degrees(atan2(transform.m12(), transform.m11())))
        soft.scale((self.width-self.foreshortening)/self.width, 1.)
        soft.translate(-stamp.origin.x(), -stamp.origin.y())
        painter.save()
        try:
            # 变换已包含显示密度和 DPR；只在眼睛这层允许柔化
            painter.resetTransform()
            dpr = painter.device().devicePixelRatioF()
            painter.scale(1/dpr, 1/dpr)
            if self.kind in ('round', 'fixed_open') or (normal and self.opened >= 1.):
                draw_stamp(painter, stamp, fixed, smooth=False)
            elif normal and self.opened > 0.:
                self.draw_closing(painter, stamp, fixed, soft)
            else:
                draw_stamp(painter, stamp, soft, smooth=True)
        finally:
            painter.restore()

    def draw_closing(self, painter, stamp, fixed, soft):
        """混合保形与随头旋转的闭眼图，避免接近闭合时突然换角度或整眼变淡"""
        bounds = fixed.mapRect(QRectF(stamp.image.rect())).united(
            soft.mapRect(QRectF(stamp.image.rect()))).toAlignedRect()
        images = []
        for matrix, smooth in ((fixed, False), (soft, True)):
            image = QImage(bounds.size(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            local = QPainter(image)
            try:
                local.translate(-bounds.x(), -bounds.y())
                draw_stamp(local, stamp, matrix, smooth=smooth)
            finally:
                local.end()
            images.append(image)
        arrays = [np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
            image.height(), image.bytesPerLine()).astype(np.uint16) for image in images]
        weight = round((1.-self.opened)*255)
        pixels = ((arrays[0]*(255-weight)+arrays[1]*weight+127)//255).astype(np.uint8)
        image = QImage(pixels.data, bounds.width(), bounds.height(), pixels.strides[0],
                       QImage.Format.Format_ARGB32_Premultiplied)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(QPointF(bounds.topLeft()), image)
