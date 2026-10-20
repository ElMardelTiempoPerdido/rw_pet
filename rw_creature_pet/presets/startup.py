"""角色库初始化与旧版行为参数升级，不改写分享文件的默认值"""
from copy import deepcopy
from dataclasses import dataclass, replace

from ..oracle.config import CustomAppearance, OracleColors
from .common import get_value
from .fields import paths_for
from .editing import PresetLink
from .personal import PersonalState, apply_values
from .profile_library import ProfileLibrary

BELL_PROFILE_ID = '797805d8-a9eb-4729-983e-32d7c0923f6f'
PRINCE_PROFILE_ID = '90fc64fe-b159-4f43-8af9-a5f6a93a607f'
CHARACTER_SETUP_VERSION = 1


def stage_character_upgrade(data):
    """在补齐配置字段前冻结旧文件实际持有的角色参数，重启后仍可继续确认"""
    saved = data.get('preset_state')
    state = deepcopy(saved) if isinstance(saved, dict) else {}
    setup = state.get('character_setup', {})
    if isinstance(setup, dict) and setup.get('version') == CHARACTER_SETUP_VERSION:
        return data, False
    active = state.get('entries', {}).get(state.get('active'), {})
    # 开发期间已经使用完整角色文件的记录无需当作旧版 settings 再次导入
    has_character = active.get('kind') == 'profile' and bool(active.get('source'))
    values = {}
    if not has_character:
        for path in paths_for('profile'):
            try:
                values[path] = get_value(data.get('config', {}), path)
            except (KeyError, AttributeError):
                continue
    state['character_setup'] = {'version': CHARACTER_SETUP_VERSION, 'pending': values}
    return {**data, 'preset_state': state}, True


@dataclass
class CharacterInitialization:
    config: object
    state: PersonalState
    notice: bool = False


def default_bell(defaults):
    return replace(defaults, oracle=replace(defaults.oracle, body_appearance='bell'))


def default_prince(defaults):
    """固定角色的初始入口，不改变启动时优先选择 Bell 的规则"""
    from ..oracle.config import OracleConfig
    return replace(defaults, oracle=replace(defaults.oracle, body_appearance='prince',
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
        body_appearance='custom', outfit='normal', custom_appearance=shape,
        custom_colors=colors, pearl_bubble_color='#00ff00'))


def prepare_character(config, store, *, library=None, defaults=None):
    """先准备选择和本机调整；确认提示及持久化由启动入口负责"""
    from ..settings_store import load_defaults
    library = library or ProfileLibrary()
    defaults = defaults or load_defaults()
    saved = store.load_preset_state()
    if not saved.get('character_setup'):
        # 直接打开设置的调用也使用原始文件，不从补齐后的 AppConfig 推断旧字段
        raw = store.read_document()
        saved = stage_character_upgrade(raw)[0]['preset_state']
    state = PersonalState(saved)
    pending = state.character_setup.get('pending', {})
    report = library.scan()
    choices = report.presets
    bell = next((p for p in choices if p.id == BELL_PROFILE_ID), None)
    bell = bell or next((p for p in choices if p.appearance.oracle.body_appearance == 'bell'), None)
    if not choices or (pending and bell is None):
        bell = library.export(default_bell(defaults), '手势之铃', preset_id=BELL_PROFILE_ID)
        choices = (*choices, bell)
    prior = state.entries.get(state.active)
    selected = None
    if not pending and prior and prior.kind == 'profile' and prior.source:
        selected = next((p for p in choices if p.id == prior.source.id), None)
    selected = selected or bell or choices[0]
    directory = store.path.parent/'appearance/images'
    valid_paths = {p.path for p in choices}
    valid_paths.update(p.path for group in report.duplicates for p in group)
    if (not pending and prior and prior.source and prior.source.id == selected.id
            and (prior.source.path in valid_paths or prior.source.revision == selected.revision)):
        # 已选角色的默认值与调整保持当前已载入版本，文件新版由用户主动切换
        key, entry = state.active, deepcopy(prior)
        if prior.source.revision == selected.revision:
            entry.source = PresetLink.of(selected)
    else:
        key, entry = state.from_preset('profile', selected, config, directory)
    effective = apply_values(config, entry.values)
    if pending:
        effective = apply_values(effective, pending)
        for path, value in pending.items():
            if value == entry.defaults[path]:
                entry.overrides.pop(path, None)
            else:
                entry.overrides[path] = value
    state.committed(key, entry)
    state.character_setup = {'version': CHARACTER_SETUP_VERSION, 'complete': True}
    return CharacterInitialization(effective, state, bool(pending))
