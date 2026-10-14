"""面部 PNG 在头部局部坐标中投影，保持原色并裁剪到皮肤轮廓"""
from math import ceil, floor

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath

from .face_assets import face_image


# 极限抬头时的局部纵向比例：头顶继续强压缩，下半张脸保留体积
UPPER_FACE_SCALE = .25
LOWER_FACE_SCALE = .90
# 极限抬头时额外上移的逻辑像素；平方缓入使轻微抬头时移动更克制
UPWARD_EXTRA_LIFT = 1.5


def project_face_y(y, pitch, top, bottom):
    """对局部比例积分，得到连续且不会折返的映射，再沿头部纵轴渐进上移"""
    up = max(0., min(1., pitch))
    if up == 0.:
        return y-pitch*1.5
    span = bottom-top

    def integral(value):
        distance = value-top
        within = max(0., min(span, distance))
        # 比例从头顶向下线性增加，轮廓以外按端点比例延续，避免大图边缘翻折
        return (UPPER_FACE_SCALE*distance
                +(LOWER_FACE_SCALE-UPPER_FACE_SCALE)*within*within/(2*span)
                +(LOWER_FACE_SCALE-UPPER_FACE_SCALE)*max(0., distance-span))

    return (1-up)*y+up*(integral(y)-integral(0.))-pitch*1.5-UPWARD_EXTRA_LIFT*up*up


class FaceWarp:
    """在最终设备像素上反查源图，避免旋转后的逐行接缝和半透明重叠"""
    def __init__(self, image, left, scale_x, edges):
        self.image, self.left, self.scale_x = image, left, scale_x
        # 与 Qt 像素边界的取舍保持一致，微小浮点余差不应把整行切换到相邻源像素
        self.edges = np.round(np.asarray(edges)*256)/256
        self.rect = QRectF(left, edges[0], image.width()*scale_x, edges[-1]-edges[0])

    def replay(self, painter):
        transform = painter.deviceTransform()
        inverse, valid = transform.inverted()
        if not valid:
            return
        local_rect = self.rect.intersected(painter.clipBoundingRect())
        if local_rect.isEmpty():
            return
        bounds = transform.mapRect(local_rect)
        left, top = floor(bounds.left()), floor(bounds.top())
        width, height = ceil(bounds.right())-left, ceil(bounds.bottom())-top
        x, y = np.meshgrid(np.arange(width)+left+.5, np.arange(height)+top+.5)
        local_x = inverse.m11()*x+inverse.m21()*y+inverse.dx()
        local_y = inverse.m12()*x+inverse.m22()*y+inverse.dy()
        source_x = np.floor(np.round((local_x-self.left)/self.scale_x*256)/256-1e-7).astype(np.intp)
        source_y = np.searchsorted(self.edges, np.round(local_y*256)/256, side='left')-1
        inside = ((source_x >= 0) & (source_x < self.image.width())
                  & (source_y >= 0) & (source_y < self.image.height()))
        source = np.frombuffer(self.image.constBits(), dtype=np.uint32).reshape(
            self.image.height(), self.image.bytesPerLine()//4)
        pixels = np.zeros((height, width), dtype=np.uint32)
        pixels[inside] = source[source_y[inside], source_x[inside]]
        image = QImage(pixels.data, width, height, pixels.strides[0],
                       QImage.Format.Format_ARGB32_Premultiplied)
        painter.save()
        # 保留现有裁剪与透明度；坐标已含头部旋转、显示倍率及设备 DPR
        painter.resetTransform()
        dpr = painter.device().devicePixelRatioF()
        painter.scale(1/dpr, 1/dpr)
        painter.drawImage(QPointF(left, top), image)
        painter.restore()


def draw_face_decals(renderer, painter, shape, gx, gy):
    mask = QPainterPath()
    mask.addEllipse(renderer.head_rect(shape.head_length))
    mask.addEllipse(QRectF(gx*2-10/3, 1.8-10/3, 20/3, 20/3))
    mask.setFillRule(Qt.FillRule.WindingFill)
    sx = 1-abs(gx)*.25
    bounds = mask.boundingRect()
    painter.save()
    painter.setClipPath(mask, Qt.ClipOperation.IntersectClip)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    # 面部装饰在下，额头标记在上；眼睛由公共头部绘制在两者之后
    for decal in (shape.face, shape.forehead):
        if not decal.enabled or not decal.image_path:
            continue
        image = face_image(decal.image_path)
        if image.isNull():
            continue
        width = image.width()*sx
        left = gx*2.5+decal.offset_x*sx-width/2
        source_top = decal.offset_y-image.height()/2
        if gy <= 0.:
            # 正视与低头复用原来的整图采样，避免无关的像素变化
            painter.drawImage(QRectF(left, source_top-gy*1.5, width, image.height()), image)
            continue
        # 按头部坐标而非 PNG 内的相对行号计算；不同图片和透明留白共享同一个面部曲面
        edges = [project_face_y(source_top+row, gy, bounds.top(), bounds.bottom())
                 for row in range(image.height()+1)]
        warp = FaceWarp(image, left, sx, edges)
        if isinstance(painter, QPainter):
            warp.replay(painter)
        else:
            # 复用头图的几何与像素缓存；只有姿态变化时才重采样
            painter.commands.append((None, warp))
    painter.restore()
