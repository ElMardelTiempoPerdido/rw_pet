"""只读查找本地 Rain World 模组，不依赖 Steam 在线状态或模组启用列表"""
import json
import os
from pathlib import Path
import re


def _system_steam_roots():
    roots = []
    if os.name == 'nt':
        import winreg
        for hive, key, value in (
            (winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath'),
        ):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    roots.append(Path(winreg.QueryValueEx(handle, value)[0]))
            except OSError:
                pass
        for name in ('ProgramFiles(x86)', 'ProgramFiles'):
            if os.environ.get(name):
                roots.append(Path(os.environ[name])/'Steam')
    else:
        roots.extend((Path.home()/'.steam/steam', Path.home()/'.local/share/Steam',
                      Path.home()/'Library/Application Support/Steam'))
    return roots


def _unique(paths):
    seen = set()
    for path in paths:
        path = Path(path).expanduser().resolve()
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            yield path


def steam_libraries(game_dir, *, steam_roots=None):
    """优先所选游戏所属库，再读取 Steam 的 libraryfolders.vdf"""
    game = Path(game_dir).expanduser().resolve()
    roots = [parent.parent for parent in game.parents if parent.name.casefold() == 'steamapps']
    roots.extend(_system_steam_roots() if steam_roots is None else steam_roots)
    roots = list(_unique(roots))
    libraries = list(roots)
    # 新版记录为 "path"，旧版为数字键；只读取路径字段，不解析或执行其他内容
    pattern = re.compile(r'^\s*"(?:path|\d+)"\s+"((?:\\.|[^"\\])*)"', re.MULTILINE | re.IGNORECASE)
    for root in roots:
        for manifest in (root/'steamapps/libraryfolders.vdf', root/'config/libraryfolders.vdf'):
            try:
                data = manifest.read_text(encoding='utf-8-sig')
            except (OSError, UnicodeError):
                continue
            for value in pattern.findall(data):
                path = Path(value.replace('\\\\', '\\').replace('\\"', '"'))
                if path.is_absolute():
                    libraries.append(path)
    return tuple(_unique(libraries))


def installed_mod_paths(game_dir, mod_id, workshop_id, *, steam_roots=None):
    """支持手动安装与创意工坊安装，不检查订阅清单、enabledMods 或前置模组"""
    found = []
    local = Path(game_dir)/'RainWorld_Data/StreamingAssets/mods'
    try:
        folders = sorted(local.iterdir())
    except OSError:
        folders = ()
    for folder in folders:
        try:
            info = json.loads((folder/'modinfo.json').read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError, ValueError):
            continue
        if isinstance(info, dict) and str(info.get('id', '')).casefold() == mod_id.casefold():
            found.append(folder)
    for library in steam_libraries(game_dir, steam_roots=steam_roots):
        folder = library/'steamapps/workshop/content/312520'/str(workshop_id)
        if folder.is_dir():
            found.append(folder)
    return tuple(_unique(found))
