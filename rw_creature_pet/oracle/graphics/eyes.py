"""固定像素眼形与摸摸时的眼睑覆盖率过渡"""
from math import ceil, floor, hypot

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter


# 坐标相对常规 2×2 睁眼矩形的左上角；第一份对应眼睛1，第二份对应眼睛2
EYE_PIXELS = {
    'squeezed': (((0, 0), (1, 1), (0, 2)), ((1, 0), (0, 1), (1, 2))),
    'slant_in': (((0, 0), (1, 1)), ((1, 0), (0, 1))),
    'slant_out': (((1, 0), (0, 1)), ((0, 0), (1, 1))),
    'round': (((1, 0), (0, 1), (2, 1), (1, 2)),)*2,
    'chevron_up': (((1, 0), (0, 1), (2, 1)),)*2,
    'chevron_down': (((0, 0), (2, 0), (1, 1)),)*2,
    'fixed_open': (((0, 0), (1, 0), (0, 1), (1, 1)),)*2,
    'fixed_closed': (((0, 0), (1, 0)),)*2,
}


def draw_eye_shape(painter, kind, sign, rect):
    """复用头部坐标和横向透视，固定表情不受睁闭眼或较低眼位影响"""
    cell_width = rect.width()/2
    for x, y in EYE_PIXELS[kind][0 if sign < 0 else 1]:
        painter.drawRect(QRectF(rect.x()+x*cell_width, rect.y()+y, cell_width, 1))
    if kind == 'round':
        painter.save()
        painter.setBrush(QColor('#ffffff'))
        painter.drawRect(QRectF(rect.x()+cell_width, rect.y()+1, cell_width, 1))
        painter.restore()


class EyeLidTransition:
    """混合相邻像素高度的眼睛遮罩，只让收缩边缘逐渐露出下方皮肤"""
    def __init__(self, closed, opened, amount, color):
        self.closed, self.opened = closed, opened
        self.amount, self.color = amount, QColor(color)

    def rect(self, amount):
        a, b = self.closed, self.opened
        return QRectF(a.x()+(b.x()-a.x())*amount, a.y()+(b.y()-a.y())*amount,
                      a.width()+(b.width()-a.width())*amount,
                      a.height()+(b.height()-a.height())*amount)

    def replay(self, painter):
        transform = painter.deviceTransform()
        density = hypot(transform.m21(), transform.m22())
        steps = max(1, ceil((self.opened.height()-self.closed.height())*density-1e-6))
        position = self.amount*steps
        index = min(steps-1, floor(position))
        weight = round((position-index)*255)
        rects = self.rect(index/steps), self.rect((index+1)/steps)
        bounds = transform.mapRect(rects[0].united(rects[1])).adjusted(-1, -1, 1, 1).toAlignedRect()
        masks = []
        for rect in rects:
            mask = QImage(bounds.size(), QImage.Format.Format_ARGB32_Premultiplied)
            mask.fill(0)
            local = QPainter(mask)
            try:
                local.translate(-bounds.x(), -bounds.y())
                local.setWorldTransform(transform, True)
                local.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                local.setPen(Qt.PenStyle.NoPen)
                local.setBrush(Qt.GlobalColor.white)
                local.drawRect(rect)
            finally:
                local.end()
            masks.append(mask)
        # 两份遮罩都采用原来的硬像素绘制；共有像素始终不透明，不会整只眼睛一起淡出
        coverage = [np.frombuffer(mask.constBits(), dtype=np.uint32).reshape(
            mask.height(), mask.bytesPerLine()//4) >> 24 for mask in masks]
        alpha = (coverage[0]*(255-weight)+coverage[1]*weight+127)//255
        pixels = alpha << 24
        for channel, shift in ((self.color.red(), 16), (self.color.green(), 8), (self.color.blue(), 0)):
            pixels |= ((alpha*channel+127)//255) << shift
        image = QImage(pixels.data, bounds.width(), bounds.height(), pixels.strides[0],
                       QImage.Format.Format_ARGB32_Premultiplied)
        painter.save()
        # 遮罩已包含旋转及设备缩放，保留原画笔的裁剪和透明度，只取消重复坐标变换
        painter.resetTransform()
        dpr = painter.device().devicePixelRatioF()
        painter.scale(1/dpr, 1/dpr)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(QPointF(bounds.topLeft()), image)
        painter.restore()
