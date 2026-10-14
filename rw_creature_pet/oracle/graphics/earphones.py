"""耳机部件共用耳侧局部坐标，左右镜像，近侧覆盖头脸、远侧置后"""
from math import cos, radians
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPolygonF

from ..ear_config import EAR_PART_FIELDS
from .face_assets import face_image
from .pixel_ellipse import PixelEllipse


def ear_assets_key(shape):
    return tuple((part, face_image(part.image_path).cacheKey() if part.enabled and part.kind == 'png' else None)
                 for part in (getattr(shape, name) for name in EAR_PART_FIELDS))


def part_path(part):
    w, h = part.width/2, part.height/2
    path = QPainterPath()
    if part.kind in ('rectangle', 'line'):
        path.addRect(QRectF(-w, -h, 2*w, 2*h))
    else:
        points = ((-w*.5, -h), (w*.5, -h), (w, h), (-w, h)) if part.kind == 'trapezoid' else (
            (0, -h), (w, h), (-w, h))
        path.addPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
        path.closeSubpath()
    return path


def draw_ear(painter, colors, shape, sign, gx, gy):
    painter.save()
    painter.translate(sign*(6.-2*abs(gx)), 0.)
    # X 为离开头部的方向；倾斜角也随左右侧镜像
    stretch = 1.+.75*abs(gx)
    painter.scale(sign, cos(radians(gy*20)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    for name in EAR_PART_FIELDS:
        part = getattr(shape, name)
        if not part.enabled:
            continue
        painter.save()
        # 挂接位置继续跟随耳壳展开，只有主体的轮廓随侧视增宽
        painter.translate(part.offset_x*stretch, part.offset_y)
        if name == 'ear_body':
            painter.scale(stretch, 1.)
        painter.rotate(part.rotation)
        rect = QRectF(-part.width/2, -part.height/2, part.width, part.height)
        if part.kind == 'png':
            image = face_image(part.image_path)
            if not image.isNull():
                painter.drawImage(rect, image)
        elif part.kind == 'ellipse':
            PixelEllipse(part.width, part.height,
                         colors.head_highlight if part.tone == 'highlight' else colors.head_shell,
                         colors.head_highlight if part.tone == 'split' else None,
                         mirrored=sign < 0).draw(painter)
        else:
            path = part_path(part)
            painter.fillPath(path, QColor(colors.head_highlight if part.tone == 'highlight' else colors.head_shell))
            if part.tone == 'split':
                painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
                rect.setWidth(part.width/2)
                painter.fillRect(rect, QColor(colors.head_highlight))
        painter.restore()
    painter.restore()
