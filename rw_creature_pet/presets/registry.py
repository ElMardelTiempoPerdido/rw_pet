"""显式登记配置叶字段，并按类型检查遗漏、过期和重复声明"""
from collections.abc import Iterable, Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType, UnionType
from typing import Union, get_args, get_origin, get_type_hints


class FieldScope(str, Enum):
    APPEARANCE = 'appearance'  # 外观配置
    PROFILE = 'profile'  # 完整预设的行为参数，外观另行引用
    LOCAL = 'local'  # 本机偏好，不参与共享预设


def schema_paths(schema: type) -> frozenset[str]:
    """从声明类型读取叶路径，不实例化配置，也不依赖列表当前是否为空"""
    if not isinstance(schema, type) or not is_dataclass(schema):
        raise TypeError('配置根类型必须为 dataclass')
    return frozenset(_walk_type(schema, ''))


def _walk_type(annotation, path):
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, UnionType):
        members = tuple(item for item in args if item is not type(None))
        if len(members) == 1:
            yield from _walk_type(members[0], path)
            return
        raise TypeError(f'尚未支持的配置联合类型：{path}: {annotation}')
    if isinstance(annotation, type) and is_dataclass(annotation):
        hints = get_type_hints(annotation)
        for field in fields(annotation):
            child = f'{path}.{field.name}' if path else field.name
            yield from _walk_type(hints[field.name], child)
        return
    if origin in (list, tuple):
        if len(args) == 1 or (origin is tuple and len(args) == 2 and args[1] is Ellipsis):
            # 结构化列表按 [] 登记每项的字段；标量列表（如允许的边缘）整体登记
            item_paths = tuple(_walk_type(args[0], path+'[]'))
            if item_paths == (path+'[]',):
                yield path
            else:
                yield from item_paths
            return
        raise TypeError(f'尚未支持的配置列表类型：{path}: {annotation}')
    if annotation in (bool, int, float, str, Path):
        yield path
        return
    # 不把不认识的对象或字典当作一个整体静默放行，避免遗漏其中的新字段
    raise TypeError(f'尚未支持的配置字段类型：{path}: {annotation}')


def validate_registry(registry: Mapping[str, FieldScope], schema: type) -> None:
    """校验每个实际字段恰好拥有有效归属，报错列出完整路径"""
    expected = schema_paths(schema)
    registered = set(registry)
    errors = []
    if missing := expected-registered:
        errors.append('未登记字段：'+', '.join(sorted(missing)))
    if stale := registered-expected:
        errors.append('配置中不存在的登记：'+', '.join(sorted(stale)))
    invalid = [path for path, scope in registry.items() if not isinstance(scope, FieldScope)]
    if invalid:
        errors.append('无效字段归属：'+', '.join(sorted(invalid)))
    if errors:
        raise ValueError('\n'.join(errors))


def build_registry(
    groups: Iterable[tuple[str, FieldScope, tuple[str, ...]]], *, schema: type,
) -> Mapping[str, FieldScope]:
    """分组只减少重复前缀；所有字段名必须显式列出，不能按前缀兜底"""
    registry = {}
    for prefix, scope, names in groups:
        for name in names:
            path = f'{prefix}.{name}' if prefix else name
            if path in registry:
                raise ValueError(f'重复登记字段：{path}')
            registry[path] = scope
    validate_registry(registry, schema)
    return MappingProxyType(registry)
