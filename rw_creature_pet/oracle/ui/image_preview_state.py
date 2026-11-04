"""外观编辑器的图片预览边界，保留非当前主体的值但不读取其资源"""
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from ..graphics.face_assets import decal_image


class ImagePreviewEditor(QWidget):
    def __init__(self, *, assets_active=True):
        super().__init__()
        self.assets_active = assets_active

    def set_assets_active(self, active):
        if self.assets_active != active:
            self.assets_active = active
            self.refresh()

    def preview_image(self, value):
        if not self.assets_active or getattr(value, 'kind', 'png') != 'png':
            return QImage()
        return decal_image(value)
