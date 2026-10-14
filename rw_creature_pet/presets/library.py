"""程序旁的外观库：原子写入自包含文件夹，按 ID 解析重复版本"""
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import tempfile
from uuid import uuid4

from .appearance import (FORMAT, MANIFEST, VERSION, AppearancePreset, appearance_mapping,
                         checked_image, get_value, image_paths, load_appearance,
                         set_value, validate_metadata)


def default_appearance_directory():
    root = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    return root/'presets/appearances'


@dataclass(frozen=True, slots=True)
class LibraryScan:
    presets: tuple[AppearancePreset, ...]
    duplicates: tuple[tuple[AppearancePreset, ...], ...]
    errors: tuple[tuple[Path, Exception], ...]


class AppearanceLibrary:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else default_appearance_directory()

    def scan(self):
        groups, errors = {}, []
        root = self.directory.resolve()
        if not root.exists():
            return LibraryScan((), (), ())
        for path in sorted(root.rglob(MANIFEST), key=lambda p: (str(p).casefold(), str(p))):
            if any(part.startswith('.staging-') for part in path.relative_to(root).parts):
                continue
            try:
                if not path.resolve().is_relative_to(root):
                    raise ValueError('预设文件路径超出了外观目录')
                preset = load_appearance(path)
                groups.setdefault(preset.id, []).append(preset)
            except (OSError, ValueError, TypeError, RecursionError) as exc:
                errors.append((path, exc))
        winners, duplicates = [], []
        for group in groups.values():
            # 路径排序提供相同时间戳的稳定选择；有效的新版本优先于文件系统 mtime
            group.sort(key=lambda preset: preset.timestamp, reverse=True)
            winners.append(group[0])
            if len(group) > 1:
                duplicates.append(tuple(group))
        winners.sort(key=lambda preset: (preset.name.casefold(), preset.id))
        return LibraryScan(tuple(winners), tuple(duplicates), tuple(errors))

    def export(self, config, name, *, preset_id=None):
        """导出当前所选主体；提供已有 ID 时生成新版本目录，不覆盖原目录"""
        return self._write(config.oracle, name.strip(), preset_id or str(uuid4()),
                           datetime.now(timezone.utc).isoformat(timespec='microseconds'),
                           lambda reference: checked_image(Path(reference).expanduser().resolve()))

    def import_file(self, source):
        preset = load_appearance(source)
        if preset.path.is_relative_to(self.directory.resolve()):
            return preset
        return self._write(preset.oracle, preset.name, preset.id, preset.updated_at, preset.image)

    def _write(self, oracle, name, identifier, updated_at, resolve_image):
        validate_metadata(identifier, name, updated_at)
        data = appearance_mapping(oracle)
        self.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.staging-', dir=self.directory) as temporary:
            staging = Path(temporary)
            for key in image_paths(oracle):
                reference = get_value(data, key)
                if not reference:
                    continue
                source = resolve_image(reference)
                payload = source.read_bytes()
                target = staging/'images'/(sha256(payload).hexdigest()+'.png')
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(payload)
                set_value(data, key, target.relative_to(staging).as_posix())
            document = dict(type=FORMAT, version=VERSION, id=identifier, name=name,
                            updated_at=updated_at, config=data)
            (staging/MANIFEST).write_text(json.dumps(document, ensure_ascii=False, indent=2,
                                                    allow_nan=False)+'\n', encoding='utf-8')
            # 写入完整后再校验，包括启用但未提供贴图的部件
            load_appearance(staging/MANIFEST)
            slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:48] or 'untitled'
            target = self.directory/f'appearance-{slug}-{uuid4().hex}'
            staging.rename(target)
        return load_appearance(target/MANIFEST)
