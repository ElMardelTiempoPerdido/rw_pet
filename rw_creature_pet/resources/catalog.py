"""声明式资源清单及纯查询接口，实际可用性由各资源加载器提供"""
from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
import re
import tomllib


CATALOG_PATH = Path(__file__).with_name('catalog.toml')


class CatalogError(ValueError):
    pass


class Availability(str, Enum):
    AVAILABLE = 'available'
    UNAVAILABLE = 'unavailable'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class Origin:
    title: str
    kind: str
    notes: str = ''


@dataclass(frozen=True)
class Source:
    origin: str
    root: str
    paths: tuple[str, ...]
    objects: tuple[str, ...] = ()
    notes: str = ''


@dataclass(frozen=True)
class Resource:
    title: str
    origins: tuple[str, ...]
    delivery: str
    loader: str
    check: str
    missing: str
    sources: tuple[Source, ...]
    cache: str = ''
    notes: str = ''


@dataclass(frozen=True)
class Feature:
    title: str
    resources: tuple[str, ...]
    sprites: tuple[str, ...] = ()
    notes: str = ''


@dataclass(frozen=True)
class SettingBinding:
    title: str
    paths: tuple[str, ...]
    features: tuple[str, ...]
    effect: str
    mode: str = 'all'
    option: str | None = None
    notes: str = ''


def _combine(states, mode='all'):
    states = tuple(states)
    # 无额外素材的计算绘制功能，在正常运行前提下可用
    if not states:
        return Availability.AVAILABLE
    decisive = Availability.UNAVAILABLE if mode == 'all' else Availability.AVAILABLE
    if decisive in states:
        return decisive
    if Availability.UNKNOWN in states:
        return Availability.UNKNOWN
    return Availability.AVAILABLE if mode == 'all' else Availability.UNAVAILABLE


@dataclass(frozen=True)
class ResourceCatalog:
    required: tuple[str, ...]
    origins: Mapping[str, Origin]
    resources: Mapping[str, Resource]
    features: Mapping[str, Feature]
    settings: Mapping[str, SettingBinding]

    def validate_settings(self, known_paths):
        """检查真实配置叶路径，包括列表项；不创建配置对象或 Qt 控件"""
        declared = {path for item in self.settings.values() for path in item.paths}
        declared.update(path for item in self.resources.values() for source in item.sources
                        if source.root == 'setting' for path in source.paths)
        if stale := declared - set(known_paths):
            raise CatalogError('资源清单引用了不存在的配置字段：'+', '.join(sorted(stale)))

    def bindings_for(self, path, *, option=None):
        """option 指定时仅返回该选项绑定及整个控件的绑定"""
        return tuple((key, item) for key, item in self.settings.items()
                     if path in item.paths and (option is None or item.option in (None, option)))

    def impacts_for(self, resource_id):
        """反查素材影响的设置；related 仅供说明，不能据此禁用整个控件"""
        if resource_id not in self.resources:
            raise KeyError(resource_id)
        affected = {key for key, item in self.features.items() if resource_id in item.resources}
        return tuple((key, item) for key, item in self.settings.items()
                     if affected.intersection(item.features))

    def _validate_states(self, states):
        unknown = set(states) - self.resources.keys()
        if unknown:
            raise CatalogError('未知资源状态：'+', '.join(sorted(unknown)))
        if any(not isinstance(value, Availability) for value in states.values()):
            raise CatalogError('资源状态必须使用 Availability；未探测不能当成缺失')

    def required_state(self, states):
        self._validate_states(states)
        return _combine(states.get(key, Availability.UNKNOWN) for key in self.required)

    def feature_state(self, feature_id, states):
        """仅判断该功能的额外素材；不代替启动检查、角色能力或行为开关"""
        self._validate_states(states)
        return _combine(states.get(key, Availability.UNKNOWN)
                        for key in self.features[feature_id].resources)

    def setting_state(self, binding_id, states):
        binding = self.settings[binding_id]
        self._validate_states(states)
        if binding.effect == 'related':
            # 共用总开关、逐槽贴图等只登记关联，不能整体判为不可用
            return Availability.UNKNOWN
        return _combine((self.feature_state(key, states) for key in binding.features), binding.mode)


def _record(cls, value, location):
    if not isinstance(value, dict):
        raise CatalogError(f'{location} 必须为表')
    allowed = {field.name for field in fields(cls)}
    if extra := set(value) - allowed:
        raise CatalogError(f'{location} 含未知字段：{sorted(extra)}')
    converted = dict(value)
    for name in ('paths', 'objects', 'origins', 'resources', 'sprites', 'features'):
        if name in converted:
            converted[name] = _strings(converted[name], f'{location}.{name}')
    if cls is Resource and 'sources' in converted:
        if not isinstance(converted['sources'], list) or not converted['sources']:
            raise CatalogError(f'{location}.sources 必须为非空数组')
        converted['sources'] = tuple(_record(Source, item, f'{location}.sources[{index}]')
                                     for index, item in enumerate(converted['sources']))
    try:
        result = cls(**converted)
    except TypeError as exc:
        raise CatalogError(f'{location}: {exc}') from exc
    for field in fields(cls):
        item = getattr(result, field.name)
        if field.name not in ('paths', 'objects', 'origins', 'resources', 'sprites', 'features', 'sources'):
            if field.name == 'option' and item is None:
                continue
            if not isinstance(item, str):
                raise CatalogError(f'{location}.{field.name} 必须为字符串')
            if field.name not in ('notes', 'cache') and not item.strip():
                raise CatalogError(f'{location}.{field.name} 不可为空')
    return result


def _strings(value, location):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise CatalogError(f'{location} 必须为字符串数组')
    if len(set(value)) != len(value):
        raise CatalogError(f'{location} 含重复项')
    return tuple(value)


def _references(values, known, location):
    if missing := set(values) - set(known):
        raise CatalogError(f'{location} 引用了未知项：{sorted(missing)}')


def _choice(value, choices, location):
    if value not in choices:
        raise CatalogError(f'{location} 不支持 {value!r}')


def parse_catalog(data):
    """严格校验清单，拒绝拼错的字段和悬空引用，不执行 loader 字符串"""
    expected = {'format_version', 'required', 'origins', 'resources', 'features', 'settings'}
    if not isinstance(data, dict) or set(data) != expected:
        raise CatalogError('资源清单必须包含且仅包含：'+', '.join(sorted(expected)))
    if type(data['format_version']) is not int or data['format_version'] != 1:
        raise CatalogError('不支持的资源清单版本')
    groups = {}
    for name, cls in (('origins', Origin), ('resources', Resource), ('features', Feature), ('settings', SettingBinding)):
        if not isinstance(data[name], dict) or not data[name]:
            raise CatalogError(f'{name} 必须为非空表')
        group = {}
        for key, value in data[name].items():
            if not re.fullmatch(r'[a-z][a-z0-9_]*', key):
                raise CatalogError(f'无效的稳定 ID：{name}.{key}')
            group[key] = _record(cls, value, f'{name}.{key}')
        groups[name] = MappingProxyType(group)
    required = _strings(data['required'], 'required')
    _references(required, groups['resources'], 'required')
    for key, item in groups['origins'].items():
        _choice(item.kind, ('base_game', 'dlc', 'bundle', 'user'), f'origins.{key}.kind')
    for key, item in groups['resources'].items():
        if not item.origins:
            raise CatalogError(f'resources.{key}.origins 不可为空')
        _references(item.origins, groups['origins'], f'resources.{key}.origins')
        _choice(item.delivery, ('extract', 'files', 'resolved', 'bundled', 'configured'), f'resources.{key}.delivery')
        for source in item.sources:
            _references((source.origin,), groups['origins'], f'resources.{key}.sources')
            _choice(source.root, ('game', 'package', 'setting'), f'resources.{key}.sources.root')
            if not source.paths:
                raise CatalogError(f'resources.{key}.sources.paths 不可为空')
            if source.root != 'setting':
                for path in source.paths:
                    if (PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts
                            or '\\' in path or ':' in path or any(c in path for c in '*?[]')):
                        raise CatalogError(f'资源路径必须为明确的相对路径：{path}')
    for key, item in groups['features'].items():
        _references(item.resources, groups['resources'], f'features.{key}.resources')
        if item.sprites and 'main_atlas' not in item.resources:
            raise CatalogError(f'features.{key} 声明 sprites 时必须依赖 main_atlas')
    seen = set()
    for key, item in groups['settings'].items():
        if not item.paths or not item.features:
            raise CatalogError(f'settings.{key} 必须指定 paths 与 features')
        _references(item.features, groups['features'], f'settings.{key}.features')
        _choice(item.effect, ('unavailable', 'related'), f'settings.{key}.effect')
        _choice(item.mode, ('all', 'any'), f'settings.{key}.mode')
        for path in item.paths:
            pair = (path, item.option)
            if pair in seen:
                raise CatalogError(f'重复的设置绑定：{pair}')
            seen.add(pair)
    return ResourceCatalog(required, **groups)


def load_catalog(path=None):
    source = Path(path) if path is not None else CATALOG_PATH
    try:
        return parse_catalog(tomllib.loads(source.read_text(encoding='utf-8')))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise CatalogError(f'读取资源清单失败：{source}: {exc}') from exc
