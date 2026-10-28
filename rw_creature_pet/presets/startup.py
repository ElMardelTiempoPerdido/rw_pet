"""角色工作目录初始化与旧版外观、行为迁移，不改写发行默认值"""
from copy import deepcopy
from dataclasses import dataclass, replace

from ..oracle.config import CustomAppearance, OracleColors
from ..shared.messages import Message
from .common import get_value
from .fields import paths_for
from .personal import PersonalState, apply_values
from .profile_library import ProfileLibrary

BELL_PROFILE_ID = '797805d8-a9eb-4729-983e-32d7c0923f6f'
PRINCE_PROFILE_ID = '90fc64fe-b159-4f43-8af9-a5f6a93a607f'


def stage_character_upgrade(data):
    """在补齐配置字段前冻结旧文件实际持有的角色参数，重启后仍可继续确认"""
    saved = data.get('preset_state')
    state = deepcopy(saved) if isinstance(saved, dict) else {}
    if state.get('version') == 3:
        return data, False
    if 'directory_migration' in state:
        return data, False
    from .editing import ALL_PATHS
    raw_values = {}
    for path in ALL_PATHS:
        try:
            raw_values[path] = get_value(data.get('config', {}), path)
        except (KeyError, AttributeError):
            pass
    legacy_pending = state.get('character_setup', {}).get('pending')
    if isinstance(legacy_pending, dict):
        # 更早版本已补齐过 settings 时，沿用当时冻结的实际行为字段
        raw_values = {path: value for path, value in raw_values.items() if path not in paths_for('profile')}
        raw_values.update(legacy_pending)
    state['directory_migration'] = {'raw_values': raw_values}
    return {**data, 'preset_state': state}, True


@dataclass
class CharacterInitialization:
    config: object
    state: PersonalState
    notice: bool = False


def default_bell(defaults):
    return replace(defaults, oracle=replace(defaults.oracle, body_appearance='bell', voice='bell'))


def default_prince(defaults):
    """固定角色的初始入口，不改变启动时优先选择 Bell 的规则"""
    from ..oracle.config import OracleConfig
    return replace(defaults, oracle=replace(defaults.oracle, body_appearance='prince', voice='none',
        prince_colors=OracleConfig().prince_colors, outfit='normal', pearl_bubble_color='#b6a1cc'))


def default_custom(defaults):
    """新建角色的基底，不改变文件缺省值、已有角色或 Bell

    来自 appearance-default-4ec922f7e5b047178e3276ceaa735bee 的导出参数
    直接内置数值，用户移动或删除外观库后仍可新建角色
    """
    shape = CustomAppearance(head_length=0.9414414414414414,
        inner_robe_enabled=False, inner_collar_enabled=False, neckline_depth=3.)
    colors = OracleColors(skin='#c5c9cf', robe_top='#f5f5f5', robe_bottom='#c6cfdc',
        inner_robe='#ffffff', collar_trim='#d8dbdf', arm='#9fa2a8', arm_highlight='#dfd6d2',
        joints='#113246', pearl_primary='#0000ff', pearl_secondary='#ff0000', pearl_glyph='#9ca5bc')
    return replace(defaults, oracle=replace(defaults.oracle,
        body_appearance='custom', voice='none', outfit='normal', custom_appearance=shape,
        custom_colors=colors, pearl_bubble_color='#00ff00'))


def prepare_character(config, store, *, library=None, defaults=None):
    """先准备选择和本机调整；确认提示及持久化由启动入口负责"""
    from ..settings_store import load_defaults
    library = library or ProfileLibrary()
    defaults = defaults or load_defaults()
    saved = store.load_preset_state()
    if saved.get('version') != 3:
        # 直接打开设置的调用也使用原始文件，不从补齐后的 AppConfig 推断旧字段
        raw = store.read_document()
        saved = stage_character_upgrade(raw)[0]['preset_state']
    from .workspace import ensure_workspace
    from .migration import migrate
    report = library.scan()
    choices = report.presets
    bell = next((p for p in choices if p.id == BELL_PROFILE_ID), None)
    bell = bell or next((p for p in choices if p.appearance.oracle.body_appearance == 'bell'), None)
    if not choices:
        if report.errors:
            raise ValueError(Message('角色目录无法读取，请先修复；原文件未改动：{path}', path=report.errors[0][0]))
        bell = library.export(default_bell(defaults), '手势之铃', preset_id=BELL_PROFILE_ID)
        choices = (*choices, bell)
    notice = False
    if saved.get('version') == 3:
        state = PersonalState(saved, library=library)
    else:
        fallback = ensure_workspace((bell or choices[0]).path)
        state, notice = migrate(store, library, config, saved, fallback)
    if state.active not in state.entries:
        selected = ensure_workspace((bell or choices[0]).path)
        key, entry = state.from_preset('profile', selected, config, store.path.parent/'appearance/images')
        state.committed(key, entry)
    effective = apply_values(config, state.entries[state.active].values)
    return CharacterInitialization(effective, state, notice)
