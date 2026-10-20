"""花瓣像素的浅曲面映射与脸盘深度遮挡，供不同生物独立配置素材和尺寸"""
from math import ceil, hypot, sqrt

from PySide6.QtGui import QColor, QImage

PALE_DISC_COLOR = '#E4E1CF'


def build_surface(texture_path, texture_scale, disc_radius, major_radius, minor_radius, height):
    # 只在首次绘制此外观时读取素材和构造几何，不给普通监视者增加初始化开销
    import numpy as np

    image = QImage(str(texture_path)).convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull():
        raise FileNotFoundError(f'Cannot load petal head image: {texture_path}')
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.width(), 4)
    ys, xs = np.nonzero(pixels[:, :, 3])
    # 每个有内容的素材像素对应曲面上的一个小四边形，保持透明缺口和二值轮廓
    corners = np.array(((0, 0), (1, 0), (1, 1), (0, 1)), dtype=np.float64)
    # 奇数边长也使用整数素材像素锚点，避免 1x 采样恰落在两行边界而把花瓣加粗
    origin = np.array((image.width(), image.height()))//2
    xy = (np.stack((xs, ys), axis=-1)[:, None, :]+corners-origin)/texture_scale
    radius = np.linalg.norm(xy, axis=-1)
    section = (radius-major_radius)/minor_radius
    z = height*np.sqrt(np.maximum(0., 1.-section*section))
    vertices = np.concatenate((xy, z[:, :, None]), axis=-1)
    indices = np.array(((0, 1, 2), (0, 2, 3)))
    petals = vertices[:, indices].reshape(-1, 3, 3)
    colors = np.repeat(pixels[ys, xs], 2, axis=0)

    extent = max(disc_radius, float(np.max(np.linalg.norm(petals, axis=-1))))
    return petals, colors.copy(), extent


def view_matrix(gaze, depth, up, *, min_facing=.25):
    """保持花纹随身体定向，用连续倾斜矩阵注视目标，正视附近不会绕视线翻转"""
    length = hypot(up.x, up.y)
    ux, uy = (up.x/length, up.y/length) if length > 1e-8 else (0., -1.)
    # 局部 x 向右，y 向下；贴图上缘朝向身体外侧
    rx, ry, dx, dy = -uy, ux, -ux, -uy
    planar = hypot(gaze.x, gaze.y)
    magnitude = hypot(planar, depth)
    facing = depth/magnitude if magnitude > 1e-8 else 1.
    facing = min_facing+(1-min_facing)*max(0., min(1., facing))
    tilt = sqrt(max(0., 1-facing*facing))
    kx, ky = ((gaze.x*rx+gaze.y*ry)/planar, (gaze.x*dx+gaze.y*dy)/planar) if planar > 1e-8 else (0., 0.)
    a, b, c = 1+(facing-1)*kx*kx, (facing-1)*kx*ky, 1+(facing-1)*ky*ky
    return (rx*a+dx*b, rx*b+dx*c, (rx*kx+dx*ky)*tilt,
            ry*a+dy*b, ry*b+dy*c, (ry*kx+dy*ky)*tilt,
            -kx*tilt, -ky*tilt, facing)


def project(surface, matrix, density, disc_radius, disc_color, petal_color=None):
    """仅扫描每片三角形的小包围盒，不遍历窗口或生成整屏网格"""
    import numpy as np

    triangles, colors, extent = surface
    # 只替换花瓣像素的 RGB，保留素材透明度；不修改共用素材或脸盘颜色
    colors = colors.copy()
    if petal_color is not None:
        colors[:, :3] = QColor(petal_color).getRgb()[:3]
    matrix = np.asarray(matrix).reshape(3, 3)
    projected = triangles @ matrix.T
    half = ceil(extent*density)+1
    side = half*2
    # 脸盘直接求投影平面的覆盖与深度，避免大三角形扩大所有花瓣的扫描步长
    yy, xx = np.indices((side, side), dtype=np.float64)
    screen = np.stack(((xx+.5-half)/density, (yy+.5-half)/density), axis=-1).reshape(-1, 2)
    local = screen @ np.linalg.inv(matrix[:2, :2]).T
    face = np.sum(local*local, axis=-1) <= disc_radius*disc_radius
    buffer = np.where(face, local @ matrix[2, :2], -np.inf)
    rgba = np.zeros((side*side, 4), dtype=np.uint8)
    rgba[face] = QColor(disc_color).getRgb()
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

