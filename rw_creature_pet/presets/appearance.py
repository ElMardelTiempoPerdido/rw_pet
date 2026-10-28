"""外观预设格式、边界校验与独立于本机偏好的配置合并"""
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ..oracle.config import OracleConfig
from ..oracle.characters import CHARACTERS, PRINCE_COLOR_NAMES
from ..shared.messages import Message
from .fields import paths_for
from .registry import FieldScope
from .common import (get_value, set_value, scoped_leaves, validate_metadata, package_path, read_document,
                     revision_for)

FORMAT = 'rw-creature-pet.appearance'
VERSION = 1
MANIFEST = 'appearance.json'


def appearance_paths(body):
    if body not in CHARACTERS:
        raise ValueError('主体外观必须为 bell / custom / prince')
    if body == 'prince':
        allowed = {'oracle.body_appearance', 'oracle.pearl_bubble_color',
                   *('oracle.prince_colors.'+name for name in PRINCE_COLOR_NAMES)}
        return tuple(path for path in paths_for(FieldScope.APPEARANCE) if path in allowed)
    excluded = (('oracle.custom_colors.', 'oracle.custom_appearance.', 'oracle.prince_colors.')
                if body == 'bell' else ('oracle.colors.', 'oracle.prince_colors.'))
    return tuple(path for path in paths_for(FieldScope.APPEARANCE) if not path.startswith(excluded))


def appearance_mapping(oracle, *, full=False):
    source, result = {'oracle': asdict(oracle)}, {}
    for path in paths_for(FieldScope.APPEARANCE) if full else appearance_paths(oracle.body_appearance):
        set_value(result, path, get_value(source, path))
    return result


def validate_config(data, *, full=False):
    if not isinstance(data, dict) or not isinstance(data.get('oracle'), dict):
        raise ValueError('外观配置必须包含 oracle 对象')
    body = data['oracle'].get('body_appearance')
    allowed = paths_for(FieldScope.APPEARANCE) if full else appearance_paths(body)
    # 缺失字段使用格式对应的代码默认值，不能继承上一个角色或用户修改过的 TOML
    defaults = appearance_mapping(replace(OracleConfig(), body_appearance=body), full=full)
    for path, value in scoped_leaves(data, allowed):
        set_value(defaults, path, value)
    return OracleConfig.from_mapping(defaults['oracle'])


def image_paths(oracle, *, full=False):
    paths = paths_for(FieldScope.APPEARANCE) if full else appearance_paths(oracle.body_appearance)
    return tuple(path for path in paths if path.endswith('.image_path'))


def checked_image(path, decal=None):
    # 与设置面板共用 PNG 格式、尺寸、动画及文件大小校验
    from ..oracle.graphics.face_assets import image_size_limit, read_face_png
    read_face_png(path, image_size_limit(decal))
    return Path(path)


@dataclass(frozen=True, slots=True)
class AppearancePreset:
    id: str
    name: str
    updated_at: str
    oracle: OracleConfig
    path: Path
    revision: str = ''
    full: bool = False

    @property
    def timestamp(self):
        return validate_metadata(self.id, self.name, self.updated_at)

    def image(self, reference):
        path = package_path(self.path.parent, reference)
        # 同一 PNG 可被多个部件引用，各部件仍按自己的尺寸限制校验
        source = {'oracle': self.oracle}
        decals = [get_value(source, key.removesuffix('.image_path')) for key in image_paths(self.oracle, full=self.full)
                  if get_value(source, key) == reference]
        for decal in decals or [None]:
            checked_image(path, decal)
        return path


def load_appearance(path):
    path = Path(path).resolve()
    data = read_document(path, format=FORMAT, version=(1, 2))
    full = data['version'] == 2
    oracle = validate_config(data['config'], full=full)
    preset = AppearancePreset(data['id'], data['name'], data['updated_at'], oracle, path, full=full)
    source = {'oracle': oracle}
    for key in image_paths(oracle, full=full):
        reference = get_value(source, key)
        if reference:
            preset.image(reference)
        else:
            decal = get_value(source, key.removesuffix('.image_path'))
            if decal.enabled and getattr(decal, 'kind', 'png') == 'png':
                raise ValueError(Message('已启用的部件缺少贴图：{path}', path=key))
    resources = [preset.image(get_value(source, key)) for key in image_paths(oracle, full=full) if get_value(source, key)]
    return replace(preset, revision=revision_for([path, *resources]))


def apply_appearance(config, preset, asset_directory):
    """先验证并缓存全部引用，再返回新配置；失败不会改写当前设置"""
    from ..oracle.graphics.face_assets import import_face_png
    values = appearance_mapping(preset.oracle, full=preset.full)
    for path in image_paths(preset.oracle, full=preset.full):
        reference = get_value(values, path)
        if reference:
            decal = get_value({'oracle': preset.oracle}, path.removesuffix('.image_path'))
            imported = import_face_png(preset.image(reference), asset_directory, decal)
            # 缓存只改变路径，不改变原本关闭的开关、名称及 PNG 以外的耳机形状
            set_value(values, path, imported.image_path)
    merged = {'oracle': asdict(config.oracle)}
    for path in paths_for(FieldScope.APPEARANCE) if preset.full else appearance_paths(preset.oracle.body_appearance):
        set_value(merged, path, get_value(values, path))
    return replace(config, oracle=OracleConfig.from_mapping(merged['oracle']))
