"""监视者独立的小型显示层；没有输入窗口、命中图或自己的仿真计时器。"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QCursor, QPainter
from PySide6.QtWidgets import QWidget

from ..shared.desktop import configure_desktop_overlay
from ..shared.geometry import Vec2
from .render import OverseerRenderer
from .group import OverseerGroup


class OverseerDesktopLayer(QWidget):
    def __init__(self, owner, entry, atlas=None):
        super().__init__(owner)
        configure_desktop_overlay(self)
        self.setWindowTitle('桌宠 - 监视者显示')
        self.model, self.events = entry.model, entry.events
        self.renderer = OverseerRenderer(atlas)
        self.viewport = None
        self.pixel_mode = 'classic'
        self.coarse_pixels_4x = False
        self.alpha = 1.
        self._frame_key = None

    def configure(self, atlas, pixel_mode, coarse_pixels_4x=False):
        if self.renderer.atlas is not atlas:
            self.renderer = OverseerRenderer(atlas)
        self.pixel_mode = pixel_mode
        self.coarse_pixels_4x = coarse_pixels_4x

    def bind(self, viewport):
        self.viewport = viewport

    def suspend(self):
        if self.isVisible():
            self.hide()  # 独立原生窗口移走时由合成器恢复其旧区域，不刷新人偶层。
        self._frame_key = None

    def refresh(self, alpha=1., *, allowed=True):
        if not allowed or self.viewport is None or not self.model.visible:
            changed = self.isVisible()
            self.suspend()
            return changed
        key = (self.model.revision, alpha, self.viewport, self.pixel_mode, self.coarse_pixels_4x, self.renderer)
        if key == self._frame_key and self.isVisible():
            return False
        self.alpha = alpha
        v, m = self.viewport, self.model
        # 固定的保守外形窗口，留出眼部偏移/辉光/触须余量，避免逐帧更改窗口大小。
        extent = m.reach+m.head_extra_extent+max(m.filament_length+24, m.observation_extent+4)
        center = v.to_global(m.root)
        workarea = QRectF(v.x, v.y, v.width, v.height).toAlignedRect()
        rect = QRectF(center.x-extent*v.scale, center.y-extent*v.scale,
                      2*extent*v.scale, 2*extent*v.scale).toAlignedRect().intersected(workarea)
        if rect.isEmpty():
            self.suspend()
            return False
        if self.geometry() != rect:
            self.setGeometry(rect)
        self._frame_key = key
        if not self.isVisible():
            self.show()
        self.update()
        return True

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(self.rect(), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            if self.viewport is not None:
                v = self.viewport
                p.translate(v.x-self.x(), v.y-self.y())
                p.scale(v.scale, v.scale)
                self.renderer.draw(p, self.model, self.alpha,
                                   pixel_mode=self.pixel_mode, raster_scale=v.requested_scale,
                                   coarse_pixels_4x=self.coarse_pixels_4x)
        finally:
            p.end()


class OverseerDesktopGroup:
    """每个槽位一个局部窗口，统一读取鼠标和推进时钟"""
    def __init__(self, owner, config, atlas=None):
        self.owner = owner
        self.group = OverseerGroup(config)
        self.layers = {}
        self.viewport = None
        self.configure(config, atlas, 'classic')

    def configure(self, config, atlas, pixel_mode, coarse_pixels_4x=False):
        self.group.configure(config)
        for key in set(self.layers)-self.group.entries.keys():
            layer = self.layers.pop(key)
            layer.close()
            layer.deleteLater()
        for key, entry in self.group.entries.items():
            if key not in self.layers:
                self.layers[key] = OverseerDesktopLayer(self.owner, entry, atlas)
            self.layers[key].configure(atlas, pixel_mode, coarse_pixels_4x)

    def bind(self, viewport, bounds, edges, *, reset=False):
        self.viewport = viewport
        self.group.bind(bounds, edges, reset=reset)
        for layer in self.layers.values():
            layer.bind(viewport)

    def mouse_world(self):
        p = QCursor.pos()
        return self.viewport.to_world(Vec2(p.x(), p.y()))

    def step(self, context_factory, *, puppet=None):
        if self.viewport is None:
            return
        mouse = self.mouse_world() if self.group.active else None
        target = mouse if mouse is not None and self.group.bounds.contains(mouse) else None
        def context():
            nonlocal mouse
            if mouse is None:
                mouse = self.mouse_world()
            return context_factory(mouse)
        self.group.step(target, threat=mouse, puppet=puppet, context_factory=context)

    def refresh(self, alpha=1., *, allowed=True):
        changed = False
        for layer in self.layers.values():
            changed |= layer.refresh(alpha, allowed=allowed)
        return changed

    def suspend(self):
        for layer in self.layers.values():
            layer.suspend()

    def close(self):
        for layer in self.layers.values():
            layer.close()
