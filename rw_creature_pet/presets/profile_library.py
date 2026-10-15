"""完整预设库，不从独立外观库按 ID 查找或自动替换引用"""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .appearance import MANIFEST as APPEARANCE_MANIFEST, checked_image
from .common import (default_library_directory, publish_package, scan_library,
                     validate_metadata, write_document)
from .library import write_appearance
from .profile import FORMAT, MANIFEST, VERSION, load_profile, profile_mapping


def default_profile_directory():
    return default_library_directory('profiles')


class ProfileLibrary:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else default_profile_directory()

    def scan(self):
        return scan_library(self.directory, MANIFEST, load_profile)

    def export(self, config, name, *, preset_id=None, appearance_source=None):
        name = name.strip()
        updated_at = datetime.now(timezone.utc).isoformat(timespec='microseconds')
        return self._write(config, name, preset_id or str(uuid4()), updated_at, config.oracle,
            appearance_source.name if appearance_source else name,
            appearance_source.id if appearance_source else str(uuid4()), updated_at,
            lambda reference: checked_image(Path(reference).expanduser().resolve()))

    def import_file(self, source):
        preset = load_profile(source)
        if preset.path.is_relative_to(self.directory.resolve()):
            return preset
        appearance = preset.appearance
        return self._write(preset.config, preset.name, preset.id, preset.updated_at,
                           appearance.oracle, appearance.name, appearance.id,
                           appearance.updated_at, appearance.image)

    def _write(self, config, name, identifier, updated_at, oracle, appearance_name,
               appearance_id, appearance_time, resolve_image):
        validate_metadata(identifier, name, updated_at)

        def write(staging):
            write_appearance(staging/'appearance', oracle, appearance_name, appearance_id,
                             appearance_time, resolve_image)
            write_document(staging/MANIFEST, dict(type=FORMAT, version=VERSION, id=identifier,
                name=name, updated_at=updated_at, config=profile_mapping(config),
                appearance={'id': appearance_id, 'path': 'appearance/'+APPEARANCE_MANIFEST}))

        return publish_package(self.directory, name, 'profile', MANIFEST, write, load_profile)
