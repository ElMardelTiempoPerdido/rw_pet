"""单张像素花瓣贴图映射到浅半环面，局部深度缓冲处理花瓣与脸盘的遮挡"""
from functools import lru_cache
from math import ceil, hypot, sqrt
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage

from .friend import DISC_RADIUS


TEXTURE_PATH = Path(__file__).resolve().parents[1]/'skin/friend/friend_head_2x.png'
TEXTURE_SCALE = 2.  # 素材像素数 / 逻辑像素数，各显示倍率复用同一张图
DISC_COLOR = '#E4E1CF'  # 脸盘固定浅黄色，不随槽位身体主色变化
TORUS_MAJOR_RADIUS = 5.  # 半环面截面的中心到脸盘中心的距离
TORUS_MINOR_RADIUS = 2.  # 截面的径向半宽
TORUS_HEIGHT = 1.75  # 朝脸盘正面拱起的高度，设为 0 可对比平面贴图
MIN_FACING = .25  # 保留原圆盘侧视时的最小厚度


@lru_cache(maxsize=1)
def _surface():
    # 只在首次绘制此外观时读取素材和构造几何，不给普通监视者增加初始化开销
    import numpy as np

    image = QImage(str(TEXTURE_PATH)).convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull():
        raise FileNotFoundError(f'Cannot load friend head image: {TEXTURE_PATH}')
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.width(), 4)
    ys, xs = np.nonzero(pixels[:, :, 3])
    # 每个有内容的素材像素对应曲面上的一个小四边形，保持透明缺口和二值轮廓
    corners = np.array(((0, 0), (1, 0), (1, 1), (0, 1)), dtype=np.float64)
    xy = (np.stack((xs, ys), axis=-1)[:, None, :]+corners-
          np.array((image.width(), image.height()))*.5)/TEXTURE_SCALE
    radius = np.linalg.norm(xy, axis=-1)
    section = (radius-TORUS_MAJOR_RADIUS)/TORUS_MINOR_RADIUS
    z = TORUS_HEIGHT*np.sqrt(np.maximum(0., 1.-section*section))
    vertices = np.concatenate((xy, z[:, :, None]), axis=-1)
    indices = np.array(((0, 1, 2), (0, 2, 3)))
    petals = vertices[:, indices].reshape(-1, 3, 3)
    colors = np.repeat(pixels[ys, xs], 2, axis=0)

    extent = max(DISC_RADIUS, float(np.max(np.linalg.norm(petals, axis=-1))))
    return petals, colors.copy(), extent


def view_matrix(gaze, depth, up):
    """保持花纹随身体定向，用连续倾斜矩阵注视目标，正视附近不会绕视线翻转"""
    length = hypot(up.x, up.y)
    ux, uy = (up.x/length, up.y/length) if length > 1e-8 else (0., -1.)
    # 局部 x 向右，y 向下；贴图上缘朝向身体外侧
    rx, ry, dx, dy = -uy, ux, -ux, -uy
    planar = hypot(gaze.x, gaze.y)
    magnitude = hypot(planar, depth)
    facing = depth/magnitude if magnitude > 1e-8 else 1.
    facing = MIN_FACING+(1-MIN_FACING)*max(0., min(1., facing))
    tilt = sqrt(max(0., 1-facing*facing))
    kx, ky = ((gaze.x*rx+gaze.y*ry)/planar, (gaze.x*dx+gaze.y*dy)/planar) if planar > 1e-8 else (0., 0.)
    a, b, c = 1+(facing-1)*kx*kx, (facing-1)*kx*ky, 1+(facing-1)*ky*ky
    return (rx*a+dx*b, rx*b+dx*c, (rx*kx+dx*ky)*tilt,
            ry*a+dy*b, ry*b+dy*c, (ry*kx+dy*ky)*tilt,
            -kx*tilt, -ky*tilt, facing)


@lru_cache(maxsize=128)
def _project(matrix, density):
    """仅扫描每片三角形的小包围盒，不遍历窗口或生成整屏网格"""
    import numpy as np

    triangles, colors, extent = _surface()
    matrix = np.asarray(matrix).reshape(3, 3)
    projected = triangles @ matrix.T
    half = ceil(extent*density)+1
    side = half*2
    # 脸盘直接求投影平面的覆盖与深度，避免大三角形扩大所有花瓣的扫描步长
    yy, xx = np.indices((side, side), dtype=np.float64)
    screen = np.stack(((xx+.5-half)/density, (yy+.5-half)/density), axis=-1).reshape(-1, 2)
    local = screen @ np.linalg.inv(matrix[:2, :2]).T
    face = np.sum(local*local, axis=-1) <= DISC_RADIUS*DISC_RADIUS
    buffer = np.where(face, local @ matrix[2, :2], -np.inf)
    rgba = np.zeros((side*side, 4), dtype=np.uint8)
    rgba[face] = QColor(DISC_COLOR).getRgb()
    xy = projected[:, :, :2]*density+half
    # 三角形包围盒内的像素中心，批量计算覆盖与深度
    low = np.maximum(0, np.ceil(np.min(xy, axis=1)-.5).astype(np.int32))
    high = np.minimum(side-1, np.floor(np.max(xy, axis=1)-.5).astype(np.int32))
    span = np.maximum(0, high-low+1)
    width, height = np.max(span, axis=0)
    offsets = np.stack(np.meshgrid(np.arange(width), np.arange(height)), axis=-1).reshape(-1, 2)
    candidates = low[:, None, :]+offsets
    p = candidates+.5
    a, b, c = xy[:, 0, None], xy[:, 1, None], xy[:, 2, None]
    ab, ac, ap = b-a, c-a, p-a
    denominator = ab[:, :, 0]*ac[:, :, 1]-ab[:, :, 1]*ac[:, :, 0]
    nonzero = np.abs(denominator) > 1e-9
    safe = np.where(nonzero, denominator, 1.)
    u = (ap[:, :, 0]*ac[:, :, 1]-ap[:, :, 1]*ac[:, :, 0])/safe
    v = (ab[:, :, 0]*ap[:, :, 1]-ab[:, :, 1]*ap[:, :, 0])/safe
    covered = (nonzero & (u >= -1e-8) & (v >= -1e-8) & (u+v <= 1+1e-8) &
               np.all(candidates <= high[:, None, :], axis=-1))
    triangle, candidate = np.nonzero(covered)
    locations = candidates[triangle, candidate]
    index = locations[:, 1]*side+locations[:, 0]
    z = projected[:, 0, 2, None]+u*(projected[:, 1, 2]-projected[:, 0, 2])[:, None]+v*(projected[:, 2, 2]-projected[:, 0, 2])[:, None]
    depths = z[triangle, candidate]
    np.maximum.at(buffer, index, depths)
    nearest = depths >= buffer[index]-1e-9
    rgba[index[nearest]] = colors[triangle[nearest]]
    # QImage 拥有自己的存储，缓存不引用临时 NumPy 数组
    image = QImage(rgba.data, side, side, side*4, QImage.Format.Format_RGBA8888).copy()
    return image, half/density


def head_image(gaze, depth, up, density):
    matrix = view_matrix(gaze, depth, up)
    # 千分之一的方向精度远小于一个显示像素，限制缓存条目并复用静止结果
    return _project(tuple(round(value, 3) for value in matrix), round(density, 6))


def draw_head(painter, model, alpha, density):
    head = model.eye_position(alpha)
    gaze, depth = model.head_gaze(alpha)
    image, half = head_image(gaze, depth, head-model.root, density)
    radius = half*model.segment_extension(1., alpha)
    painter.drawImage(QRectF(head.x-radius, head.y-radius, radius*2, radius*2), image)
