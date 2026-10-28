"""核对已迁移角色是否用了错误旧会话；默认只读，--apply 备份后纠正"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rw_creature_pet.presets.migration_repair import apply_repair, plan_repair
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--profiles', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--discard-post-migration', action='store_true', help='不保留迁移后的参数修改')
    args = parser.parse_args()
    store, library = SettingsStore(args.settings), ProfileLibrary(args.profiles)
    plan = plan_repair(store, library, preserve_changes=not args.discard_post_migration)
    result = apply_repair(store, library, plan) if args.apply else {
        'candidates': [{'name': row['name'], 'corrected_fields': len(row['corrected_fields']),
                        'preserved_fields': len(row['preserved_fields'])}
                       for row in plan['rows'] if row['action'] == 'repair'],
        'unchanged': [row['name'] for row in plan['rows'] if row['action'] != 'repair']}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({'result': result, 'plan': plan}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
