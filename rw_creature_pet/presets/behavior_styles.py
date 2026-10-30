"""行为风格库：明确字段归属、逐条校验、本地覆盖与一次性参数快照"""
from collections import Counter
from dataclasses import dataclass, fields
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re
import sys
import tomllib
from types import MappingProxyType

from ..config import AppConfig
from ..oracle.behavior_config import DailyActivityConfig, ReadingConfig
from ..oracle.drift_config import DriftConfig
from ..oracle.drag_reaction_config import DragReactionConfig
from ..oracle.mouse_avoidance_config import MouseAvoidanceConfig
from ..oracle.style_config import DIMENSIONS, StyleSelection
from ..shared.paths import PACKAGE_ROOT
from .common import get_value, replace_fields, set_value


def _group(prefix, cls):
    return tuple(prefix+'.'+f.name for f in fields(cls))


_PEARL_READING = ('approach_weight', 'recall_weight', 'orbit_weight', 'observe_distance', 'recall_distance')
DIMENSION_PATHS = {
    'daily_activity': (*_group('oracle.daily_activity', DailyActivityConfig),
                       'oracle.float_speed', 'oracle.base_speed', 'oracle.cross_edge_probability'),
    'drift': (*_group('oracle.drift', DriftConfig), 'oracle.antigravity_probability',
              'oracle.antigravity_duration_seconds', 'oracle.drift_speed'),
    'mouse_attention': ('interaction.hover_radius', 'interaction.hover_dwell_seconds',
                        'interaction.hover_probability', 'interaction.hover_open_probability',
                        'interaction.petting_enabled', 'interaction.petting_seconds', 'interaction.petting_grace_seconds'),
    'mouse_avoidance': (*_group('oracle.mouse_avoidance', MouseAvoidanceConfig),
                        'interaction.hover_avoidance_enabled'),
    'drag_reactions': (*_group('oracle.drag_reactions', DragReactionConfig),
                       'oracle.drag_projection_probability', 'oracle.drag_projection_cooldown_seconds'),
    'reading_habits': (*(f'oracle.reading.{f.name}' for f in fields(ReadingConfig)
                        if f.name not in _PEARL_READING), 'oracle.pearl_playback_probability'),
    'pearl_interaction': (*(f'oracle.reading.{name}' for name in _PEARL_READING),
                          'oracle.pearl_matrix_avoid_radius', 'oracle.pearl_follow_width', 'oracle.pearl_follow_height'),
}
PATH_DIMENSIONS = {path: dimension for dimension, paths in DIMENSION_PATHS.items() for path in paths}
SELECTION_PREFIX = 'oracle.behavior_styles.'
SELECTION_PATHS = tuple(SELECTION_PREFIX+dimension+'.'+name for dimension in DIMENSIONS for name in ('id', 'version'))


def set_selection(config, dimension, selection):
    changes = {}
    set_value(changes, SELECTION_PREFIX+dimension+'.id', selection.id)
    set_value(changes, SELECTION_PREFIX+dimension+'.version', selection.version)
    return replace_fields(config, changes)


@dataclass(frozen=True, slots=True)
class BehaviorStyle:
    id: str
    dimension: str
    order: int
    name_zh: str
    name_en: str
    description_zh: str
    description_en: str
    values: object

    @property
    def version(self):
        # 改名与排序不影响参数版本；内容变动无需手工维护版本号
        payload = json.dumps(dict(self.values), sort_keys=True, separators=(',', ':'), allow_nan=False)
        return 'v1:'+sha256(payload.encode('utf-8')).hexdigest()

    def apply(self, config):
        changes = {}
        for path, value in self.values.items():
            set_value(changes, path, value)
        config = replace_fields(config, changes)
        return set_selection(config, self.dimension, StyleSelection(self.id, self.version))


def _validate(data):
    names = {'id', 'dimension', 'order', 'name_zh', 'name_en', 'description_zh', 'description_en', 'values'}
    if not isinstance(data, dict) or set(data) != names:
        raise ValueError('Incomplete or unknown style fields')
    if not isinstance(data['id'], str) or not re.fullmatch(r'[a-z0-9_.-]{1,120}', data['id']):
        raise ValueError('Invalid style ID')
    dimension = data['dimension']
    if not isinstance(dimension, str) or dimension not in DIMENSIONS:
        raise ValueError('Unknown style dimension')
    if type(data['order']) is not int:
        raise ValueError('Style order must be an integer')
    for name in ('name_zh', 'name_en', 'description_zh', 'description_en'):
        if not isinstance(data[name], str) or not data[name].strip() or len(data[name]) > 1000:
            raise ValueError('Invalid style text: '+name)
    values = data['values']
    # 旧关注风格仅补齐新增摸摸字段，原有字段缺失或未知字段仍按错误处理
    legacy = {'interaction.hover_radius', 'interaction.hover_dwell_seconds',
              'interaction.hover_probability', 'interaction.hover_open_probability'}
    if (dimension == 'mouse_attention' and isinstance(values, dict)
            and legacy <= set(values) <= set(DIMENSION_PATHS[dimension])):
        values = {'interaction.petting_enabled': True, 'interaction.petting_seconds': 1.5,
                  'interaction.petting_grace_seconds': .6, **values}
    if not isinstance(values, dict) or set(values) != set(DIMENSION_PATHS[dimension]):
        raise ValueError('Style must contain exactly its dimension parameters')
    defaults, changes, normalized = AppConfig(), {}, {}
    for path, value in values.items():
        default = get_value(defaults, path)
        valid = (type(value) in (float, int) and isfinite(value) if type(default) is float
                 else type(value) is type(default))
        if not valid:
            raise ValueError('Invalid style parameter type: '+path)
        normalized[path] = float(value) if type(default) is float else value
        set_value(changes, path, normalized[path])
    replace_fields(defaults, changes)  # 范围、最小/最大与权重约束复用实际运行配置
    return BehaviorStyle(**{**data, 'values': MappingProxyType(normalized)})


@dataclass(frozen=True, slots=True)
class BehaviorStyleLibrary:
    styles: tuple
    errors: tuple = ()

    def find(self, identifier, dimension):
        return next((s for s in self.styles if s.id == identifier and s.dimension == dimension), None)

    def for_dimension(self, dimension):
        return tuple(sorted((s for s in self.styles if s.dimension == dimension), key=lambda s: (s.order, s.id)))

    @classmethod
    def load(cls, directory=None):
        explicit_directory = directory is not None
        directory = Path(directory) if directory is not None else default_style_directory()
        entries, errors = {}, []
        for filename in ('builtin.toml', 'local.toml'):
            path = directory/filename
            if (filename == 'builtin.toml' and not explicit_directory and not path.exists()
                    and getattr(sys, 'frozen', False)):
                path = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))/'presets/behavior_styles'/filename
            if filename == 'local.toml' and not path.exists():
                continue
            try:
                with path.open('rb') as stream:
                    data = tomllib.load(stream)
                if (type(data.get('format_version')) is not int or data['format_version'] != 1
                        or set(data)-{'format_version', 'styles'} or not isinstance(data.get('styles', []), list)):
                    raise ValueError('Unsupported style library format')
            except (OSError, ValueError) as exc:
                errors.append(f'{filename}: {exc}')
                continue
            rows = data.get('styles', [])
            counts = Counter(row.get('id') for row in rows if isinstance(row, dict) and isinstance(row.get('id'), str))
            for row in rows:
                try:
                    if not isinstance(row, dict) or not isinstance(row.get('id'), str):
                        raise ValueError('Missing style ID')
                    identifier = row['id']
                    if counts[identifier] != 1:
                        raise ValueError('Duplicate style ID: '+identifier)
                    merged = row
                    if filename == 'local.toml' and identifier in entries:
                        base = entries[identifier]
                        if row.get('dimension', base.dimension) != base.dimension:
                            raise ValueError('Cannot change the dimension of a style')
                        if not isinstance(row.get('values', {}), dict):
                            raise ValueError('Invalid style values')
                        merged = {**{f.name: getattr(base, f.name) for f in fields(base)}, **row,
                                  'values': {**base.values, **row.get('values', {})}}
                    entries[identifier] = _validate(merged)
                except (TypeError, ValueError, OverflowError) as exc:
                    errors.append(f'{filename} / {row.get("id", "?") if isinstance(row, dict) else "?"}: {exc}')
        return cls(tuple(entries.values()), tuple(errors))


def default_style_directory():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent/'presets/behavior_styles'
    return PACKAGE_ROOT.parent/'presets/behavior_styles'
