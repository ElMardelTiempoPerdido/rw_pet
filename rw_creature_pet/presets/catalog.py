"""角色目录的进程内索引及共享选择规则，不缓存实际切换时的校验"""
from collections import OrderedDict
import os
from pathlib import Path

from .common import scan_library

_SCANS = OrderedDict()
_CACHE_LIMIT = 8


def file_stamp(path):
    try:
        info = Path(path).stat()
        return info.st_mtime_ns, info.st_ctime_ns, info.st_size, info.st_ino
    except FileNotFoundError:
        return None


def directory_stamp(root):
    """只读取目录和文件元数据，包含引用贴图，以检测增加、删除、替换和编辑"""
    if not root.exists():
        return ()
    def failed(error):
        raise error
    files = []
    for directory, folders, names in os.walk(root, onerror=failed):
        folders[:] = sorted(name for name in folders if not name.startswith('.staging-'))
        for name in sorted(names):
            path = Path(directory)/name
            files.append((str(path), file_stamp(path)))
    return tuple(files)


def cached_scan(directory, manifest, loader):
    root = Path(directory).resolve()
    key = root, manifest, loader
    stamp = directory_stamp(root)
    cached = _SCANS.get(key)
    if cached is not None and cached[0] == stamp:
        _SCANS.move_to_end(key)
        return cached[1]
    report = scan_library(root, manifest, loader)
    # 扫描过程中有文件变化时，不把混合版本留在缓存中
    if directory_stamp(root) == stamp:
        _SCANS[key] = stamp, report
        _SCANS.move_to_end(key)
        while len(_SCANS) > _CACHE_LIMIT:
            _SCANS.popitem(last=False)
    else:
        _SCANS.pop(key, None)
    return report


def same_preset(first, second):
    return (first is not None and second is not None
            and (first.path, first.revision) == (second.path, second.revision))


def selection_options(presets, loaded=None):
    """沿用库的去重排序，额外保留不在库中的已载入版本"""
    rows = [(preset, False) for preset in presets]
    if loaded is not None and not any(same_preset(preset, loaded) for preset in presets):
        rows.append((loaded, True))
    return rows
