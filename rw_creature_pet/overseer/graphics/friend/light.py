"""朋友？观察时的短光束：缓存局部柔光图，随花冠法线投影，不推进物理"""
from functools import lru_cache
from math import atan2, ceil, degrees, hypot, radians, tan

OBSERVATION_DURATION = (8., 16.)  # 朋友？单次观察时长，秒，含展开过程
BEAM_LENGTH = 60.0  # 最外层光束的逻辑长度，实际投影随头部倾角缩短
BEAM_HALF_ANGLE = 28.0  # 柔光半角，度
RAY_HALF_ANGLE = 15.0  # 像素光线锥面的半角，度
SPARK_HALF_ANGLE = 30.0  # 光点分布锥面的半角，度
BEAM_ROOT_RADIUS = 3.0  # 光束起点半宽
BEAM_BACK_LENGTH = 3.0  # 起点向后柔和收口的距离
GLOW_RADIUS = 12.0  # 观察时额外光晕，常驻紫色微光仍由 render 绘制
LIGHT_OPACITY = 1.0  # 整体强度，乘以下面各层的透明度
# 长度比例、颜色、透明度；桌面没有原作的地形遮罩，外层提亮以免在浅色背景上形成暗影
BEAM_LAYERS = ((1., '#bdd6ee', .85), (.8, '#ffe1a6', .85), (.6, '#ffffff', .85))
GLOW_LAYERS = ((1., '#ffe1a6', .3), (.6, '#ffffff', .3))


def light_extent():
    """用于局部画布和桌面窗口的保守半径，修改光束尺寸时同步更新"""
    from .pixels import pixel_extent
    width = BEAM_ROOT_RADIUS+tan(radians(BEAM_HALF_ANGLE))*BEAM_LENGTH
    return ceil(max(hypot(BEAM_LENGTH+1, width+1), GLOW_RADIUS+1,
                    pixel_extent(BEAM_LENGTH, BEAM_ROOT_RADIUS,
                                 ray_half_angle=RAY_HALF_ANGLE,
                                 spark_half_angle=SPARK_HALF_ANGLE)))


@lru_cache(maxsize=8)
def light_images(density):
    # 仅首次使用某个像素密度时计算，转头和淡入淡出不重建光图
    import numpy as np
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage

    def canvas(left, top, right, bottom):
        left, top = int(left*density)-1, int(top*density)-1
        right, bottom = ceil(right*density)+1, ceil(bottom*density)+1
        yy, xx = np.indices((bottom-top, right-left), dtype=np.float32)
        rgba = np.zeros((*xx.shape, 4), dtype=np.float32)
        return rgba, (xx+left+.5)/density, (yy+top+.5)/density, QRectF(
            left/density, top/density, (right-left)/density, (bottom-top)/density)

    def over(rgba, color, opacity):
        # 和原版 FlatLight 相同，使用普通 Alpha 混合
        rgb = np.array(QColor(color).getRgbF()[:3], dtype=np.float32)
        rgba *= (1-opacity)[:, :, None]
        rgba[:, :, :3] += opacity[:, :, None]*rgb
        rgba[:, :, 3] += opacity

    def image(rgba):
        pixels = np.round(np.clip(rgba, 0., 1.)*255).astype(np.uint8)
        height, width = pixels.shape[:2]
        return QImage(pixels.data, width, height, width*4,
                      QImage.Format.Format_RGBA8888_Premultiplied).copy()

    slope = tan(radians(BEAM_HALF_ANGLE))
    radius = BEAM_ROOT_RADIUS+slope*BEAM_LENGTH
    beam, x, y, beam_rect = canvas(-BEAM_BACK_LENGTH, -radius, BEAM_LENGTH, radius)
    width = BEAM_ROOT_RADIUS+slope*np.maximum(0., x)
    cross = np.maximum(0., 1-(y/width)**2)**3.5
    back = np.clip((x+BEAM_BACK_LENGTH)/BEAM_BACK_LENGTH, 0., 1.)
    for length, color, opacity in BEAM_LAYERS:
        along = np.clip(x/(BEAM_LENGTH*length), 0., 1.)
        fade = np.maximum(0., 1-(.2+.8*along)**2)**3.5
        over(beam, color, cross*back*fade*opacity)
    glow, x, y, glow_rect = canvas(-GLOW_RADIUS, -GLOW_RADIUS, GLOW_RADIUS, GLOW_RADIUS)
    for radius, color, opacity in GLOW_LAYERS:
        falloff = np.maximum(0., 1-(x*x+y*y)/(GLOW_RADIUS*radius)**2)**3.5
        over(glow, color, falloff*opacity)
    return image(beam), beam_rect, image(glow), glow_rect


def draw_light(painter, model, alpha, density):
    from .head import view_matrix

    extension = model.extension(alpha)
    strength = max(0., min(extension, model.lens.opening(alpha), 1.))
    if strength <= 0 or LIGHT_OPACITY <= 0:
        return
    head = model.eye_position(alpha)
    gaze, depth = model.head_gaze(alpha)
    # 使用花冠投影后的真实法线，包括 MIN_FACING 的侧视厚度修正
    matrix = view_matrix(gaze, depth, head-model.root)
    dx, dy = matrix[2], matrix[5]
    planar = hypot(dx, dy)
    beam, beam_rect, glow, glow_rect = light_images(density)
    opacity = painter.opacity()*min(1., LIGHT_OPACITY)*strength*strength*(3-2*strength)
    painter.save()
    try:
        painter.translate(head.x, head.y)
        painter.scale(extension, extension)
        painter.setOpacity(opacity)
        painter.drawImage(glow_rect, glow)
        if planar > 1e-6:
            # 正视时只留下局部光晕，避免归一化近零方向导致光束突然换边
            painter.setOpacity(opacity*planar)
            painter.rotate(degrees(atan2(dy, dx)))
            painter.scale(planar, 1.)
            painter.drawImage(beam_rect, beam)
    finally:
        painter.restore()


def draw_pixels(painter, model, alpha, hologram):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QPainter
    from .head import view_matrix
    from .pixels import PIXEL_COLOR, PIXEL_OPACITY, SPARK_FRAMES

    state = model.friend_light_pixels
    extension = model.extension(alpha)
    strength = max(0., min(extension, model.lens.opening(alpha), 1.))
    if state is None or not state.active or strength <= 0:
        return
    head = model.eye_position(alpha)
    gaze, depth = model.head_gaze(alpha)
    matrix = view_matrix(gaze, depth, head-model.root)
    lines, sparks = state.project(head, matrix, extension, BEAM_LENGTH, BEAM_ROOT_RADIUS, alpha,
                                  ray_half_angle=RAY_HALF_ANGLE,
                                  spark_half_angle=SPARK_HALF_ANGLE)
    lines = tuple(line for line, show in zip(lines, state.line_show) if show < strength)
    painter.save()
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        # 按 1 逻辑像素栅格绘制并最近邻放大，adaptive 模式下也保留像素阶梯
        # 持续观察时也保留较弱的局部缺损，不额外丢弃整条线或降低存留像素的亮度
        hologram.draw(painter, lines, QColor(PIXEL_COLOR), strength*state.signal_strength(alpha), state.tick,
                      state.noise_offset, density=1.)
        color = QColor(PIXEL_COLOR)
        color.setAlphaF(PIXEL_OPACITY*strength*strength*(3-2*strength))
        for center, frame in sparks:
            x, y = round(center.x), round(center.y)
            for dx, dy in SPARK_FRAMES[frame]:
                painter.fillRect(QRectF(x+dx, y+dy, 1., 1.), color)
    finally:
        painter.restore()
