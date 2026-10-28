"""角色设置：已登记的行为参数，加上明确指向包内外观副本的引用"""
from dataclasses import dataclass, replace
from hashlib import sha256
from math import isfinite
from pathlib import Path

from ..config import AppConfig
from ..shared.messages import Message
from ..ui_config import UiConfig
from ..oracle.audio.voice import legacy_voice
from .appearance import AppearancePreset, apply_appearance, load_appearance
from .common import (get_value, mapping_for, package_path, read_document, replace_fields,
                     scoped_leaves, set_value, validate_metadata)
from .fields import paths_for
from .registry import FieldScope

FORMAT = 'rw-creature-pet.profile'
VERSION = 1
MANIFEST = 'profile.json'


def profile_mapping(config):
    return mapping_for(config, paths_for(FieldScope.PROFILE))


def validate_config(data, *, body_appearance='bell'):
    # 缺省值由当前格式的配置定义提供，与本机模板、当前人物和系统语言无关
    defaults = AppConfig(ui=UiConfig('en'))
    values = profile_mapping(defaults)
    # 旧分享文件没有语音选项时，保留它原来的发声行为
    set_value(values, 'oracle.voice', legacy_voice(body_appearance))
    for path, value in scoped_leaves(data, paths_for(FieldScope.PROFILE)):
        default = get_value(defaults, path)
        # 避免 JSON 的 true 被当作浮点数 1，也不接受字符串形式的数字
        valid = (type(value) is bool if type(default) is bool else
                 type(value) is int if type(default) is int else
                 type(value) in (int, float) if type(default) is float else
                 type(value) is type(default))
        if not valid or (type(value) is float and not isfinite(value)):
            raise ValueError(Message('角色设置字段类型无效：{path}', path=path))
        set_value(values, path, value)
    return replace_fields(defaults, values)


@dataclass(frozen=True, slots=True)
class ProfilePreset:
    id: str
    name: str
    updated_at: str
    config: AppConfig
    appearance: AppearancePreset
    path: Path
    revision: str = ''
    state_path: str = ''

    @property
    def timestamp(self):
        return validate_metadata(self.id, self.name, self.updated_at)


def load_profile(path):
    path = Path(path).resolve()
    if not path.exists() and not (path.parent/'character.json').exists():
        original = path.parent/'original'/MANIFEST
        if original.is_file():
            return replace(load_profile(original), path=path)
    data = read_document(path, format=FORMAT, version=(1, 2),
                         extra_fields={1: ('appearance',), 2: ('appearance', 'state')})
    reference = data['appearance']
    if not isinstance(reference, dict) or set(reference) != {'id', 'path'}:
        raise ValueError('角色设置必须包含外观 ID 与包内路径')
    appearance = load_appearance(package_path(path.parent, reference['path']))
    if appearance.id != reference['id']:
        raise ValueError('角色设置引用的外观 ID 与包内文件不一致')
    config = validate_config(data['config'], body_appearance=appearance.oracle.body_appearance)
    state_path = data.get('state', '')
    if data['version'] == 2 and (not isinstance(state_path, str) or not state_path):
        raise ValueError('角色工作目录缺少有效的历史索引路径')
    state_bytes = b''
    if state_path:
        state_file = package_path(path.parent, state_path)
        if state_file.stat().st_size > 4*1024*1024:
            raise ValueError('角色历史文件过大')
        state_bytes = state_file.read_bytes()
    revision = sha256(path.read_bytes()+appearance.revision.encode('ascii')+state_bytes).hexdigest()
    return ProfilePreset(data['id'], data['name'], data['updated_at'], config, appearance, path, revision, state_path)


def apply_profile(config, preset, asset_directory):
    # 先计算出完整结果，再交给 UI 一次性填入；本机设置和另一外观分支均沿用当前值
    config = replace_fields(config, profile_mapping(preset.config))
    return apply_appearance(config, preset.appearance, asset_directory)
