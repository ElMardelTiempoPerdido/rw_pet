"""局部像素画布：曲线网格、眼部与触须；绘制不推进仿真。"""
from math import atan2, ceil, degrees, floor, hypot, pi, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPen, QPolygonF, QRadialGradient

from .model import clamp, perpendicular, unit
from ..shared.geometry import Vec2


def point(value):
    return QPointF(value.x, value.y)


def mixed(a, b, amount):
    a, b = QColor(a), QColor(b)
    return QColor.fromRgbF(*(a.getRgbF()[i]*(1-amount)+b.getRgbF()[i]*amount for i in range(4)))


class OverseerRenderer:
    def __init__(self, atlas=None):
        self.atlas = atlas
        self._key = self.image = self.target = None

    def sprite(self, painter, name, center, width, height, color, rotation=0):
        painter.save()
        painter.translate(center.x, center.y)
        painter.rotate(rotation)
        rect = QRectF(-width/2, -height/2, width, height)
        if self.atlas is not None:
            painter.drawImage(rect, self.atlas.sprite(name, QColor(color).name()))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            if name == 'pixel':
                painter.drawRect(rect)
            else:
                painter.drawEllipse(rect)
        painter.restore()

    def draw(self, painter, model, alpha=1., *, pixel_mode='classic', raster_scale=None, guides=False):
        if not model.active:
            return
        alpha = clamp(alpha, 0., 1.)
        if model.extension(alpha) <= 0:
            if guides:
                self.draw_guides(painter, model, alpha)
            return
        if raster_scale is None:
            transform = painter.deviceTransform()
            raster_scale = max(hypot(transform.m11(), transform.m12()), hypot(transform.m21(), transform.m22()))
        density = 1. if pixel_mode == 'classic' else round(clamp(raster_scale, 1., 4.), 6)
        key = (model, model.revision, alpha, density)
        if key != self._key:
            bounds = model.visual_bounds(alpha)
            left, top = floor(bounds.left*density), floor(bounds.top*density)
            right, bottom = ceil(bounds.right*density), ceil(bounds.bottom*density)
            self.target = QRectF(left/density, top/density, (right-left)/density, (bottom-top)/density)
            self.image = QImage(right-left, bottom-top, QImage.Format.Format_ARGB32_Premultiplied)
            self.image.fill(0)
            raster = QPainter(self.image)
            try:
                raster.scale(density, density)
                raster.translate(-left/density, -top/density)
                # 只向活动面内绘制，根部在边缘收口，触须和柔光不会越过边框。
                b = model.bounds
                raster.setClipRect(QRectF(b.left, b.top, b.right-b.left, b.bottom-b.top))
                self._draw(raster, model, alpha)
            finally:
                raster.end()
            self._key = key
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(self.target, self.image)
        painter.restore()
        if guides:
            self.draw_guides(painter, model, alpha)

    def _draw(self, painter, model, alpha):
        color = model.config.color
        extension = model.extension(alpha)
        head = model.eye_position(alpha)
        gaze, depth = model.gaze(alpha)
        gradient = QRadialGradient(point(head), 11)
        inner = QColor(color)
        inner.setAlpha(round(45*extension))
        outer = QColor(color)
        outer.setAlpha(0)
        gradient.setColorAt(0, inner)
        gradient.setColorAt(1, outer)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(point(head), 11, 11)

        # 后排触须在身体后面，前排绕在身体前面，眼球覆盖连接处。
        self._filaments(painter, model, alpha, (0, 2), color)
        centers = [model.stem(i/10, alpha) for i in range(11)]
        length = sum((b-a).length() for a, b in zip(centers, centers[1:]))
        exponent = 1.75-1.4*clamp((length-20*model.config.size)/(70*model.config.size), 0., 1.)
        sections = []
        for i, center in enumerate(centers):
            direction = unit(centers[min(10, i+1)]-centers[max(0, i-1)], model.normal)
            normal = perpendicular(direction)
            fraction = i/10
            segment = model.segment_extension(fraction, alpha)
            wall_radius = 1+sin(fraction*pi)
            full_radius = max(.45, 5*(1-(1-fraction)**exponent))
            radius = wall_radius+(full_radius-wall_radius)*segment
            sections.append((center-normal*radius, center+normal*radius))
        for i, ((a, b), (c, d)) in enumerate(zip(sections, sections[1:])):
            painter.setBrush(mixed('#546969', color, .25+.65*i/9))
            painter.drawPolygon(QPolygonF([point(a), point(b), point(d), point(c)]))
        self._filaments(painter, model, alpha, (1, 3), color)
        rotation = degrees(atan2(gaze.y, gaze.x))-90 if gaze.length() > 1e-6 else 0.
        diameter = 2*(1+4*model.segment_extension(1., alpha))
        eye_width, eye_height = diameter*.7*extension, diameter*(.35+.35*depth)*extension
        self.sprite(painter, 'Circle20', head, diameter, diameter*(1.2-.2*depth), color, rotation)
        self.sprite(painter, 'Circle20', head+gaze*(4*extension), eye_width, eye_height,
                    mixed(color, '#2745ad', .5), rotation)
        self.sprite(painter, 'Circle20', head+gaze*(2.5*extension), eye_width*.75, eye_height*.75,
                    mixed(color, '#e8fff7', .7), rotation)
        pupil = head+gaze*(2*extension)+unit(gaze)*sin(gaze.length()*pi)*2
        self.sprite(painter, 'pixel', pupil, 1.5*extension, 1.5*extension, '#193e38')

    def _filaments(self, painter, model, alpha, indices, color):
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # OverseerGraphics.colorMyceliaFrom：体型 0.5～1 对应从长度 50%～30% 开始渐变。
        gradient_start = .5-.4*(model.config.size-.5)
        root_color = mixed('#416c68', color, .45)
        dark_teal = QColor.fromHslF(22/45, .5, .2)
        for index in indices:
            strand = model.filaments[index]
            colors = [mixed(root_color, dark_teal, clamp((i/(len(strand)-1)-gradient_start)/(1-gradient_start), 0., 1.))
                      for i in range(len(strand))]
            # Mycelium.UpdateColor 把末端两个顶点覆盖为纯蓝；最后一段由深青过渡到蓝色。
            colors[-1] = QColor('#0000ff')
            for i, (a, b) in enumerate(zip(strand, strand[1:])):
                start, end = point(a.sample(alpha)), point(b.sample(alpha))
                gradient = QLinearGradient(start, end)
                gradient.setColorAt(0, colors[i])
                gradient.setColorAt(1, colors[i+1])
                pen = QPen(QBrush(gradient), .85,
                           Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(start, end)
        painter.setPen(Qt.PenStyle.NoPen)

    @staticmethod
    def draw_guides(painter, model, alpha):
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor('#b49ce0'), 1, Qt.PenStyle.DotLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawEllipse(point(model.root), model.reach, model.reach)
        pen.setColor(QColor('#e6a578'))
        painter.setPen(pen)
        painter.drawEllipse(point(model.root), model.config.withdraw_distance, model.config.withdraw_distance)
        pen.setColor(QColor('#73bcaf'))
        painter.setPen(pen)
        painter.drawEllipse(point(model.root), model.config.reemerge_distance, model.config.reemerge_distance)
        painter.drawLine(point(model.eye_position(alpha)), point(model.previous_look.lerp(model.look_at, alpha)))
        for p, color in ((model.root, '#ffcf80'), (model.hover, '#839ce7'),
                         (model.eye_position(alpha), '#a3ffdd')):
            pen.setColor(QColor(color))
            pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawLine(point(p-Vec2(3, 0)), point(p+Vec2(3, 0)))
            painter.drawLine(point(p-Vec2(0, 3)), point(p+Vec2(0, 3)))
        painter.restore()
