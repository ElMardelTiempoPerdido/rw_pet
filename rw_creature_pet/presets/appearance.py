"""外观预设格式、边界校验与独立于本机偏好的配置合并"""
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import UUID

from ..oracle.config import OracleConfig
from ..shared.messages import Message
from .fields import paths_for
from .registry import FieldScope

FORMAT = 'rw-creature-pet.appearance'
VERSION = 1
MANIFEST = 'appearance.json'
MAX_MANIFEST_BYTES = 256*1024


def appearance_paths(body):
    if body not in ('bell', 'custom'):
        raise ValueError('主体外观必须为 bell 或 custom')
    excluded = ('oracle.custom_colors.', 'oracle.custom_appearance.') if body == 'bell' else ('oracle.colors.',)
    return tuple(path for path in paths_for(FieldScope.APPEARANCE) if not path.startswith(excluded))


def get_value(obj, path):
    for name in path.split('.'):
        obj = obj[name] if isinstance(obj, dict) else getattr(obj, name)
    return obj


def set_value(mapping, path, value):
    *parts, name = path.split('.')
    for part in parts:
        mapping = mapping.setdefault(part, {})
    mapping[name] = value


def appearance_mapping(oracle):
    source, result = {'oracle': asdict(oracle)}, {}
    for path in appearance_paths(oracle.body_appearance):
        set_value(result, path, get_value(source, path))
    return result


def _leaves(data, allowed, prefix=''):
    if not isinstance(data, dict):
        raise ValueError('外观配置必须为对象')
    for key, value in data.items():
        path = f'{prefix}.{key}' if prefix else key
        if path in allowed:
            if isinstance(value, (dict, list)):
                raise ValueError(Message('外观字段格式无效：{path}', path=path))
            yield path, value
        elif any(item.startswith(path+'.') for item in allowed):
            yield from _leaves(value, allowed, path)
        else:
            raise ValueError(Message('不属于此外观的配置字段：{path}', path=path))


def validate_config(data):
    if not isinstance(data, dict) or not isinstance(data.get('oracle'), dict):
        raise ValueError('外观配置必须包含 oracle 对象')
    body = data['oracle'].get('body_appearance')
    allowed = appearance_paths(body)
    # 缺失字段使用格式对应的代码默认值，不能继承上一个角色或用户修改过的 TOML
    defaults = appearance_mapping(replace(OracleConfig(), body_appearance=body))
    for path, value in _leaves(data, allowed):
        set_value(defaults, path, value)
    return OracleConfig.from_mapping(defaults['oracle'])


def validate_metadata(identifier, name, updated_at):
    try:
        if not isinstance(identifier, str) or str(UUID(identifier)) != identifier:
            raise ValueError
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError
        if any(ord(char) < 32 for char in name):
            raise ValueError
        if not isinstance(updated_at, str):
            raise ValueError
        stamp = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError('外观预设的 ID、名称或更新时间无效') from None
    return stamp


def image_paths(oracle):
    return tuple(path for path in appearance_paths(oracle.body_appearance) if path.endswith('.image_path'))


def package_image(directory, reference):
    # Windows 驱动器、UNC、ADS、反斜线和父目录均不属于可移植的包内相对路径
    path = PurePosixPath(reference)
    if (not reference or '\\' in reference or ':' in reference or path.is_absolute()
            or PureWindowsPath(reference).drive or '..' in path.parts):
        raise ValueError(Message('贴图必须使用包内相对路径：{path}', path=reference))
    root = Path(directory).resolve()
    resolved = (root/reference).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(Message('贴图路径超出了外观目录：{path}', path=reference))
    return resolved


def checked_image(path):
    # 与设置面板共用 PNG 格式、尺寸、动画及文件大小校验
    from ..oracle.graphics.face_assets import read_face_png
    read_face_png(path)
    return Path(path)


@dataclass(frozen=True, slots=True)
class AppearancePreset:
    id: str
    name: str
    updated_at: str
    oracle: OracleConfig
    path: Path

    @property
    def timestamp(self):
        return validate_metadata(self.id, self.name, self.updated_at)

    def image(self, reference):
        return checked_image(package_image(self.path.parent, reference))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(Message('外观文件包含重复字段：{path}', path=key))
        result[key] = value
    return result


def _invalid_number(value):
    raise ValueError('外观文件包含无效数值')


def load_appearance(path):
    path = Path(path).resolve()
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError('外观配置文件不能超过 256 KB')
    data = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_object,
                      parse_constant=_invalid_number)
    if not isinstance(data, dict) or data.get('type') != FORMAT:
        raise ValueError('请选择有效的外观预设文件')
    if type(data.get('version')) is not int or data['version'] != VERSION:
        raise ValueError('不支持此外观预设版本，请使用匹配版本的桌宠')
    if set(data) != {'type', 'version', 'id', 'name', 'updated_at', 'config'}:
        raise ValueError('外观预设文件字段不完整或包含未知字段')
    validate_metadata(data['id'], data['name'], data['updated_at'])
    oracle = validate_config(data['config'])
    preset = AppearancePreset(data['id'], data['name'], data['updated_at'], oracle, path)
    source = {'oracle': oracle}
    for key in image_paths(oracle):
        reference = get_value(source, key)
        if reference:
            preset.image(reference)
        else:
            decal = get_value(source, key.removesuffix('.image_path'))
            if decal.enabled and getattr(decal, 'kind', 'png') == 'png':
                raise ValueError(Message('已启用的部件缺少贴图：{path}', path=key))
    return preset


def apply_appearance(config, preset, asset_directory):
    """先验证并缓存全部引用，再返回新配置；失败不会改写当前设置"""
    from ..oracle.graphics.face_assets import import_face_png
    values = appearance_mapping(preset.oracle)
    for path in image_paths(preset.oracle):
        reference = get_value(values, path)
        if reference:
            decal = get_value({'oracle': preset.oracle}, path.removesuffix('.image_path'))
            imported = import_face_png(preset.image(reference), asset_directory, decal)
            # 缓存只改变路径，不改变原本关闭的开关、名称及 PNG 以外的耳机形状
            set_value(values, path, imported.image_path)
    merged = {'oracle': asdict(config.oracle)}
    for path in appearance_paths(preset.oracle.body_appearance):
        set_value(merged, path, get_value(values, path))
    return replace(config, oracle=OracleConfig.from_mapping(merged['oracle']))
