"""分享文件的只读默认值、本机调整和有界外观历史，不依赖 Qt 控件"""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..config import AppConfig
from ..ui_config import UiConfig
from .appearance import appearance_paths, apply_appearance
from .common import get_value, replace_fields, set_value
from .editing import ALL_PATHS, PresetLink, scope_paths
from .fields import paths_for
from .registry import FieldScope
from .profile import apply_profile

HISTORY_LIMIT = 10


def apply_values(config, values):
    changes = {}
    for path, value in values.items():
        if path not in ALL_PATHS:
            raise ValueError('个人调整包含不属于外观或角色设置的字段')
        set_value(changes, path, value)
    return replace_fields(config, changes)


def capture(config, kind, directory, *, include_inactive=False, strict=True):
    """贴图保存为不可变的内容缓存，历史恢复不依赖外部文件"""
    from ..oracle.graphics.face_assets import import_face_png
    active = scope_paths(kind, config.oracle.body_appearance)
    paths = (ALL_PATHS if kind == 'profile' else paths_for(FieldScope.APPEARANCE)) if include_inactive else active
    values = {path: get_value(config, path) for path in paths}
    directory = Path(directory).resolve()
    for path, value in tuple(values.items()):
        if not path.endswith('.image_path') or not value:
            continue
        source = Path(value).resolve()
        if not source.is_file():
            if path not in active or not strict:
                continue  # 不启用的另一主体可能保留待修复路径，不阻断当前主体编辑
            raise ValueError('外观贴图不存在，无法保存当前调整')
        if source.parent != directory:
            decal = get_value(config, path.removesuffix('.image_path'))
            try:
                values[path] = import_face_png(source, directory, decal).image_path
            except (OSError, ValueError):
                if path in active and strict:
                    raise
    return values


def normalized(values):
    return {key: value.lower() if isinstance(value, str) and value.startswith('#') else value
            for key, value in values.items()}


def complete_snapshot(values, kind, base):
    """旧快照缺失的新字段使用代码默认值，不能沿用切换前的角色参数"""
    config = apply_values(base, values)
    completed = {path: get_value(config, path)
                 for path in scope_paths(kind, config.oracle.body_appearance)}
    # 保留已保存的默认值及非当前主体分支，不读取可变的 TOML 或外观源文件
    return {**completed, **deepcopy(values)}


@dataclass
class PersonalEntry:
    kind: str
    source: PresetLink | None
    defaults: dict
    overrides: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    appearance_name: str = ''
    appearance_source: PresetLink | None = None

    @property
    def values(self):
        return {**self.defaults, **self.overrides}

    def update(self, config, directory, *, strict=True):
        current = capture(config, self.kind, directory, include_inactive=True, strict=strict)
        # 同一角色切换 Bell / 自定义时，未显示分支的已保存调整也保留
        self.overrides.update(current)
        baseline = normalized(self.defaults)
        self.overrides = {key: value for key, value in self.overrides.items()
                          if key not in baseline or normalized({key: value})[key] != baseline[key]}

    def remember(self, config, directory):
        values = capture(config, 'appearance', directory)
        signature = normalized(values)
        self.history = [item for item in self.history if normalized(item['values']) != signature]
        self.history.insert(0, {'name': self.appearance_name,
            'time': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'values': values,
            'source': self.appearance_source.serialize() if self.appearance_source else None})
        del self.history[HISTORY_LIMIT:]

    def restore(self, index, config, directory):
        selected = deepcopy(self.history[index])
        self.history.pop(index)
        self.remember(config, directory)
        self.appearance_name = selected['name']
        self.appearance_source = read_link(selected.get('source'))
        restored = apply_values(config, selected['values'])
        self.update(restored, directory)
        return restored

    def serialize(self):
        return {'kind': self.kind, 'source': self.source.serialize() if self.source else None,
                'defaults': deepcopy(self.defaults), 'overrides': deepcopy(self.overrides),
                'history': deepcopy(self.history), 'appearance_name': self.appearance_name,
                'appearance_source': self.appearance_source.serialize() if self.appearance_source else None}

    @classmethod
    def read(cls, data):
        kind = data['kind']
        if kind not in ('appearance', 'profile'):
            raise ValueError('无效的个人调整类型')
        source = read_link(data.get('source'))
        defaults, overrides = data['defaults'], data.get('overrides', {})
        allowed = ALL_PATHS if kind == 'profile' else paths_for(FieldScope.APPEARANCE)
        if any(key not in allowed for key in (*defaults, *overrides)):
            raise ValueError('个人调整包含不属于外观或角色设置的字段')
        config = AppConfig(ui=UiConfig('en'))
        defaults = complete_snapshot(defaults, kind, config)
        apply_values(config, {**defaults, **overrides})
        history = deepcopy(data.get('history', []))[:HISTORY_LIMIT]
        for item in history:
            datetime.fromisoformat(item['time'])
            read_link(item.get('source'))
            values = item['values']
            if any(path not in appearance_paths(values['oracle.body_appearance']) for path in values):
                raise ValueError('外观历史中包含非外观字段')
            item['values'] = complete_snapshot(values, 'appearance', config)
        return cls(kind, source, deepcopy(defaults), deepcopy(overrides), history,
                   str(data.get('appearance_name', '')), read_link(data.get('appearance_source')))


def read_link(source):
    if source:
        source = PresetLink(**{**source, 'path': Path(source['path'])})
        source.timestamp  # 校验来源标识和日期
    return source


class PersonalState:
    def __init__(self, data=None):
        data = data or {}
        self.autosave = data.get('autosave', True) is not False
        self.character_setup = deepcopy(data.get('character_setup', {}))
        self.entries = {}
        self.active = 'current'
        if data.get('version') == 2:
            for key, value in data.get('entries', {}).items():
                self.entries[key] = PersonalEntry.read(value)
            self.active = data.get('active', 'current')

    @staticmethod
    def key(kind, preset):
        # 同 ID 的新版有自己的调整，不会误套旧版字段；旧版本仍可恢复
        return f'{kind}:{preset.id}:{preset.revision}'

    def from_preset(self, kind, preset, config, directory):
        key = self.key(kind, preset)
        if key in self.entries:
            return key, deepcopy(self.entries[key])
        default = (apply_profile if kind == 'profile' else apply_appearance)(config, preset, directory)
        appearance = preset.appearance if kind == 'profile' else preset
        return key, PersonalEntry(kind, PresetLink.of(preset), capture(default, kind, directory),
                                  appearance_name=appearance.name, appearance_source=PresetLink.of(appearance))

    def serialize(self, key=None, entry=None):
        entries = {name: item.serialize() for name, item in self.entries.items()}
        if entry is not None:
            entries[key] = entry.serialize()
        return {'version': 2, 'autosave': self.autosave, 'active': key or self.active, 'entries': entries,
                'character_setup': deepcopy(self.character_setup)}

    def committed(self, key, entry):
        self.active = key
        self.entries[key] = deepcopy(entry)
