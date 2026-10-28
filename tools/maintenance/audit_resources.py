"""只读校验资源清单，不提取游戏资源、不迁移用户设置"""
import argparse
from dataclasses import asdict
import json

from rw_creature_pet.config import AppConfig
from rw_creature_pet.presets.registry import schema_paths
from rw_creature_pet.resources import CatalogError, load_catalog
from rw_creature_pet.shared.paths import PACKAGE_ROOT


def report(catalog, *, check_package=False):
    catalog.validate_settings(schema_paths(AppConfig))
    result = {'format_version': 1, 'required': catalog.required}
    for name in ('origins', 'resources', 'features', 'settings'):
        result[name] = {key: asdict(value) for key, value in getattr(catalog, name).items()}
    if check_package:
        # 这里只检查发行文件清单，不把存在误报为已成功解码/可用
        paths = {path for resource in catalog.resources.values() for source in resource.sources
                 if source.root == 'package' for path in source.paths}
        result['package_files'] = {path: (PACKAGE_ROOT/path).is_file() for path in sorted(paths)}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', help='校验指定 TOML，默认使用随包清单')
    parser.add_argument('--check-package', action='store_true', help='核对包内文件是否齐全，不判定资源可用性')
    parser.add_argument('--json', action='store_true', help='将完整来源与设置映射输出为 JSON')
    args = parser.parse_args(argv)
    try:
        result = report(load_catalog(args.catalog), check_package=args.check_package)
    except CatalogError as exc:
        parser.exit(1, f'{exc}\n')
    missing = [path for path, present in result.get('package_files', {}).items() if not present]
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"资源清单有效：{len(result['resources'])} 组资源，{len(result['features'])} 项功能，"
              f"{len(result['settings'])} 组设置绑定")
        if args.check_package:
            print(f"包内文件：{len(result['package_files'])} 项，缺失 {len(missing)} 项")
        for path in missing:
            print(f'缺失：{path}')
    return 1 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main())
