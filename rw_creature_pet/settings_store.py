"""用户设置存储：独立于安装目录，完整保留未在 GUI 中展示的配置。"""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sys
import tempfile

from .config import AppConfig
from .shared.messages import Message


def default_settings_path():
    root = Path(os.environ.get('LOCALAPPDATA', Path.home()/'.config'))
    return root/'rw_creature_pet/settings.json'


def default_template_path():
    # 打包后先找 exe 旁的默认配置，再找包内资源；不依赖启动快捷方式的工作目录。
    roots = ([Path(sys.executable).parent, Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))]
             if getattr(sys, 'frozen', False) else [Path(__file__).resolve().parents[1]])
    return next((root/'config.toml' for root in roots if (root/'config.toml').is_file()), None)


def absolute_paths(config, source=None):
    base = source.resolve().parent if source is not None else Path.cwd()
    game = config.game_dir.expanduser()
    if not game.is_absolute():
        game = base/game
    voice = config.oracle.voice_directory
    if voice != 'auto':
        from .oracle.voice_assets import LEGACY_DIRECTORY
        from .oracle.voice import BELL_VOICE_CLIPS
        directory = Path(voice).expanduser()
        resolved = (directory if directory.is_absolute() else base/directory).resolve()
        if voice.replace('\\', '/') == LEGACY_DIRECTORY and not all(
                (resolved/clip.filename).is_file() for clip in BELL_VOICE_CLIPS):
            voice = 'auto'
        else:
            voice = str(resolved)
    return replace(config, game_dir=game.resolve(), oracle=replace(config.oracle, voice_directory=voice))


def validate_game_directory(directory):
    if not (directory/'RainWorld_Data/resources.assets').is_file():
        raise ValueError('请选择 Rain World 安装目录：其中应包含 RainWorld_Data 文件夹及 resources.assets。')


def _mapping(config):
    data = asdict(config)
    data['game_dir'] = str(config.game_dir)
    return data


def _fill_missing(data, defaults):
    """只按键是否存在补齐，保留 false、0、空列表及用户的嵌套设置。"""
    result, changed = dict(data), False
    for key, value in defaults.items():
        if key not in result:
            result[key], changed = value, True
        elif isinstance(value, dict) and isinstance(result[key], dict):
            result[key], nested_changed = _fill_missing(result[key], value)
            changed |= nested_changed
    return result, changed


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_settings_path()

    def load(self):
        source = default_template_path()
        defaults = absolute_paths(AppConfig.load(source), source)
        return self._load(_mapping(defaults))[0]

    def _load(self, defaults):
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1:
            raise ValueError('不支持的用户设置文件版本')
        if not isinstance(data.get('config'), dict):
            raise ValueError('配置必须为对象')
        merged, changed = _fill_missing(data['config'], defaults)
        # 默认路径已按 TOML 所在目录解析；用户自己的相对路径仍以用户文件为准。
        config = absolute_paths(AppConfig.from_mapping(merged), self.path)
        if merged['ui']['language'] != config.ui.language:
            merged['ui'] = {**merged['ui'], 'language': config.ui.language}
            changed = True
        return config, {**data, 'config': merged}, changed

    def save(self, config):
        data = _mapping(config)
        AppConfig.from_mapping(data)
        self._write({'version': 1, 'config': data})

    def _write(self, data):
        payload = json.dumps(data, ensure_ascii=False, indent=2)+'\n'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=self.path.name+'.', suffix='.tmp',
                                             mode='w', encoding='utf-8', newline='\n', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if self.path.exists():
                # 保留上次完整文件，也为损坏文件重新确认设置后的恢复提供副本。
                self.path.with_suffix('.json.bak').write_bytes(self.path.read_bytes())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def startup(self, explicit=None):
        """返回配置、是否需要首次设置、提示；显式 TOML 仅覆盖本次启动。"""
        first_run, message = not self.path.is_file(), ''
        source = explicit if explicit is not None else default_template_path()
        defaults = absolute_paths(AppConfig.load(source), source)
        if explicit is None and not first_run:
            try:
                config, payload, changed = self._load(_mapping(defaults))
            except (OSError, ValueError, TypeError) as exc:
                message = Message('无法读取已保存设置：{error}\n请重新确认，保存时会保留旧文件的备份。', error=exc)
                first_run = True
            else:
                if changed:
                    try:
                        self._write(payload)
                    except OSError as exc:
                        # 自动升级写入失败仍使用读出的用户值，不退回首次设置或默认值。
                        message = Message('已保留原有设置，但无法保存新增设置：{error}\n本次仍可使用；请检查设置文件的写入权限后重试。', error=exc)
                return config, False, message
        return defaults, first_run, message
