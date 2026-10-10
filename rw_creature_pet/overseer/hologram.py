"""镜片的局部全息遮罩，复用小图块，不对整张桌面或监视者身体做后处理"""
from functools import lru_cache
from math import ceil, floor, hypot
from random import Random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen


TILE_SIZE = 96  # 能被扫描条纹的周期 3 整除，拼接处保持连续
STRENGTH_STEPS = 32


@lru_cache(maxsize=1)
def noise_masks():
    """首次使用时生成共享图块；Qt 调色板查表转为二值遮罩，运行中平铺合成"""
    rng = Random(0xF0711E)

    def smooth_noise(cell):
        count = TILE_SIZE//cell
        grid = [[rng.random() for _ in range(count)] for _ in range(count)]
        weights = [(i % cell)/cell for i in range(TILE_SIZE)]
        weights = [f*f*(3-2*f) for f in weights]
        result = []
        for y, fy in enumerate(weights):
            upper, lower = grid[y//cell], grid[(y//cell+1) % count]
            result.extend((upper[x//cell]*(1-fx)+upper[(x//cell+1) % count]*fx)*(1-fy)
                          +(lower[x//cell]*(1-fx)+lower[(x//cell+1) % count]*fx)*fy
                          for x, fx in enumerate(weights))
        return result

    # 连续的小块缺损带少量细节，避免每个像素独立抽签形成满屏雪花
    noise = [2*(a*.8+b*.2) for a, b in zip(smooth_noise(4), smooth_noise(2))]
    indexed = []
    for phase in range(3):
        # 先把噪声及条纹量化为索引，所有完整度共用它，不逐档遍历像素
        data = bytes(round((n+(.25 if (i//TILE_SIZE+phase) % 3 == 0 else 0))*255/2.25)
                     for i, n in enumerate(noise))
        indexed.append(QImage(data, TILE_SIZE, TILE_SIZE, TILE_SIZE, QImage.Format.Format_Indexed8).copy())
    masks = []
    for level in range(STRENGTH_STEPS+1):
        strength = level/STRENGTH_STEPS
        threshold = round((.65+strength**2)*255/2.25)
        palette = [0xffffffff if i <= threshold else 0 for i in range(256)]
        phases = []
        for source in indexed:
            source.setColorTable(palette)
            phases.append(source.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))
        masks.append(tuple(phases))
    return tuple(masks)


class LensHologramRenderer:
    def __init__(self):
        self.image = None

    def draw(self, painter, lines, color, strength, tick, offset, *, density=None):
        if not lines or strength <= 0:
            return
        if density is None:
            transform = painter.deviceTransform()
            density = max(hypot(transform.m11(), transform.m12()), hypot(transform.m21(), transform.m22()))
        points = [point for a, b, _ in lines for point in (a, b)]
        left = floor((min(p.x for p in points)-1)*density)
        top = floor((min(p.y for p in points)-1)*density)
        right = ceil((max(p.x for p in points)+1)*density)
        bottom = ceil((max(p.y for p in points)+1)*density)
        width, height = right-left, bottom-top
        if self.image is None or self.image.width() != width or self.image.height() != height:
            self.image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        self.image.fill(0)
        bounds = QRectF(left/density, top/density, width/density, height/density)
        raster = QPainter(self.image)
        try:
            raster.scale(density, density)
            raster.translate(-bounds.left(), -bounds.top())
            tint = QColor(color)
            for a, b, opacity in lines:
                tint.setAlphaF(opacity)
                raster.setPen(QPen(tint, 1., Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                raster.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))

            # 噪声和水平扫描线按世界坐标取样，不跟随局部包围盒或头部转向
            x, y = offset[0] % TILE_SIZE, (offset[1]+tick*2) % TILE_SIZE
            phase = (tick//2-y) % 3
            level = min(STRENGTH_STEPS, max(0, round(strength*STRENGTH_STEPS)))
            raster.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            raster.setBrushOrigin(QPointF(-x, -y))
            raster.fillRect(bounds, QBrush(noise_masks()[level][phase]))
        finally:
            raster.end()
        painter.drawImage(bounds, self.image)
