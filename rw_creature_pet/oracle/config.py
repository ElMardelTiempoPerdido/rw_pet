"""Oracle 调试配置：以完好 Moon / DM 为基础的 Bell 外观。"""
from ..shared.messages import Message
from .characters import CHARACTERS, PRINCE_COLORS, PRINCE_COLOR_NAMES
from .space import ALL_EDGES, EDGE_FRACTION_MIN, EDGE_FRACTION_MAX, SpaceAssessment
from .face_config import FaceDecal
from .ear_config import EAR_PART_FIELDS, EarPart
from .eye_config import EYE_FIELDS, EyeAppearance
from .outfit_config import OutfitSettings
from .soft_part_config import SOFT_PART_FIELDS, SoftPart
from .cape_config import Cape
from .clothing_config import CLOTHING_DECAL_FIELDS, ClothingDecal
from .behavior_config import DailyActivityConfig, ReadingConfig
from .drag_reaction_config import DragReactionConfig
from .drift_config import DriftConfig
from .style_config import BehaviorStyleSelections
from .mouse_avoidance_config import MouseAvoidanceConfig
from .audio.voice import VOICE_CLIPS, legacy_voice
from dataclasses import dataclass, fields, replace
from math import isfinite
from pathlib import Path
import re


DISPLAY_SCALES = (1., 1.5, 2., 3., 4.)
EDGE_NAMES = ALL_EDGES
INNER_COLLAR_WIDTH_MAX = 24.  # 完整宽度，允许用宽高领表现围巾轮廓

# 显示长度 = 存储比例 × 可变段长度 + 固定段长度；与头部椭圆、衣袍中央理想轮廓一致
# 衣袍中央顶端为 5×0.65，下摆为 -18×1.35，前 45% 的领口区域不伸缩
ROBE_LENGTH_ANCHOR = (5-23*.45)*(1+.35*(2*.45-1))
CUSTOM_LENGTH_UNITS = {
    'head_length': (100/11+1., 0.),
    'robe_length': (ROBE_LENGTH_ANCHOR+18*1.35, 5*.65-ROBE_LENGTH_ANCHOR),
}

# 调试窗口与桌面设置共用同一份配色名称
COLOR_LABELS = {
    'skin': '皮肤', 'eyes': '眼睛', 'head_shell': '耳机底色',
    'head_highlight': '耳机高光', 'robe_top': '衣袍',
    'robe_bottom': '衣袍渐变色', 'arm': '机械臂主体', 'arm_highlight': '机械臂高光',
    'joints': '关节颜色', 'third_eye': '额头标记',
    'inner_robe': '内搭', 'collar_trim': '衣袍领边', 'beads': '念珠',
    'pearl': '普通珍珠色', 'pearl_primary': '彩珍珠主色', 'pearl_secondary': '彩珍珠辅色',
    'pearl_glyph': '投影',
}

# 自定义模板的双眼单独编辑，标记和念珠暂不使用公共调色项
CUSTOM_COLOR_NAMES = tuple(name for name in COLOR_LABELS if name not in ('third_eye', 'beads', 'eyes'))


def validate_edges(edges, base_side):
    if not isinstance(edges, (tuple, list)) or any(edge not in EDGE_NAMES for edge in edges):
        raise ValueError('允许活动的边缘必须为 top / right / bottom / left')
    if not edges:
        raise ValueError('请至少选择一条允许活动的边缘。')
    if len(set(edges)) != len(edges):
        raise ValueError('允许活动的边缘不能重复。')
    indices = {EDGE_NAMES.index(edge) for edge in edges}
    if len(indices) == 2 and all((i+1) % 4 not in indices for i in indices):
        raise ValueError('所选边缘必须连续：不能只选顶部和底部，或只选左侧和右侧。')
    if base_side not in edges:
        raise ValueError('启动时的位置必须包含在允许活动的边缘中。')
    return tuple(edge for edge in EDGE_NAMES if edge in edges)


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
                raise ValueError(Message('oracle.colors.{value0} 必须为 #RRGGBB 颜色', value0=field.name))


def migrate_shoulder_width(data):
    """为已有胸肩配置保留原先的袖根间距，新配置使用独立肩宽默认值"""
    width = data.get('chest_width')
    if ('shoulder_width' not in data and not isinstance(width, bool)
            and isinstance(width, (int, float)) and 8 <= width <= 18):
        return {**data, 'shoulder_width': width*2/3}
    return data


@dataclass(frozen=True, slots=True)
class CustomAppearance:
    """独立保存的尺寸和面部贴图；长度为比例，其余尺寸为逻辑像素，宽度为完整宽度"""
    head_length: float = 1.
    sleeve_root_width: float = 6.
    sleeve_cuff_width: float = 10.
    robe_length: float = 1.
    robe_flare: float = 1.  # 相对原版的横向展开量，不随衣袍长度变化
    robe_hem_curve: float = 1.  # 相对原版底边弧度，0 为平底；不改变中央长度
    sleeve_cuff_radius: float = 2.
    neck_width: float = 3.
    chest_width: float = 12.
    chest_height: float = 8.
    shoulder_width: float = 8.
    inner_robe_enabled: bool = True
    inner_collar_enabled: bool = True
    inner_collar_height: float = 3.
    inner_collar_top_width: float = 3.
    inner_collar_bottom_width: float = 4.
    neckline_shape: str = 'v'
    neckline_width: float = 7.6
    neckline_depth: float = 6.
    neckline_height: float = 3.5
    neckline_roundness: float = .55
    neckline_tip_radius: float = 0.
    neckline_trim_enabled: bool = True
    neckline_trim_width: float = 2.
    neckline_trim_gap: float = 0.
    eye_1: EyeAppearance = EyeAppearance()
    eye_2: EyeAppearance = EyeAppearance()
    forehead: FaceDecal = FaceDecal(offset_y=-3.)
    face: FaceDecal = FaceDecal()
    ear_body: EarPart = EarPart(enabled=True, tone='split')
    ear_part_1: EarPart = EarPart(kind='line', width=1., height=8., offset_y=2.)
    ear_part_2: EarPart = EarPart(kind='line', width=1., height=3., rotation=90., offset_y=6.)
    ear_part_3: EarPart = EarPart(kind='ellipse', width=2., height=2., offset_y=7.)
    soft_part_1: SoftPart = SoftPart(offset_x=-3.)
    soft_part_2: SoftPart = SoftPart(offset_x=3., length=22.)
    cape: Cape = Cape()
    clothing_decal_1: ClothingDecal = ClothingDecal()
    clothing_decal_2: ClothingDecal = ClothingDecal(part='left_sleeve')
    clothing_decal_3: ClothingDecal = ClothingDecal(part='right_sleeve')

    def __post_init__(self):
        for name in ('inner_robe_enabled', 'inner_collar_enabled', 'neckline_trim_enabled'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(Message('自定义外观 {name} 必须为布尔值', name=name))
        if not isinstance(self.forehead, FaceDecal) or not isinstance(self.face, FaceDecal):
            raise ValueError('面部贴图必须为贴图配置')
        if any(not isinstance(getattr(self, name), EarPart) for name in EAR_PART_FIELDS):
            raise ValueError('耳机部件必须为部件配置')
        if any(not isinstance(getattr(self, name), EyeAppearance) for name in EYE_FIELDS):
            raise ValueError('眼睛必须为眼睛外观配置')
        if any(not isinstance(getattr(self, name), SoftPart) for name in SOFT_PART_FIELDS):
            raise ValueError('柔性部件必须为部件配置')
        if not isinstance(self.cape, Cape):
            raise ValueError('斗篷必须为斗篷配置')
        if any(not isinstance(getattr(self, name), ClothingDecal) for name in CLOTHING_DECAL_FIELDS):
            raise ValueError('服装贴图必须为服装贴图配置')
        if self.neckline_shape not in ('arc', 'v'):
            raise ValueError('领口形状必须为 arc / v')
        for name, low, high in (('head_length', .7, 1.5), ('sleeve_root_width', 2., 12.),
                                ('sleeve_cuff_width', 2., 16.), ('robe_length', .7, 1.5),
                                ('robe_flare', 0., 2.), ('robe_hem_curve', 0., 2.),
                                ('sleeve_cuff_radius', 0., 4.), ('neck_width', 1., 8.),
                                ('chest_width', 8., 18.), ('chest_height', 4., 10.),
                                ('shoulder_width', 4., 18.),
                                ('inner_collar_height', 0., 8.),
                                ('inner_collar_top_width', 1., INNER_COLLAR_WIDTH_MAX),
                                ('inner_collar_bottom_width', 1., INNER_COLLAR_WIDTH_MAX),
                                ('neckline_width', 2., 18.), ('neckline_depth', 0., 16.),
                                ('neckline_height', -6., 8.), ('neckline_roundness', 0., 1.),
                                ('neckline_tip_radius', 0., 4.), ('neckline_trim_width', 0., 6.),
                                ('neckline_trim_gap', 0., 6.)):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or not low <= value <= high):
                raise ValueError(Message('自定义外观 {name} 必须在 {low}～{high} 之间',
                                         name=name, low=low, high=high))

    @classmethod
    def from_mapping(cls, data, *, eye_color='#050000'):
        data = dict(migrate_shoulder_width(data))
        for name in EYE_FIELDS:
            data[name] = EyeAppearance(**{'color': eye_color, **data.get(name, {})})
        for name, y in (('forehead', -3.), ('face', 0.)):
            data[name] = FaceDecal(**{'offset_y': y, **data.get(name, {})})
        from dataclasses import asdict
        defaults = cls()
        data['cape'] = Cape(**data.get('cape', {}))
        for name in CLOTHING_DECAL_FIELDS:
            data[name] = ClothingDecal(**{**asdict(getattr(defaults, name)), **data.get(name, {})})
        for name in SOFT_PART_FIELDS:
            data[name] = SoftPart(**{**asdict(getattr(defaults, name)), **data.get(name, {})})
        for name in EAR_PART_FIELDS:
            data[name] = EarPart(**{**asdict(getattr(defaults, name)), **data.get(name, {})})
        return cls(**data)

    def resolve_image_paths(self, base):
        decals = {}
        for name in ('forehead', 'face', *EAR_PART_FIELDS, *SOFT_PART_FIELDS, *CLOTHING_DECAL_FIELDS):
            decal = getattr(self, name)
            if decal.image_path:
                path = Path(decal.image_path).expanduser()
                path = (path if path.is_absolute() else base/path).resolve()
                decals[name] = replace(decal, image_path=str(path))
        return replace(self, **decals) if decals else self


@dataclass(frozen=True, slots=True)
class OracleConfig:
    world_width: float = 960.0
    world_height: float = 600.0
    edge_fraction: float = .20
    base_side: str = 'top'
    allowed_edges: tuple[str, ...] = EDGE_NAMES
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
    pearl_matrix_avoid_radius: float = 80.  # 自主停留点与矩阵中心的间距；0 关闭。
    pearl_playback_probability: float = .25  # 矩阵珠召近阅读后，触发无声音乐脉冲。
    pearl_bubble_max_size: float = 12.  # bubble 最大直径，逻辑像素；下限固定为珍珠的 6px。
    pearl_bubble_color: str = '#ff0000'
    pearl_orbits_enabled: bool = False
    pearl_inner_count: int = 4
    pearl_outer_count: int = 2
    pearl_fixed_count: int = 2
    pearl_satellite_count: int = 0  # 旧配置默认不增加持续运动；本机 TOML 开启 1 颗。
    projection_opacity: float = .5  # 全息投影的不透明度；珍珠字符及后续光环共用。
    drag_projection_probability: float = .20  # 每次空闲拖动反应选择；0 关闭。
    drag_projection_cooldown_seconds: float = 45.  # 从触发开始计时，松手不重置。
    colors: OracleColors = OracleColors()
    physics_backend: str = 'auto'  # 安装 speedups 可选依赖后自动使用 Numba。
    halo_enabled: bool = True
    halo_scale: float = .8  # 原版圆环/短条的整体倍率；窄活动带会再限制上限。
    halo_arcs_enabled: bool = True
    halo_arc_max_count: int = 3
    pixel_mode: str = 'adaptive'  # 人偶与光环：classic 原始像素 / adaptive 精细像素。
    coarse_pixels_4x: bool = False  # 4× 改用 1× 像素画布；默认使用 2×，3× 始终使用 1×
    outfit: str = 'normal'  # normal 原有外观 / maid 叠加女仆套装。
    outfit_settings: OutfitSettings = OutfitSettings()
    body_appearance: str = 'bell'  # 固定角色与自定义模板使用独立配色和绘制入口
    custom_appearance: CustomAppearance = CustomAppearance()
    custom_colors: OracleColors = OracleColors()
    prince_colors: OracleColors = OracleColors(**PRINCE_COLORS)
    hide_cords: bool = False  # 隐藏粗细线缆，同时停止线缆物理求解。
    glow_enabled: bool = False
    glow_color: str = '#ffffff'
    glow_radius: float = 2.  # 外发光扩散半径，逻辑像素；跟随桌宠显示倍率。
    glow_opacity: float = .4  # 仅调节柔光合成强度；0 隐藏，1 为完整强度。
    drag_reactions: DragReactionConfig = DragReactionConfig()
    voice: str = 'bell'  # 角色行为选项，与主体外观、眼睛和手臂能力无关
    voice_directory: str = 'auto'  # 首次从 game_dir 准备语音并缓存，也可指定已处理 WAV 目录。
    behavior_styles: BehaviorStyleSelections = BehaviorStyleSelections()
    daily_activity: DailyActivityConfig = DailyActivityConfig()
    reading: ReadingConfig = ReadingConfig()
    drift: DriftConfig = DriftConfig()
    mouse_avoidance: MouseAvoidanceConfig = MouseAvoidanceConfig()

    def __post_init__(self):
        if not isinstance(self.behavior_styles, BehaviorStyleSelections):
            raise ValueError("Invalid behavior style selections")
        if not isinstance(self.drift, DriftConfig) or not isinstance(self.mouse_avoidance, MouseAvoidanceConfig):
            raise ValueError('漫游或鼠标躲避配置无效')
        if not isinstance(self.daily_activity, DailyActivityConfig) or not isinstance(self.reading, ReadingConfig):
            raise ValueError('日常活动或阅读配置无效')
        if type(self.coarse_pixels_4x) is not bool:
            raise ValueError('oracle.coarse_pixels_4x 必须为布尔值')
        if self.outfit not in ('normal', 'maid'):
            raise ValueError('oracle.outfit 必须为 normal / maid')
        if not isinstance(self.outfit_settings, OutfitSettings):
            raise ValueError('附加外观配置无效')
        if self.body_appearance not in CHARACTERS:
            raise ValueError('主体外观必须为 bell / custom / prince')
        if not isinstance(self.custom_appearance, CustomAppearance):
            raise ValueError('自定义外观必须为尺寸配置')
        if any(not isinstance(getattr(self, name), OracleColors)
               for name in ('colors', 'custom_colors', 'prince_colors')):
            raise ValueError('外观配色必须为颜色配置')
        if type(self.hide_cords) is not bool:
            raise ValueError('oracle.hide_cords 必须为布尔值')
        if type(self.glow_enabled) is not bool:
            raise ValueError('oracle.glow_enabled 必须为布尔值')
        if not isinstance(self.glow_color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', self.glow_color):
            raise ValueError('发光颜色必须为 #RRGGBB 颜色')
        if (isinstance(self.glow_radius, bool) or not isinstance(self.glow_radius, (int, float))
                or not isfinite(self.glow_radius) or not 1 <= self.glow_radius <= 24):
            raise ValueError('发光半径必须在 1～24 逻辑像素之间')
        if (isinstance(self.glow_opacity, bool) or not isinstance(self.glow_opacity, (int, float))
                or not isfinite(self.glow_opacity) or not 0 <= self.glow_opacity <= 1):
            raise ValueError('发光不透明度必须在 0～1 之间')
        if self.pixel_mode not in ('classic', 'adaptive'):
            raise ValueError('oracle.pixel_mode 必须为 classic / adaptive')
        if not isinstance(self.voice_directory, str) or not self.voice_directory.strip():
            raise ValueError('oracle.voice_directory 必须为非空路径字符串')
        if not isinstance(self.voice, str) or self.voice not in VOICE_CLIPS:
            raise ValueError('oracle.voice 必须为 bell / none')
        if type(self.halo_enabled) is not bool:
            raise ValueError('oracle.halo_enabled 必须为布尔值')
        if type(self.halo_arcs_enabled) is not bool:
            raise ValueError('oracle.halo_arcs_enabled 必须为布尔值')
        if type(self.halo_arc_max_count) is not int or not 1 <= self.halo_arc_max_count <= 10:
            raise ValueError('oracle.halo_arc_max_count 必须为 1～10 的整数')
        if (isinstance(self.halo_scale, bool) or not isinstance(self.halo_scale, (int, float))
                or not isfinite(self.halo_scale) or not .25 <= self.halo_scale <= 1.5):
            raise ValueError('oracle.halo_scale 必须在 0.25～1.5')
        if self.physics_backend not in ('auto', 'python', 'numba'):
            raise ValueError('oracle.physics_backend 必须为 auto / python / numba')
        for name in ('world_width', 'world_height', 'edge_fraction', 'base_fraction', 'arm_scale', 'float_speed', 'drift_speed', 'base_speed',
                     'cross_edge_probability', 'antigravity_probability', 'antigravity_duration_seconds',
                     'pearl_follow_width', 'pearl_follow_height', 'pearl_matrix_avoid_radius',
                     'pearl_playback_probability', 'pearl_bubble_max_size', 'projection_opacity',
                     'drag_projection_probability', 'drag_projection_cooldown_seconds'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
                raise ValueError(Message('oracle.{value0} 必须为有限数值', value0=name))
        if not EDGE_FRACTION_MIN <= self.edge_fraction <= EDGE_FRACTION_MAX:
            raise ValueError('oracle.edge_fraction 必须在 0.20～0.499 之间')
        if self.base_side not in EDGE_NAMES:
            raise ValueError('oracle.base_side 必须为 top / right / bottom / left')
        object.__setattr__(self, 'allowed_edges', validate_edges(self.allowed_edges, self.base_side))
        if not 0 <= self.base_fraction <= 1:
            raise ValueError('oracle.base_fraction 必须在 0～1 之间')
        if not .35 <= self.arm_scale <= .75:
            raise ValueError('oracle.arm_scale 必须在 0.35～0.75 之间')
        if not SpaceAssessment(self.world_width, self.world_height, self.arm_scale,
                               self.edge_fraction, self.allowed_edges).valid:
            raise ValueError('场景空间不足，请扩大活动带、缩小机械臂或降低显示倍率')
        if type(self.sliding_base) is not bool:
            raise ValueError('oracle.sliding_base 必须为布尔值')
        if type(self.pearl_matrix_enabled) is not bool:
            raise ValueError('oracle.pearl_matrix_enabled 必须为布尔值')
        if not 0 <= self.pearl_matrix_avoid_radius <= 300:
            raise ValueError('矩阵避让半径必须在 0～300 逻辑像素之间')
        if not 0 <= self.pearl_playback_probability <= 1:
            raise ValueError('珍珠播放动画概率必须在 0～1 之间')
        if not 6 <= self.pearl_bubble_max_size <= 64:
            raise ValueError('播放光泡最大直径必须在 6～64 逻辑像素之间')
        if not isinstance(self.pearl_bubble_color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', self.pearl_bubble_color):
            raise ValueError('播放光泡颜色必须为 #RRGGBB 颜色')
        if type(self.pearl_orbits_enabled) is not bool:
            raise ValueError('oracle.pearl_orbits_enabled 必须为布尔值')
        for name, maximum in (('pearl_matrix_count', 64), ('pearl_inner_count', 32), ('pearl_outer_count', 32),
                              ('pearl_fixed_count', 32), ('pearl_satellite_count', 32)):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError(Message('oracle.{value0} 必须为 0～{value1} 的整数', value0=name, value1=maximum))
        if not 0 <= self.projection_opacity <= 1:
            raise ValueError('oracle.projection_opacity 必须在 0～1 之间')
        if not 0 <= self.drag_projection_probability <= 1:
            raise ValueError('拖动投影触发概率必须在 0～1 之间')
        if not 0 <= self.drag_projection_cooldown_seconds <= 3600:
            raise ValueError('拖动投影冷却时间必须在 0～3600 秒之间')
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

    @property
    def character(self):
        return CHARACTERS[self.body_appearance]

    @property
    def active_outfit(self):
        return self.outfit if self.character.outfits else 'normal'

    @property
    def editable_color_names(self):
        if self.body_appearance == 'prince':
            return PRINCE_COLOR_NAMES
        return CUSTOM_COLOR_NAMES if self.body_appearance == 'custom' else tuple(COLOR_LABELS)

    @property
    def active_custom_appearance(self):
        return self.custom_appearance if self.body_appearance == 'custom' else None

    @property
    def active_colors(self):
        return getattr(self, self.character.palette)

    @classmethod
    def from_mapping(cls, data):
        if not isinstance(data, dict):
            raise ValueError('oracle 必须为配置表')
        data = dict(data)
        data.setdefault('voice', legacy_voice(data.get('body_appearance', 'bell')))
        # 旧 TOML 仅有共用配色时，将它作为两套配色的初始值
        data['custom_colors'] = OracleColors(**data.get('custom_colors', data.get('colors', {})))
        data['colors'] = OracleColors(**data.get('colors', {}))
        data['prince_colors'] = OracleColors(**{**PRINCE_COLORS, **data.get('prince_colors', {})})
        data['custom_appearance'] = CustomAppearance.from_mapping(data.get('custom_appearance', {}),
                                                                 eye_color=data['custom_colors'].eyes)
        data['drag_reactions'] = DragReactionConfig(**data.get('drag_reactions', {}))
        data['outfit_settings'] = OutfitSettings.from_mapping(data.get('outfit_settings', {}))
        data['daily_activity'] = DailyActivityConfig(**data.get('daily_activity', {}))
        data['reading'] = ReadingConfig(**data.get('reading', {}))
        data['behavior_styles'] = BehaviorStyleSelections.from_mapping(data.get('behavior_styles', {}))
        data['drift'] = DriftConfig(**data.get('drift', {}))
        data['mouse_avoidance'] = MouseAvoidanceConfig(**data.get('mouse_avoidance', {}))
        return cls(**data)
