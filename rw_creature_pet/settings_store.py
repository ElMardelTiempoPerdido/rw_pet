"""用户设置存储：独立于安装目录，完整保留未在 GUI 中展示的配置。"""
from dataclasses import asdict, replace
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile

from .config import AppConfig
from .oracle.config import migrate_shoulder_width
from .oracle.eye_config import EYE_FIELDS
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
        from .oracle.audio.assets import LEGACY_DIRECTORY
        from .oracle.audio.voice import BELL_VOICE_CLIPS
        directory = Path(voice).expanduser()
        resolved = (directory if directory.is_absolute() else base/directory).resolve()
        if voice.replace('\\', '/') == LEGACY_DIRECTORY and not all(
                (resolved/clip.filename).is_file() for clip in BELL_VOICE_CLIPS):
            voice = 'auto'
        else:
            voice = str(resolved)
    shape = config.oracle.custom_appearance.resolve_image_paths(base)
    return replace(config, game_dir=game.resolve(), oracle=replace(config.oracle, voice_directory=voice,
                   custom_appearance=shape))


def load_defaults(source=None):
    """启动、配置升级和面板重置共用同一份默认模板及路径解析。"""
    source = source if source is not None else default_template_path()
    return absolute_paths(AppConfig.load(source), source)


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
        self._preset_state = None

    def load_preset_state(self):
        state = self.read_document().get('preset_state', {})
        return state if isinstance(state, dict) else {}

    def read_document(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @contextmanager
    def preset_state(self, state):
        """与本次设置提交一同写入；失败或取消不改变已保存的预设关联"""
        previous, self._preset_state = self._preset_state, state
        try:
            yield
        finally:
            self._preset_state = previous

    def load(self):
        defaults = load_defaults()
        return self._load(_mapping(defaults))[0]

    def _load(self, defaults):
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1:
            raise ValueError('不支持的用户设置文件版本')
        if not isinstance(data.get('config'), dict):
            raise ValueError('配置必须为对象')
        from .presets.startup import stage_character_upgrade
        data, character_staged = stage_character_upgrade(data)
        user_config = dict(data['config'])
        oracle = user_config.get('oracle')
        palette_migrated = isinstance(oracle, dict) and 'custom_colors' not in oracle
        if palette_migrated:
            # 必须在补默认值之前复制旧配色，避免升级时丢失用户已调好的颜色
            colors, _ = _fill_missing(oracle.get('colors', {}), defaults['oracle']['colors'])
            user_config['oracle'] = {**oracle, 'custom_colors': colors}
        oracle = user_config.get('oracle')
        eyes_migrated = False
        if isinstance(oracle, dict):
            shape = oracle.get('custom_appearance', {})
            palette = oracle.get('custom_colors', {})
            if isinstance(shape, dict) and isinstance(palette, dict) and 'eyes' in palette:
                shape = dict(shape)
                # 在补默认模板前保留旧统一眼睛色，已有单眼颜色优先
                for name in EYE_FIELDS:
                    eye = shape.get(name, {})
                    if isinstance(eye, dict) and 'color' not in eye:
                        shape[name] = {**eye, 'color': palette['eyes']}
                        eyes_migrated = True
                if eyes_migrated:
                    user_config['oracle'] = {**oracle, 'custom_appearance': shape}
        oracle = user_config.get('oracle')
        shoulders_migrated = False
        if isinstance(oracle, dict) and isinstance(oracle.get('custom_appearance'), dict):
            shape = oracle['custom_appearance']
            upgraded = migrate_shoulder_width(shape)
            if upgraded is not shape:
                user_config['oracle'] = {**oracle, 'custom_appearance': upgraded}
                shoulders_migrated = True
        watcher = user_config.get('overseer')
        migrated = isinstance(watcher, dict) and 'slots' not in watcher and 'color' in watcher
        if migrated:
            user_config['overseer'] = {**watcher, 'slots': [
                {'id': 1, 'color': watcher['color'], 'appearance': 'standard'}]}
        merged, changed = _fill_missing(user_config, defaults)
        changed |= migrated or palette_migrated or eyes_migrated or shoulders_migrated or character_staged
        # 默认路径已按 TOML 所在目录解析；用户自己的相对路径仍以用户文件为准。
        config = absolute_paths(AppConfig.from_mapping(merged), self.path)
        if merged['ui']['language'] != config.ui.language:
            merged['ui'] = {**merged['ui'], 'language': config.ui.language}
            changed = True
        return config, {**data, 'config': merged}, changed

    def save(self, config):
        data = _mapping(config)
        AppConfig.from_mapping(data)
        state = self.load_preset_state() if self._preset_state is None else self._preset_state
        self._write({'version': 1, 'config': data, 'preset_state': state})

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
        defaults = load_defaults(explicit)
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
