"""只使用目标自身的 alpha 轮廓，输入区域不包含装饰层或空白包围盒。"""
from math import floor

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QBitmap, QRegion


class PixelHitMap:
    def __init__(self, image, origin):
        self.image, self.origin = image, origin

    def contains(self, point):
        x, y = floor(point.x-self.origin.x), floor(point.y-self.origin.y)
        return (0 <= x < self.image.width() and 0 <= y < self.image.height()
                and self.image.pixelColor(x, y).alpha() >= 128)

    def region(self, scale, offset):
        """映射到 Qt DIP；不把系统 DPI 再乘一次。"""
        width = max(1, round(self.image.width()*scale))
        height = max(1, round(self.image.height()*scale))
        mask = self.image.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.FastTransformation).createAlphaMask(
                                     Qt.ImageConversionFlag.ThresholdDither)
        return QRegion(QBitmap.fromImage(mask)).translated(QPoint(
            round(offset.x+self.origin.x*scale), round(offset.y+self.origin.y*scale)))
