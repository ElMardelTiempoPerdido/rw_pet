"""附加外观的静态部件定义，不依赖 Qt，也不包含角色的个人修改"""
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import lru_cache
from math import hypot


class Anchor(StrEnum):
    HEAD_CROWN = 'head_crown'
    BODY_COLLAR = 'body_collar'
    GOWN_COLLAR = 'gown_collar'


class Slot(StrEnum):
    BEHIND_HEAD = 'behind_head'
    FRONT_HEAD = 'front_head'
    BEFORE_SLEEVES = 'before_sleeves'
    AFTER_SLEEVES = 'after_sleeves'
    FRONT = 'front'


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
        if head_slot != (self.anchor == Anchor.HEAD_CROWN):
            raise ValueError('Head components must use a head slot and the head anchor')
        if self.clip != Clip.NONE and self.slot not in (Slot.BEFORE_SLEEVES, Slot.AFTER_SLEEVES):
            raise ValueError('Clothing clips require a body slot')
        if head_slot and self.sampling != Sampling.LOCAL:
            raise ValueError('Head components are rasterized with the head')
        if self.slot == Slot.FRONT and self.sampling != Sampling.ALIGNED:
            raise ValueError('Front components require aligned sampling for their separate glow layer')

    def variant(self, density):
        return min(self.variants, key=lambda value: abs(value.density-density))


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


NORMAL = OutfitDefinition('normal')
MAID = OutfitDefinition('maid', (
    OutfitComponent('head', Anchor.HEAD_CROWN, Slot.BEHIND_HEAD,
                    _maid_variants('head', ((0., -3.), (0., -4.), (0., -5.)))),
    OutfitComponent('lace', Anchor.BODY_COLLAR, Slot.AFTER_SLEEVES,
                    _maid_variants('lace', ((-1., 0.), (-2., 1.), (-2., 1.))),
                    image_origin=(1., 0.), mirror=True),
    OutfitComponent('apron', Anchor.GOWN_COLLAR, Slot.BEFORE_SLEEVES,
                    _maid_variants('apron', ((0., 1.), (0., 3.), (0., 4.))),
                    clip=Clip.CLOTHING, sampling=Sampling.ALIGNED),
    OutfitComponent('ribbon_up', Anchor.HEAD_CROWN, Slot.FRONT_HEAD,
                    _maid_variants('ribbon_up', ((0., -1.), (1., -2.), (2., -2.))),
                    image_origin=(0., 0.)),
    OutfitComponent('ribbon_down', Anchor.GOWN_COLLAR, Slot.FRONT,
                    _maid_variants('ribbon_down', ((0., 7.), (0., 12.), (0., 14.))),
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
            parts.append(replace(part, mirror=values.mirror, offset=(values.offset_x, values.offset_y),
                                 color_adjustment=(values.hue, values.saturation, values.brightness)))
    return replace(definition, components=tuple(parts))


def outfit_padding(config):
    """在原有附件余量上增加位移半径，包含旋转和镜像后的外形"""
    definition = outfit_definition(config.outfit, config.outfit_settings)
    return max((hypot(*part.offset) for part in definition.components), default=0.)
