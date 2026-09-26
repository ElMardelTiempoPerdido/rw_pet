"""只使用目标自身的 alpha 轮廓，输入区域不包含装饰层或空白包围盒。"""
from math import floor

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QBitmap, QRegion


class PixelHitMap:
    def __init__(self, image, origin, density=1.):
        self.image, self.origin = image, origin
        self.density = density  # 图像像素 / 世界单位，独立于 Qt DIP。

    def contains(self, point):
        x = floor((point.x-self.origin.x)*self.density)
        y = floor((point.y-self.origin.y)*self.density)
        return (0 <= x < self.image.width() and 0 <= y < self.image.height()
                and self.image.pixelColor(x, y).alpha() >= 128)

    def region(self, scale, offset):
        """映射到 Qt DIP；不把系统 DPI 再乘一次。"""
        width = max(1, round(self.image.width()*scale/self.density))
        height = max(1, round(self.image.height()*scale/self.density))
        mask = self.image.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.FastTransformation).createAlphaMask(
                                     Qt.ImageConversionFlag.ThresholdDither)
        return QRegion(QBitmap.fromImage(mask)).translated(QPoint(
            round(offset.x+self.origin.x*scale), round(offset.y+self.origin.y*scale)))
