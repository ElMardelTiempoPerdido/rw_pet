"""核对旧迁移额外生成的角色；默认只检查，--apply 完整归档并清除引用"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rw_creature_pet.presets.migration_cleanup import apply_cleanup, plan_cleanup
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--profiles', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    store, library = SettingsStore(args.settings), ProfileLibrary(args.profiles)
    plan = plan_cleanup(store, library)
    result = apply_cleanup(store, library, plan) if args.apply else {
        'archive_candidates': sum(row['action'] == 'archive' for row in plan['rows']),
        'keep': sum(row['action'] == 'keep' for row in plan['rows'])}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({'result': result, 'plan': plan}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
