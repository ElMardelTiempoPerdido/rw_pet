"""只读检测雨世界本体目录，复用 Steam 库枚举，不检查 DLC 或订阅状态"""
from pathlib import Path
import re

from .game_mods import steam_libraries


def is_game_directory(directory):
    try:
        return (Path(directory).expanduser()/'RainWorld_Data/resources.assets').is_file()
    except (OSError, RuntimeError, ValueError):
        return False


def _installed_directory(library):
    manifest = library/'steamapps/appmanifest_312520.acf'
    try:
        data = manifest.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError):
        return None
    match = re.search(r'^\s*"installdir"\s+"([^"\r\n]+)"', data, re.MULTILINE | re.IGNORECASE)
    if match is None:
        return None
    name = match[1]
    # Steam 安装记录只提供 common 下的目录名，不接受绝对路径或向上跳转
    if name in ('.', '..') or any(c in name for c in '/\\:\0'):
        return None
    return library/'steamapps/common'/name


def find_game_directory(preferred=None, *, steam_roots=None):
    """保留有效配置；随后按 Steam 库顺序找安装记录和常规目录，无结果返回 None"""
    if preferred is not None and is_game_directory(preferred):
        return Path(preferred).expanduser().resolve()
    for library in steam_libraries(preferred, steam_roots=steam_roots):
        for candidate in (_installed_directory(library), library/'steamapps/common/Rain World'):
            if candidate is not None and is_game_directory(candidate):
                return candidate.resolve()
    return None
