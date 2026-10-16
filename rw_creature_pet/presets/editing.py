"""预设编辑基准和来源，独立于运行配置及 Qt 控件"""
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from ..config import AppConfig
from ..ui_config import UiConfig
from .appearance import appearance_paths
from .common import get_value, validate_metadata
from .fields import paths_for
from .registry import FieldScope

ALL_PATHS = (*paths_for(FieldScope.APPEARANCE), *paths_for(FieldScope.PROFILE))


def scope_paths(kind, body):
    return (*appearance_paths(body), *(paths_for(FieldScope.PROFILE) if kind == 'profile' else ()))


def snapshot(config, paths, image=None):
    values = {}
    for path in paths:
        value = get_value(config, path)
        if path.endswith('.image_path') and value:
            try:
                from ..oracle.graphics.face_assets import image_size_limit, read_face_png
                source = image(value) if image else Path(value).expanduser()
                decal = get_value(config, path.removesuffix('.image_path'))
                pixels = read_face_png(source, image_size_limit(decal))
                size = f'{pixels.width()}x{pixels.height()}:'.encode('ascii')
                value = 'pixels:'+sha256(size+bytes(pixels.constBits())).hexdigest()
            except (OSError, ValueError):
                value = 'missing:'+value
        elif isinstance(value, str) and value.startswith('#'):
            value = value.lower()
        values[path] = value
    return values


def preset_snapshot(preset, kind):
    appearance = preset.appearance if kind == 'profile' else preset
    result = snapshot({'oracle': appearance.oracle}, appearance_paths(appearance.oracle.body_appearance),
                      appearance.image)
    if kind == 'profile':
        result.update(snapshot(preset.config, paths_for(FieldScope.PROFILE)))
    return result


@dataclass(frozen=True)
class PresetLink:
    id: str
    name: str
    updated_at: str
    path: Path
    revision: str

    @classmethod
    def of(cls, preset):
        return cls(preset.id, preset.name, preset.updated_at, preset.path, preset.revision)

    @property
    def timestamp(self):
        return validate_metadata(self.id, self.name, self.updated_at)

    def serialize(self):
        return {**asdict(self), 'path': str(self.path)}


class PresetEditingState:
    def __init__(self, data=None):
        self.baseline = snapshot(AppConfig(ui=UiConfig('en')), ALL_PATHS)
        self.profile_baseline = {}
        self.sources = {'appearance': None, 'profile': None}
        data = data or {}
        if data.get('version') != 1:
            return
        values = data.get('baseline', {})
        if isinstance(values, dict):
            for path, value in values.items():
                default = self.baseline.get(path)
                if path in self.baseline and (type(value) is type(default) or
                        type(default) is float and type(value) in (int, float)):
                    self.baseline[path] = value
        profile_values = data.get('profile_baseline', {})
        if isinstance(profile_values, dict):
            self.profile_baseline = {key: value for key, value in profile_values.items()
                if key in self.baseline and (type(value) is type(self.baseline[key]) or
                    type(self.baseline[key]) is float and type(value) in (int, float))}
        for kind in self.sources:
            try:
                source = data.get('sources', {})[kind]
                validate_metadata(source['id'], source['name'], source['updated_at'])
                if not isinstance(source['revision'], str) or len(source['revision']) != 64:
                    continue
                self.sources[kind] = PresetLink(**{**source, 'path': Path(source['path'])})
            except (KeyError, TypeError, ValueError):
                pass

    def record(self, kind, preset):
        values = preset_snapshot(preset, kind)
        self.baseline.update(values)
        self.sources[kind] = PresetLink.of(preset)
        if kind == 'profile':
            self.profile_baseline = values
            self.sources['appearance'] = PresetLink.of(preset.appearance)

    def baseline_for(self, kind):
        # 单独保存外观不能确认完整预设中外观引用及行为的组合也已保存
        return {**self.baseline, **self.profile_baseline} if kind == 'profile' and self.sources['profile'] else self.baseline

    def at_risk(self, current, incoming, paths, kind='appearance'):
        before, after = snapshot(current, paths), snapshot(incoming, paths)
        baseline = self.baseline_for(kind)
        return tuple(path for path in paths if before[path] != after[path]
                     and before[path] != baseline[path])

    def matches(self, config, preset, kind):
        expected = preset_snapshot(preset, kind)
        return snapshot(config, expected) == expected

    def serialize(self):
        return {'version': 1, 'baseline': dict(self.baseline), 'profile_baseline': dict(self.profile_baseline),
                'sources': {kind: value.serialize() if value else None for kind, value in self.sources.items()}}
