"""Friend 花冠的素材、尺寸与有界投影缓存"""
from functools import lru_cache

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor

from .body import DISC_RADIUS
from ....shared.paths import PACKAGE_ROOT
from ....shared import petal_head


TEXTURE_PATH = PACKAGE_ROOT/'skin/friend/friend_head_2x.png'
TEXTURE_SCALE = 2.  # 素材像素数 / 逻辑像素数，各显示倍率复用同一张图
DISC_COLOR = petal_head.PALE_DISC_COLOR  # 脸盘固定浅黄色，不随槽位身体主色变化
TORUS_MAJOR_RADIUS = 5.  # 半环面截面的中心到脸盘中心的距离
TORUS_MINOR_RADIUS = 2.  # 截面的径向半宽
TORUS_HEIGHT = 1.75  # 朝脸盘正面拱起的高度，设为 0 可对比平面贴图
MIN_FACING = .25  # 保留原圆盘侧视时的最小厚度


@lru_cache(maxsize=1)
def _surface():
    return petal_head.build_surface(TEXTURE_PATH, TEXTURE_SCALE, DISC_RADIUS,
                                    TORUS_MAJOR_RADIUS, TORUS_MINOR_RADIUS, TORUS_HEIGHT)


def view_matrix(gaze, depth, up):
    return petal_head.view_matrix(gaze, depth, up, min_facing=MIN_FACING)


@lru_cache(maxsize=128)
def _project(matrix, density, petal_color='#000000'):
    return petal_head.project(_surface(), matrix, density, DISC_RADIUS, DISC_COLOR, petal_color)


def head_image(gaze, depth, up, density, petal_color='#000000'):
    matrix = view_matrix(gaze, depth, up)
    # 千分之一的方向精度远小于一个显示像素，限制缓存条目并复用静止结果
    return _project(tuple(round(value, 3) for value in matrix), round(density, 6),
                    QColor(petal_color).name())


def draw_head(painter, model, alpha, density):
    head = model.eye_position(alpha)
    gaze, depth = model.head_gaze(alpha)
    image, half = head_image(gaze, depth, head-model.root, density, model.config.color)
    radius = half*model.segment_extension(1., alpha)
    painter.drawImage(QRectF(head.x-radius, head.y-radius, radius*2, radius*2), image)
