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
    pearl: str = '#d8cdc5'  # 保留旧配置名，作为共有色。
    pearl_primary: str = '#75a9b9'  # Bell 肤色向白色混合约 25% 的初始值。
    pearl_secondary: str = '#ff8c8f'  # Bell 衣袍上部向白色混合约 25%。
    pearl_glyph: str = '#7faabc'

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                raise ValueError(f'oracle.colors.{field.name} 必须为 #RRGGBB 颜色')


@dataclass(frozen=True, slots=True)
class DragReactionConfig:
    enabled: bool = True
    gesture_probability: float = .90
    flutter_probability: float = .85  # 手势触发后：85% 双手动作 / 15% 单手抗议。
    alternating_probability: float = .47  # 双手动作内部：47% 固定交替，其余随机扑腾。
    eye_open_probability: float = .65
    voice_probability: float = .55  # 与手势、睁眼独立；窗口层消费播放请求。

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError('oracle.drag_reactions.enabled 必须为布尔值')
        for name in ('gesture_probability', 'flutter_probability', 'alternating_probability',
                     'eye_open_probability', 'voice_probability'):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f'oracle.drag_reactions.{name} 必须在 0～1 之间')


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
    drift_speed: float = 1.0  # 漫游巡航基准，独立于视觉失重程度；40 Hz。
    base_speed: float = 2.8
    cross_edge_probability: float = .05  # 普通活动选择及漫游低频选路时的邻边概率。
    antigravity_probability: float = .08
    antigravity_duration_seconds: float = 300.
    pearl_follow_width: float = 360.
    pearl_follow_height: float = 280.
    pearl_matrix_enabled: bool = False
    pearl_matrix_count: int = 14
    pearl_orbits_enabled: bool = False
    pearl_inner_count: int = 4
    pearl_outer_count: int = 2
    pearl_fixed_count: int = 2
    pearl_satellite_count: int = 0  # 旧配置默认不增加持续运动；本机 TOML 开启 1 颗。
    projection_opacity: float = .5  # 全息投影的不透明度；珍珠字符及后续光环共用。
    colors: OracleColors = OracleColors()
    physics_backend: str = 'auto'  # 安装 speedups 可选依赖后自动使用 Numba。
    halo_enabled: bool = True
    halo_scale: float = .8  # 原版圆环/短条的整体倍率；窄活动带会再限制上限。
    pixel_mode: str = 'adaptive'  # 人偶与光环：classic 原始像素 / adaptive 精细像素。
    drag_reactions: DragReactionConfig = DragReactionConfig()
    voice_directory: str = 'auto'  # 首次从 game_dir 准备语音并缓存，也可指定已处理 WAV 目录。

    def __post_init__(self):
        if self.pixel_mode not in ('classic', 'adaptive'):
            raise ValueError('oracle.pixel_mode 必须为 classic / adaptive')
        if not isinstance(self.voice_directory, str) or not self.voice_directory.strip():
            raise ValueError('oracle.voice_directory 必须为非空路径字符串')
        if type(self.halo_enabled) is not bool:
            raise ValueError('oracle.halo_enabled 必须为布尔值')
        if (isinstance(self.halo_scale, bool) or not isinstance(self.halo_scale, (int, float))
                or not isfinite(self.halo_scale) or not .25 <= self.halo_scale <= 1.5):
            raise ValueError('oracle.halo_scale 必须在 0.25～1.5')
        if self.physics_backend not in ('auto', 'python', 'numba'):
            raise ValueError('oracle.physics_backend 必须为 auto / python / numba')
        for name in ('world_width', 'world_height', 'edge_fraction', 'base_fraction', 'arm_scale', 'float_speed', 'drift_speed', 'base_speed',
                     'cross_edge_probability', 'antigravity_probability', 'antigravity_duration_seconds',
                     'pearl_follow_width', 'pearl_follow_height', 'projection_opacity'):
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
        if type(self.pearl_matrix_enabled) is not bool:
            raise ValueError('oracle.pearl_matrix_enabled 必须为布尔值')
        if type(self.pearl_orbits_enabled) is not bool:
            raise ValueError('oracle.pearl_orbits_enabled 必须为布尔值')
        for name, maximum in (('pearl_matrix_count', 64), ('pearl_inner_count', 32), ('pearl_outer_count', 32),
                              ('pearl_fixed_count', 32), ('pearl_satellite_count', 32)):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError(f'oracle.{name} 必须为 0～{maximum} 的整数')
        if not 0 <= self.projection_opacity <= 1:
            raise ValueError('oracle.projection_opacity 必须在 0～1 之间')
        if not .3 <= self.float_speed <= 2.0 or not 1.5 <= self.base_speed <= 4.0:
            raise ValueError('float_speed 必须在 0.3～2.0；base_speed 必须在 1.5～4.0')
        if not .3 <= self.drift_speed <= 1.8:
            raise ValueError('drift_speed 必须在 0.3～1.8')
        if not 0 <= self.cross_edge_probability <= 1:
            raise ValueError('cross_edge_probability 必须在 0～1 之间')
        if not 0 <= self.antigravity_probability <= 1:
            raise ValueError('antigravity_probability 必须在 0～1 之间')
        if self.antigravity_duration_seconds < 1:
            raise ValueError('antigravity_duration_seconds 必须至少为 1 秒')
        if self.pearl_follow_width < 160 or self.pearl_follow_height < 160:
            raise ValueError('珍珠跟随矩形的宽和高至少为 160 逻辑单位')

    @classmethod
    def from_mapping(cls, data):
        if not isinstance(data, dict):
            raise ValueError('oracle 必须为配置表')
        data = dict(data)
        data['colors'] = OracleColors(**data.get('colors', {}))
        data['drag_reactions'] = DragReactionConfig(**data.get('drag_reactions', {}))
        return cls(**data)
