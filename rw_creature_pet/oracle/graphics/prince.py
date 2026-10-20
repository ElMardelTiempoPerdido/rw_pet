"""Prince 的固定花冠头部与无双臂身体入口

后续 Rot Prince 的头部、躯干与装饰在这里添加，不读取 CustomAppearance
"""
from dataclasses import dataclass
from functools import lru_cache
from math import atan2, cos, degrees, hypot, radians, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen

from ...shared.geometry import Vec2
from ...shared.paths import PACKAGE_ROOT
from ...shared import petal_head
from ..motion.prince_robe import CHEST_WIDTH, CHEST_HEIGHT
from ..prince_assets import robe_layout
from .raster import painter_scale


TEXTURE_PATH = PACKAGE_ROOT/'skin/prince/prince_head_petals.png'
TEXTURE_SCALE = 1.  # 素材以 1x 绘制，不按 Friend 的 2x 素材缩小
DISC_RADIUS = 4.3
DISC_COLOR = petal_head.PALE_DISC_COLOR  # 与 Friend 相同的固定浅黄色，仅影响脸盘
TORUS_MAJOR_RADIUS = 4.5
TORUS_MINOR_RADIUS = 3.5
TORUS_HEIGHT = 1.5
HEAD_GAZE_NEAR_FRACTION = .25  # 注视强度的近段，0～1；这里不是 Friend 的工作区距离
HEAD_GAZE_NEAR_ANGLE = 12.  # 近段末尾的轻微转角
HEAD_GAZE_POWER = 2.  # 中段转动放缓，避免过早接近极端朝向
HEAD_GAZE_MAX_YAW = 70.  # 曲面投影前的横向最大转角
HEAD_GAZE_MAX_PITCH = 60.  # 仰俯稍收紧，保留更完整的脸盘


def head_tilt_angle(span, maximum):
    """沿用 Friend 的两段连续响应；Oracle 注视已在场景中限幅和平滑"""
    maximum = max(0., min(89., maximum))
    near = max(0., min(.95, HEAD_GAZE_NEAR_FRACTION))
    angle = min(maximum, max(0., HEAD_GAZE_NEAR_ANGLE)) if near > 0 else 0.
    if near > 0 and span < near:
        progress = max(0., span)/near
        return radians(angle*progress*(2-progress))
    progress = max(0., min(1., (span-near)/(1.-near)))
    return radians(angle+(maximum-angle)*progress**max(1., HEAD_GAZE_POWER))


def head_view_gaze(gx, gy):
    length = hypot(gx, gy)
    if length < 1e-9:
        return Vec2(), 1.
    # 两轴不累加偏转强度，斜向不会比同幅度的单轴更早转满
    span = max(abs(gx), abs(gy))
    vertical = (gy/length)**2
    maximum = HEAD_GAZE_MAX_YAW*(1.-vertical)+HEAD_GAZE_MAX_PITCH*vertical
    angle = head_tilt_angle(span, maximum)
    # Oracle 的 gy 正值表示抬头，曲面局部 y 向下
    return Vec2(gx, -gy)*(sin(angle)/length), cos(angle)


@lru_cache(maxsize=1)
def _surface():
    return petal_head.build_surface(TEXTURE_PATH, TEXTURE_SCALE, DISC_RADIUS,
                                    TORUS_MAJOR_RADIUS, TORUS_MINOR_RADIUS, TORUS_HEIGHT)


@lru_cache(maxsize=128)
def _project(matrix, density):
    # 保留 PNG 自身的颜色和透明像素，脸盘与花瓣之间由深度缓冲决定遮挡
    return petal_head.project(_surface(), matrix, density, DISC_RADIUS, DISC_COLOR)


def head_image(gx, gy, density):
    gaze, depth = head_view_gaze(gx, gy)
    matrix = petal_head.view_matrix(gaze, depth, Vec2(0., -1.))
    return _project(tuple(round(value, 3) for value in matrix), round(density, 6))


@dataclass(frozen=True)
class PetalHead:
    gx: float
    gy: float

    def replay(self, painter):
        # 在头部像素画布重放时读取真正密度，兼容 3x/4x 的基础像素档位
        image, half = head_image(self.gx, self.gy, painter_scale(painter))
        painter.drawImage(QRectF(-half, -half, half*2, half*2), image)


def draw_head(renderer, painter, gx, gy, openness=0., **kwargs):
    command = PetalHead(gx, gy)
    if hasattr(painter, 'draw_deferred'):
        painter.draw_deferred(command)
    else:
        command.replay(painter)


def draw_body(renderer, painter, scene, alpha, upper, lower, direction, head, look, **kwargs):
    frame = scene.prince_posture.frame(upper, direction, alpha)
    root, c1, c2, end = frame.neck_controls(head)
    point = lambda p: QPointF(p.x, p.y)
    neck = QPainterPath(point(root))
    neck.cubicTo(point(c1), point(c2), point(end))
    painter.setPen(QPen(QColor(renderer.colors.skin), 3., Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(neck)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(renderer.colors.skin))
    # 下半身由双层衣料完整替代，不再在镂空处绘制旧腿部或宽腰轮廓
    painter.save()
    painter.translate(frame.chest.x, frame.chest.y)
    painter.rotate(degrees(atan2(frame.chest_direction.x, -frame.chest_direction.y)))
    painter.drawEllipse(QRectF(-CHEST_WIDTH/2, -CHEST_HEIGHT, CHEST_WIDTH, CHEST_HEIGHT*2))
    painter.restore()
    opening, _, gown = renderer.draw_gown(painter, scene, alpha, hem_color=robe_layout().color)
    return opening, gown
