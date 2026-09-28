"""用户设置存储：独立于安装目录，完整保留未在 GUI 中展示的配置。"""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sys
import tempfile

from .config import AppConfig


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


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_settings_path()

    def load(self):
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1:
            raise ValueError('不支持的用户设置文件版本')
        return absolute_paths(AppConfig.from_mapping(data.get('config')), self.path)

    def save(self, config):
        data = asdict(config)
        data['game_dir'] = str(config.game_dir)
        AppConfig.from_mapping(data)
        payload = json.dumps({'version': 1, 'config': data}, ensure_ascii=False, indent=2)+'\n'
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
        if explicit is None and not first_run:
            try:
                return self.load(), False, ''
            except (OSError, ValueError, TypeError) as exc:
                message = f'无法读取已保存设置：{exc}\n请重新确认，保存时会保留旧文件的备份。'
                first_run = True
        source = explicit if explicit is not None else default_template_path()
        return absolute_paths(AppConfig.load(source), source), first_run, message
