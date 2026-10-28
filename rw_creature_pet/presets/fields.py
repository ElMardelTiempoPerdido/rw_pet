"""所有 AppConfig 叶字段的归属清单，与 GUI 页签及控件可见性无关"""
from ..config import AppConfig
from .registry import FieldScope, build_registry


_APPEARANCE = FieldScope.APPEARANCE
_PROFILE = FieldScope.PROFILE
_LOCAL = FieldScope.LOCAL

# 同一结构的不同实例复用显式清单；不能改成读取 dataclass/UI 字段自动登记
_COLOR_FIELDS = (
    'skin', 'eyes', 'head_shell', 'head_highlight', 'robe_top', 'robe_bottom',
    'inner_robe', 'collar_trim', 'beads', 'arm', 'arm_highlight', 'joints',
    'third_eye', 'pearl', 'pearl_primary', 'pearl_secondary', 'pearl_glyph',
)
_DECAL_FIELDS = ('enabled', 'image_path', 'image_name', 'offset_x', 'offset_y')
_EAR_FIELDS = (*_DECAL_FIELDS, 'kind', 'width', 'height', 'rotation', 'tone')
_CLOTHING_FIELDS = (*_DECAL_FIELDS, 'part')
_EYE_FIELDS = ('color', 'visible', 'default_open', 'height_mode')
_OUTFIT_PART_FIELDS = ('enabled', 'anchor', 'layer', 'offset_x', 'offset_y', 'mirror', 'hue',
                       'saturation', 'brightness')
_SOFT_PART_FIELDS = ('enabled', 'anchor', 'offset_x', 'offset_y', 'angle', 'length', 'width',
                     'color', 'softness', 'damping', 'kind', 'layer', 'image_path', 'image_name',
                     'tip_width_ratio')

FIELD_SCOPES = build_registry((
    ('', _LOCAL, ('game_dir',)),
    ('debug', _LOCAL, ('tick_rate', 'world_width', 'world_height', 'floor_y')),
    ('desktop', _LOCAL, ('scale', 'autonomous', 'screen')),
    ('audio', _LOCAL, ('enabled', 'volume')),
    ('ui', _LOCAL, ('language',)),
    ('interaction', _LOCAL, ('drag_enabled',)),
    # 鼠标注意与避让属于性格；是否允许拖动属于使用习惯
    ('interaction', _PROFILE, (
        'hover_radius', 'hover_dwell_seconds', 'hover_probability',
        'hover_open_probability', 'hover_avoidance_enabled',
    )),
    # 设备空间、显示偏好、性能后端及路径均不随角色预设覆盖
    ('oracle', _LOCAL, (
        'world_width', 'world_height', 'edge_fraction', 'base_side',
        'allowed_edges', 'base_fraction', 'arm_scale', 'sliding_base',
        'physics_backend', 'pixel_mode', 'coarse_pixels_4x', 'hide_cords',
        'glow_enabled', 'glow_color', 'glow_radius', 'glow_opacity',
        'halo_enabled', 'halo_arcs_enabled', 'voice_directory',
    )),
    ('oracle', _PROFILE, (
        'voice',
        'float_speed', 'drift_speed', 'base_speed', 'cross_edge_probability',
        'antigravity_probability', 'antigravity_duration_seconds',
        'pearl_follow_width', 'pearl_follow_height', 'pearl_matrix_enabled',
        'pearl_matrix_count', 'pearl_matrix_avoid_radius', 'pearl_playback_probability',
        'pearl_bubble_max_size', 'pearl_orbits_enabled', 'pearl_inner_count',
        'pearl_outer_count', 'pearl_fixed_count', 'pearl_satellite_count',
        'projection_opacity', 'drag_projection_probability',
        'drag_projection_cooldown_seconds', 'halo_scale', 'halo_arc_max_count',
    )),
    ('oracle.daily_activity', _PROFILE, (
        'idle_min_seconds', 'idle_max_seconds', 'long_idle_min_seconds', 'long_idle_max_seconds',
        'move_min_distance', 'move_max_distance', 'idle_weight', 'move_weight', 'meditate_weight',
        'meditate_min_seconds', 'meditate_max_seconds', 'cross_edge_cooldown_seconds',
        'cross_edge_check_seconds', 'move_lean_degrees',
    )),
    ('oracle.reading', _PROFILE, ('start_probability',)),
    ('oracle.drift', _PROFILE, (
        'cooldown_seconds', 'duration_variation', 'entry_min_seconds', 'entry_max_seconds',
        'resume_min_seconds', 'resume_max_seconds', 'short_pause_min_seconds', 'short_pause_max_seconds',
        'normal_pause_min_seconds', 'normal_pause_max_seconds', 'long_pause_min_seconds', 'long_pause_max_seconds',
        'short_pause_weight', 'normal_pause_weight', 'long_pause_weight', 'bout_min_seconds', 'bout_max_seconds',
        'long_bout_min_seconds', 'long_bout_max_seconds', 'long_bout_probability',
        'move_min_distance', 'move_max_distance', 'speed_min_factor', 'speed_max_factor',
    )),
    ('oracle.mouse_avoidance', _PROFILE, (
        'delay_min_seconds', 'delay_max_seconds', 'probability', 'enter_distance', 'exit_distance',
        'leave_grace_seconds', 'pointer_lag_seconds', 'retry_min_seconds', 'retry_max_seconds',
        'impatience_min_seconds', 'impatience_max_seconds', 'move_probability',
        'move_min_distance', 'move_max_distance', 'speed_min', 'speed_max',
        'lean_move_probability', 'lean_move_min_distance', 'lean_move_max_distance',
        'lean_min_degrees', 'lean_max_degrees', 'lean_sample_power', 'lean_speed', 'move_angle_jitter',
    )),
    # 拖动反应归角色行为；音量与语音总开关仍为本机
    ('oracle.drag_reactions', _PROFILE, (
        'enabled', 'gesture_probability', 'flutter_probability',
        'alternating_probability', 'eye_open_probability', 'voice_probability',
    )),
    # 播放光晕颜色暂保留当前存储路径，未来迁移配色时须同步更新清单
    ('oracle', _APPEARANCE, ('body_appearance', 'outfit', 'pearl_bubble_color')),
    ('oracle.outfit_settings.maid.head', _APPEARANCE, _OUTFIT_PART_FIELDS),
    ('oracle.outfit_settings.maid.lace', _APPEARANCE, _OUTFIT_PART_FIELDS),
    ('oracle.outfit_settings.maid.apron', _APPEARANCE, _OUTFIT_PART_FIELDS),
    ('oracle.outfit_settings.maid.ribbon_up', _APPEARANCE, _OUTFIT_PART_FIELDS),
    ('oracle.outfit_settings.maid.ribbon_down', _APPEARANCE, _OUTFIT_PART_FIELDS),
    ('oracle.colors', _APPEARANCE, _COLOR_FIELDS),
    ('oracle.custom_colors', _APPEARANCE, _COLOR_FIELDS),
    ('oracle.prince_colors', _APPEARANCE, _COLOR_FIELDS),
    ('oracle.custom_appearance', _APPEARANCE, (
        'head_length', 'sleeve_root_width', 'sleeve_cuff_width', 'robe_length',
        'robe_flare', 'robe_hem_curve',
        'sleeve_cuff_radius', 'neck_width', 'chest_width', 'chest_height',
        'shoulder_width', 'inner_robe_enabled', 'inner_collar_enabled',
        'inner_collar_height', 'inner_collar_top_width', 'inner_collar_bottom_width',
        'neckline_shape', 'neckline_width', 'neckline_depth', 'neckline_height',
        'neckline_roundness', 'neckline_tip_radius', 'neckline_trim_enabled',
        'neckline_trim_width', 'neckline_trim_gap',
    )),
    ('oracle.custom_appearance.eye_1', _APPEARANCE, _EYE_FIELDS),
    ('oracle.custom_appearance.eye_2', _APPEARANCE, _EYE_FIELDS),
    ('oracle.custom_appearance.forehead', _APPEARANCE, _DECAL_FIELDS),
    ('oracle.custom_appearance.face', _APPEARANCE, _DECAL_FIELDS),
    ('oracle.custom_appearance.ear_body', _APPEARANCE, _EAR_FIELDS),
    ('oracle.custom_appearance.ear_part_1', _APPEARANCE, _EAR_FIELDS),
    ('oracle.custom_appearance.ear_part_2', _APPEARANCE, _EAR_FIELDS),
    ('oracle.custom_appearance.ear_part_3', _APPEARANCE, _EAR_FIELDS),
    ('oracle.custom_appearance.soft_part_1', _APPEARANCE, _SOFT_PART_FIELDS),
    ('oracle.custom_appearance.soft_part_2', _APPEARANCE, _SOFT_PART_FIELDS),
    ('oracle.custom_appearance.clothing_decal_1', _APPEARANCE, _CLOTHING_FIELDS),
    ('oracle.custom_appearance.clothing_decal_2', _APPEARANCE, _CLOTHING_FIELDS),
    ('oracle.custom_appearance.clothing_decal_3', _APPEARANCE, _CLOTHING_FIELDS),
    ('oracle.custom_appearance.cape', _APPEARANCE, (
        'enabled', 'length', 'color', 'neckline_shape', 'neckline_width', 'neckline_depth',
        'neckline_height', 'neckline_roundness', 'neckline_tip_radius', 'hem_trim_enabled',
        'hem_trim_color', 'hem_trim_width', 'hem_trim_gap',
    )),
    # 监视者是独立附加模块，本轮全部保留在本机，包括单个槽位的外观
    ('overseer', _LOCAL, (
        'enabled', 'appearance_mode', 'check_interval', 'appearance_probability',
        'duration_min', 'duration_max', 'cooldown_min', 'cooldown_max',
        'size', 'filament_count', 'color', 'withdraw_distance', 'reemerge_distance',
        'puppet_withdraw_distance', 'puppet_reemerge_distance',
        'relocation_probability', 'observation_probability', 'observation_interval',
        'safe_delay', 'emerge_seconds', 'withdraw_seconds',
    )),
    ('overseer.slots[]', _LOCAL, ('id', 'color', 'appearance', 'size', 'filament_count')),
), schema=AppConfig)


def scope_for(path: str) -> FieldScope:
    """查询完整叶路径；列表项使用 []，未知路径抛出 KeyError，不设默认归属"""
    return FIELD_SCOPES[path]


def paths_for(scope: FieldScope | str) -> tuple[str, ...]:
    """返回某一归属的稳定排序路径，不读取或修改任何配置值"""
    scope = FieldScope(scope)
    return tuple(sorted(path for path, owner in FIELD_SCOPES.items() if owner == scope))
