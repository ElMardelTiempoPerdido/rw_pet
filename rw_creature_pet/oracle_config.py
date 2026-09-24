"""Oracle 调试配置：以完好 Moon / DM 为基础的 Bell 外观。"""
from dataclasses import dataclass, fields
from math import isfinite
import re


@dataclass(frozen=True, slots=True)
class OracleColors:
    # OracleGraphics.SkinColor(IsPastMoon) = (0.13, 0.53, 0.69).
    skin: str = '#2187b0'
    eyes: str = '#050000'
    head_shell: str = '#adb3b9'
    head_highlight: str = '#e0e5e9'
    # DM 衣袍 Color(f) 的上下端 HSL 颜色；目前用渐变轮廓预览。
    robe_top: str = '#a36329'
    robe_bottom: str = '#8f483d'
    inner_robe: str = '#ffb7c5'
    collar_trim: str = '#ff949f'
    beads: str = '#9cddd8'
    # 原版金属受房间调色板影响；这里使用固定的中性预览颜色。
    arm: str = '#9aa4b1'
    arm_highlight: str = '#d2dae3'
    joints: str = '#424c5d'
    third_eye: str = '#bc29e7'
    pearl: str = '#d8cdc5'
    pearl_glyph: str = '#a6bcb9'

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                raise ValueError(f'oracle.colors.{field.name} 必须为 #RRGGBB 颜色')


@dataclass(frozen=True, slots=True)
class OracleConfig:
    world_width: float = 960.0
    world_height: float = 600.0
    edge_fraction: float = .20
    base_side: str = 'top'
    base_fraction: float = .50
    # 保留原版 300:150:90:30 比例，缩小机械臂以适应桌面边缘带。
    arm_scale: float = .60
    sliding_base: bool = True
    float_speed: float = 1.6
    base_speed: float = 2.8
    cross_edge_probability: float = .05
    colors: OracleColors = OracleColors()

    def __post_init__(self):
        for name in ('world_width', 'world_height', 'edge_fraction', 'base_fraction', 'arm_scale', 'float_speed', 'base_speed',
                     'cross_edge_probability'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
                raise ValueError(f'oracle.{name} 必须为有限数值')
        if self.world_width < 640 or self.world_height < 480:
            raise ValueError('Oracle 场景至少为 640 × 480')
        if not .20 <= self.edge_fraction <= .35:
            raise ValueError('oracle.edge_fraction 必须在 0.20～0.35 之间')
        if self.base_side not in ('top', 'right', 'bottom', 'left'):
            raise ValueError('oracle.base_side 必须为 top / right / bottom / left')
        if not 0 <= self.base_fraction <= 1:
            raise ValueError('oracle.base_fraction 必须在 0～1 之间')
        if not .35 <= self.arm_scale <= .75:
            raise ValueError('oracle.arm_scale 必须在 0.35～0.75 之间')
        if type(self.sliding_base) is not bool:
            raise ValueError('oracle.sliding_base 必须为布尔值')
        if not .3 <= self.float_speed <= 2.0 or not 1.5 <= self.base_speed <= 4.0:
            raise ValueError('float_speed 必须在 0.3～2.0；base_speed 必须在 1.5～4.0')
        if not 0 <= self.cross_edge_probability <= 1:
            raise ValueError('cross_edge_probability 必须在 0～1 之间')

    @classmethod
    def from_mapping(cls, data):
        if not isinstance(data, dict):
            raise ValueError('oracle 必须为配置表')
        data = dict(data)
        data['colors'] = OracleColors(**data.get('colors', {}))
        return cls(**data)
