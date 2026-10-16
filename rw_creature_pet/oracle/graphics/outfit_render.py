"""附加外观的锚点与绘制槽位，复用人偶现有姿态，不推进物理"""
from dataclasses import dataclass, field
from math import atan2, degrees

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from ...shared.geometry import Vec2
from ..scene import unit
from .appearance import rotate
from .glow import GlowLayer
from .outfit_definition import Anchor, Clip, Sampling, Slot, outfit_definition
from .outfits import component_layers
from .raster import aligned_sprite, attached_sprite_rect, painter_density, stable_pixel_angle


@dataclass
class OutfitSprite:
    key: tuple | None = None
    image: QImage | None = None
    target: QRectF | None = None
    glow: GlowLayer = field(default_factory=GlowLayer)


class OutfitRenderer:
    """供 OracleRenderer 使用的公共附件入口，部件名称不参与绘制分支"""

    def init_outfit_renderer(self):
        self._outfit_definition = None
        self._outfit_sprites = {}
        self._front_outfit_layers = ()
        self._clothing_geometry_key = None

    def draw_head_outfit(self, painter, definition, slot, density, crown_y):
        for component in definition.at(slot):
            for image, rect in component_layers(component, density, anchor_y=crown_y):
                painter.drawImage(rect, image)

    def body_collar_axis(self, upper, direction, head):
        # 领口投影到身体中轴，转头不使肩部附件整体横移
        delta = self.inner_collar(upper, direction, head)-upper
        return upper+direction*(delta.x*direction.x+delta.y*direction.y), direction

    def draw_outfit_components(self, painter, definition, components, density, frames,
                               *, mask=None, offset=Vec2()):
        if definition != self._outfit_definition:
            # 只保留当前套装的旋转图，避免切换套装后积累不再使用的缓存
            self._outfit_sprites.clear()
            self._outfit_definition = definition
        aligned = []
        for component in components:
            origin, angle = frames[component.anchor]
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            if component.clip == Clip.CLOTHING:
                painter.setClipPath(mask, Qt.ClipOperation.IntersectClip)
            if component.sampling == Sampling.LOCAL:
                painter.translate(origin.x, origin.y)
                painter.rotate(angle)
                for image, rect in component_layers(component, density):
                    painter.drawImage(rect, image)
            else:
                angle = stable_pixel_angle(angle)
                for index, (texture, rect) in enumerate(component_layers(component, density)):
                    sprite_id = component.id, index
                    sprite = self._outfit_sprites.get(sprite_id)
                    if sprite is None:
                        sprite = self._outfit_sprites[sprite_id] = OutfitSprite()
                    key = (component, texture.cacheKey(), density, rect.getRect(), angle)
                    if key != sprite.key:
                        sprite.image = aligned_sprite(texture, rect, density, angle)
                        sprite.key = key
                    # 缓存身体含局部平移，只在最终世界网格量化一次
                    sprite.target = attached_sprite_rect(sprite.image, origin+offset, density)
                    sprite.target.translate(-offset.x, -offset.y)
                    painter.drawImage(sprite.target, sprite.image)
                    aligned.append(sprite)
            painter.restore()
        return tuple(aligned)

    def draw_body_outfit(self, painter, scene, alpha, upper, lower, direction, head,
                         opening, gown, density, slot, *, offset=Vec2(), cache_key=None):
        definition = outfit_definition(scene.config.outfit, scene.config.outfit_settings)
        components = definition.at(slot)
        if not components:
            return
        frames, mask = {}, None
        anchors = {component.anchor for component in components}
        if Anchor.GOWN_COLLAR in anchors or any(c.clip == Clip.CLOTHING for c in components):
            if cache_key is None or cache_key is not self._clothing_geometry_key:
                self._clothing_geometry = self.clothing_geometry(
                    scene, alpha, upper-offset, lower-offset, direction, head-offset, opening, gown, offset)
                self._clothing_geometry_key = cache_key
            mask, origin, angle = self._clothing_geometry
            frames[Anchor.GOWN_COLLAR] = origin, angle
        if Anchor.BODY_COLLAR in anchors:
            origin, axis = self.body_collar_axis(upper-offset, direction, head-offset)
            frames[Anchor.BODY_COLLAR] = origin, degrees(atan2(axis.x, -axis.y))
        self.draw_outfit_components(painter, definition, components, density, frames, mask=mask, offset=offset)

    def draw_front_outfit(self, painter, scene, alpha=1., *, raster_scale=None):
        self._front_outfit_layers = ()
        definition = outfit_definition(scene.config.outfit, scene.config.outfit_settings)
        components = definition.at(Slot.FRONT)
        if not components:
            if definition != self._outfit_definition:
                self._outfit_sprites.clear()
                self._outfit_definition = definition
            return
        if scene.appearance.sleeping:
            alpha = 1.
        density = painter_density(painter, scene.config.pixel_mode, raster_scale, scene.config.coarse_pixels_4x)
        upper, lower = [p.previous_position.lerp(p.position, alpha) for p in scene.body.chunks]
        app = scene.appearance
        direction = rotate(unit(upper-lower), app.previous_sway+(app.sway-app.previous_sway)*alpha)
        frames = {}
        for anchor in {component.anchor for component in components}:
            if anchor == Anchor.GOWN_COLLAR:
                origin, axis = self.gown_axis(scene, alpha, upper, direction, app.head.sample(alpha))
            else:
                origin, axis = self.body_collar_axis(upper, direction, app.head.sample(alpha))
            frames[anchor] = origin, degrees(atan2(axis.x, -axis.y))
        self._front_outfit_layers = self.draw_outfit_components(
            painter, definition, components, density, frames)
