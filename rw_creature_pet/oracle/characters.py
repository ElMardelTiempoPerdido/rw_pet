"""角色能力与独立配色入口；固定角色不借用自定义外观参数"""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Character:
    palette: str
    has_eyes: bool = True
    has_hands: bool = True
    outfits: bool = True
    neck_extension: float = 0.  # 固定颈根的额外逻辑长度，不放大头部摆动段


CHARACTERS = {
    'bell': Character('colors'),
    'custom': Character('custom_colors'),
    # 基础头高为 14px + 额外颈长，Prince 的弓身和头部惯性单独在 motion/prince.py 中处理
    'prince': Character('prince_colors', has_eyes=False, has_hands=False, outfits=False, neck_extension=5.),
}

# 暂用深色的固定轮廓占位；Rot Prince 的专用造型在 graphics/prince.py 中继续开发
PRINCE_COLORS = {
    'skin': '#34313f', 'robe_top': '#302e3b', 'robe_bottom': '#171620',
    'arm': '#7b7889', 'arm_highlight': '#b3afbd', 'joints': '#474451',
    'pearl': '#d8cdc5', 'pearl_primary': '#b597c9', 'pearl_secondary': '#889bab',
    'pearl_glyph': '#b6a1cc',
}
PRINCE_COLOR_NAMES = tuple(PRINCE_COLORS)
