"""监视者独立的小型显示层；没有输入窗口、命中图或自己的仿真计时器。"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QCursor, QPainter
from PySide6.QtWidgets import QWidget

from ..shared.desktop import configure_desktop_overlay
from ..shared.geometry import Vec2
from .events import OverseerEvents
from .model import Overseer
from .render import OverseerRenderer


class OverseerDesktopLayer(QWidget):
    def __init__(self, owner, config, atlas=None):
        super().__init__(owner)
        configure_desktop_overlay(self)
        self.setWindowTitle('桌宠 · 监视者显示')
        self.model = Overseer(config=config)
        self.events = OverseerEvents(self.model)
        self.renderer = OverseerRenderer(atlas)
        self.viewport = None
        self.pixel_mode = 'classic'
        self.alpha = 1.
        self._frame_key = None

    def configure(self, config, atlas, pixel_mode):
        if self.model.config.size != config.size:
            self.events.cancel()
            self.suspend()
        if config != self.model.config:
            self.events.configure(config)
        if self.renderer.atlas is not atlas:
            self.renderer = OverseerRenderer(atlas)
        self.pixel_mode = pixel_mode

    def bind(self, viewport, bounds, edges, *, reset=False):
        if reset or bounds != self.model.bounds or (self.model.active and self.model.anchor.edge not in edges):
            self.suspend()
            if reset:
                self.events.clear()
            else:
                self.events.cancel()
            if bounds != self.model.bounds:
                self.model.place(bounds, self.model.anchor)
        self.viewport = viewport

    def mouse_world(self):
        # 独立轮询；不读取 DragInputWindow、拖动开关或鼠标按键。
        p = QCursor.pos()
        return self.viewport.to_world(Vec2(p.x(), p.y()))

    def step(self, context_factory, *, puppet=None):
        if self.viewport is None or (not self.model.active and not self.events.config.enabled):
            return
        mouse = self.mouse_world() if self.model.active else None
        target = mouse if mouse is not None and self.model.bounds.contains(mouse) else None
        self.events.step(target, threat=mouse, puppet=puppet, context_factory=context_factory)

    def suspend(self):
        if self.isVisible():
            self.hide()  # 独立原生窗口移走时由合成器恢复其旧区域，不刷新人偶层。
        self._frame_key = None

    def refresh(self, alpha=1., *, allowed=True):
        if not allowed or self.viewport is None or not self.model.visible:
            changed = self.isVisible()
            self.suspend()
            return changed
        key = (self.model.revision, alpha, self.viewport, self.pixel_mode, self.renderer)
        if key == self._frame_key and self.isVisible():
            return False
        self.alpha = alpha
        v, m = self.viewport, self.model
        # 固定的保守外形窗口，留出眼部偏移/辉光/触须余量，避免逐帧更改窗口大小。
        extent = m.reach+m.filament_length+24
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
                                   pixel_mode=self.pixel_mode, raster_scale=v.physical_scale)
        finally:
            p.end()
