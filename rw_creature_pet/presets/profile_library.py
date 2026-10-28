"""完整预设库，不从独立外观库按 ID 查找或自动替换引用"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .appearance import MANIFEST as APPEARANCE_MANIFEST
from .common import (default_library_directory, publish_package,
                     update_package, validate_metadata, write_document)
from .library import write_appearance
from .profile import FORMAT, MANIFEST, VERSION, load_profile, profile_mapping
from .catalog import cached_scan


def default_profile_directory():
    return default_library_directory('profiles')


class ProfileLibrary:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else default_profile_directory()

    def scan(self):
        return cached_scan(self.directory, MANIFEST, load_profile)

    def export(self, config, name, *, preset_id=None, appearance_source=None):
        name = name.strip()
        updated_at = datetime.now(timezone.utc).isoformat(timespec='microseconds')
        return self._write(config, name, preset_id or str(uuid4()), updated_at, config.oracle,
            appearance_source.name if appearance_source else name,
            appearance_source.id if appearance_source else str(uuid4()), updated_at,
            lambda reference: Path(reference).expanduser().resolve())

    def import_file(self, source, *, conflict=None):
        with self.import_transaction(source, conflict=conflict) as installed:
            return installed

    def import_transaction(self, source, *, conflict=None):
        from .sharing import import_transaction
        return import_transaction(self, source, conflict=conflict)

    def export_share(self, config, destination, *, name, preset_id, appearance_source=None):
        from .sharing import export_share
        return export_share(config, destination, name=name, identifier=preset_id,
                            appearance=appearance_source)

    def _write(self, config, name, identifier, updated_at, oracle, appearance_name,
               appearance_id, appearance_time, resolve_image, *, target=None):
        validate_metadata(identifier, name, updated_at)
        # 更新时使用新的外观资源目录，旧清单在提交前始终指向完整旧副本
        folder = 'appearance' if target is None else 'appearance-'+uuid4().hex

        def write(staging):
            write_appearance(staging/folder, oracle, appearance_name, appearance_id,
                             appearance_time, resolve_image)
            write_document(staging/MANIFEST, dict(type=FORMAT, version=VERSION, id=identifier,
                name=name, updated_at=updated_at, config=profile_mapping(config),
                appearance={'id': appearance_id, 'path': folder+'/'+APPEARANCE_MANIFEST}))

        if target is not None:
            return update_package(self.directory, target, MANIFEST, write, load_profile)
        return publish_package(self.directory, name, 'profile', MANIFEST, write, load_profile)

    def update(self, config, target, *, name=None, appearance_source=None):
        name = target.name if name is None else name.strip()
        source = appearance_source or target.appearance
        stamp = max(datetime.now(timezone.utc), target.timestamp+timedelta(microseconds=1)).isoformat()
        return self._write(config, name, target.id, stamp, config.oracle, source.name, source.id, stamp,
            lambda reference: Path(reference).expanduser().resolve(), target=target)
