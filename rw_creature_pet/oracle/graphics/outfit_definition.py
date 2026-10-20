"""附加外观的静态部件定义，不依赖 Qt，也不包含角色的个人修改"""
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import lru_cache
from ..outfit_layout import Anchor, MAID_PLACEMENTS, Slot, allowed_slots


class Clip(StrEnum):
    NONE = 'none'
    CLOTHING = 'clothing'  # 衣袍与启用的内搭轮廓，不含袖子


class Sampling(StrEnum):
    LOCAL = 'local'  # 在所属部位坐标内绘制，随该图层一起像素化
    ALIGNED = 'aligned'  # 固定锚点的旋转小图，最终落点对齐世界像素网格


@dataclass(frozen=True)
class ImageVariant:
    density: float
    asset: str  # 相对于 PACKAGE_ROOT
    offset: tuple[float, float] = (0., 0.)  # 此档原图的显示像素，x 向右、y 向脚


@dataclass(frozen=True)
class OutfitComponent:
    id: str
    anchor: Anchor
    slot: Slot
    variants: tuple[ImageVariant, ...]
    image_origin: tuple[float, float] = (.5, 0.)  # 原图内的归一化定位点
    mirror: bool = False
    clip: Clip = Clip.NONE
    sampling: Sampling = Sampling.LOCAL
    offset: tuple[float, float] = (0., 0.)  # 角色微调，单位为逻辑像素
    color_adjustment: tuple[float, float, float] = (0., 0., 0.)  # 色相角、饱和度与明度增量

    def __post_init__(self):
        if not self.id or not self.variants:
            raise ValueError('Outfit components need an id and image variants')
        densities = [v.density for v in self.variants]
        if any(d <= 0 for d in densities) or len(set(densities)) != len(densities):
            raise ValueError('Outfit image densities must be positive and unique')
        head_slot = self.slot in (Slot.BEHIND_HEAD, Slot.FRONT_HEAD)
        if self.slot not in allowed_slots(self.anchor):
            raise ValueError('Head components must use a head slot and the head anchor')
        if self.clip != Clip.NONE and head_slot:
            raise ValueError('Clothing clips require a body slot')
        if head_slot and self.sampling != Sampling.LOCAL:
            raise ValueError('Head components are rasterized with the head')
        if self.slot == Slot.FRONT and self.sampling != Sampling.ALIGNED:
            raise ValueError('Front components require aligned sampling for their separate glow layer')

    def variant(self, density):
        return min(self.variants, key=lambda value: abs(value.density-density))

    @property
    def region(self):
        return Anchor(self.anchor).region


@dataclass(frozen=True)
class OutfitDefinition:
    id: str
    components: tuple[OutfitComponent, ...] = ()
    collar_under_sleeves: bool = False
    palms_over_decorations: bool = True

    def __post_init__(self):
        ids = [part.id for part in self.components]
        if not self.id or len(set(ids)) != len(ids):
            raise ValueError('Outfit and component ids must be unique and nonempty')

    def at(self, slot):
        # 同一槽位保持定义中的顺序，后列出的部件覆盖前面的部件
        return tuple(part for part in self.components if part.slot == slot)

    def component(self, component_id):
        return next(part for part in self.components if part.id == component_id)


def _maid_variants(part, offsets):
    return tuple(ImageVariant(density, f'skin/maid/maid_{part}_{density:g}x.png', offset)
                 for density, offset in zip((1., 1.5, 2.), offsets))


def _maid_component(part, offsets, **values):
    anchor, slot = MAID_PLACEMENTS[part]
    return OutfitComponent(part, anchor, slot, _maid_variants(part, offsets), **values)


NORMAL = OutfitDefinition('normal')
MAID = OutfitDefinition('maid', (
    _maid_component('head', ((0., -3.), (0., -4.), (0., -5.))),
    _maid_component('lace', ((-1., 0.), (-2., 1.), (-2., 1.)),
                    image_origin=(1., 0.), mirror=True),
    _maid_component('apron', ((0., 1.), (0., 3.), (0., 4.)),
                    clip=Clip.CLOTHING, sampling=Sampling.ALIGNED),
    _maid_component('ribbon_up', ((0., -1.), (1., -2.), (2., -2.)),
                    image_origin=(0., 0.)),
    _maid_component('ribbon_down', ((0., 7.), (0., 12.), (0., 14.)),
                    sampling=Sampling.ALIGNED),
), collar_under_sleeves=True, palms_over_decorations=False)

BUILTIN_OUTFITS = {outfit.id: outfit for outfit in (NORMAL, MAID)}


def outfit_definition(outfit, settings=None):
    definition = BUILTIN_OUTFITS[outfit]
    adjustments = getattr(settings, outfit, None)
    return definition if adjustments is None else adjusted_definition(definition, adjustments)


@lru_cache(maxsize=128)
def adjusted_definition(definition, adjustments):
    parts = []
    for part in definition.components:
        values = getattr(adjustments, part.id, None)
        if values is None:
            parts.append(part)
        elif values.enabled:
            head = values.anchor.region == 'head'
            sampling = (Sampling.LOCAL if head else Sampling.ALIGNED
                        if values.layer == Slot.FRONT else part.sampling)
            parts.append(replace(part, anchor=values.anchor, slot=values.layer,
                                 clip=Clip.NONE if head else part.clip, sampling=sampling,
                                 mirror=values.mirror, offset=(values.offset_x, values.offset_y),
                                 color_adjustment=(values.hue, values.saturation, values.brightness)))
    return replace(definition, components=tuple(parts))
