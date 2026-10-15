"""程序旁的外观库，以及供完整预设携带的外观副本"""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from .appearance import (FORMAT, MANIFEST, VERSION, appearance_mapping, checked_image,
                         get_value, image_paths, load_appearance, set_value, validate_metadata)
from .common import default_library_directory, publish_package, scan_library, write_document


def default_appearance_directory():
    return default_library_directory('appearances')


def write_appearance(directory, oracle, name, identifier, updated_at, resolve_image):
    """写入调用方的暂存目录，完整预设复用此处的资源复制及引用改写"""
    validate_metadata(identifier, name, updated_at)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    data = appearance_mapping(oracle)
    for key in image_paths(oracle):
        reference = get_value(data, key)
        if not reference:
            continue
        payload = resolve_image(reference).read_bytes()
        target = directory/'images'/(sha256(payload).hexdigest()+'.png')
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(payload)
        set_value(data, key, target.relative_to(directory).as_posix())
    write_document(directory/MANIFEST, dict(type=FORMAT, version=VERSION, id=identifier,
                   name=name, updated_at=updated_at, config=data))


class AppearanceLibrary:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else default_appearance_directory()

    def scan(self):
        return scan_library(self.directory, MANIFEST, load_appearance)

    def export(self, config, name, *, preset_id=None):
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
        return publish_package(self.directory, name, 'appearance', MANIFEST,
            lambda staging: write_appearance(staging, oracle, name, identifier, updated_at, resolve_image),
            load_appearance)
