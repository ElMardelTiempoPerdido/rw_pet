"""同步声明式 Qt 表单的中文原文到 TS；翻译完成后用 Qt lrelease 编译。"""
import argparse
import ast
from pathlib import Path
import shutil
import string
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT/'rw_creature_pet'
CATALOG = PACKAGE/'translations/en.ts'
FILES = ('oracle/settings.py', 'oracle/toolbar.py', 'oracle/desktop.py',
         'config.py', 'oracle/config.py', 'overseer/config.py', 'interaction/config.py',
         'settings_store.py', 'shared/atlas.py', 'ui_config.py', 'overseer/events.py')
UNTRANSLATED = {'中文', '语言/language', ' · 独立调试；关闭窗口返回桌宠'}


def sources():
    result = {}
    for filename in (*FILES, 'app.py'):
        tree = ast.parse((PACKAGE/filename).read_text(encoding='utf-8'))
        excluded = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr)
                    and isinstance(n.value, ast.Constant)}
        excluded.update(id(part) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for part in n.values)
        nodes = ast.walk(tree) if filename != 'app.py' else (
            arg for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == 'tr' for arg in n.args)
        for node in nodes:
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in excluded
                    and node.value not in UNTRANSLATED and any('\u4e00' <= c <= '\u9fff' for c in node.value)):
                result.setdefault(node.value, []).append((filename, node.lineno))
    return result


def placeholders(text):
    return sorted((field, spec, conversion) for _, field, spec, conversion in string.Formatter().parse(text)
                  if field is not None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='检查缺少的译文和占位符，不修改文件')
    parser.add_argument('--compile', action='store_true', help='检查完成后编译 en.qm')
    args = parser.parse_args()
    prior = ET.parse(CATALOG).getroot() if CATALOG.exists() else ET.Element('TS')
    translations = {m.findtext('source'): m.findtext('translation', '') for m in prior.findall('./context/message')}
    required = sources()
    missing = [source for source in required if not translations.get(source)]
    mismatched = [source for source in required if translations.get(source)
                  and placeholders(source) != placeholders(translations[source])]
    if not args.check:
        root = ET.Element('TS', version='2.1', language='en_US', sourcelanguage='zh_CN')
        context = ET.SubElement(root, 'context')
        ET.SubElement(context, 'name').text = 'BellPet'
        for source, locations in sorted(required.items()):
            message = ET.SubElement(context, 'message')
            for filename, line in locations:
                ET.SubElement(message, 'location', filename='../'+filename, line=str(line))
            ET.SubElement(message, 'source').text = source
            translation = ET.SubElement(message, 'translation')
            translation.text = translations.get(source, '')
            if not translation.text:
                translation.set('type', 'unfinished')
        ET.indent(root, space='  ')
        CATALOG.parent.mkdir(parents=True, exist_ok=True)
        CATALOG.write_bytes(ET.tostring(root, encoding='utf-8', xml_declaration=True)+b'\n')
    if missing or mismatched:
        print(f'Missing translations: {len(missing)}; mismatched placeholders: {len(mismatched)}')
        for source in missing+mismatched:
            print(ascii(source))
        return 1
    if args.compile:
        compiler = shutil.which('pyside6-lrelease') or str(Path(sys.executable).parent/'Scripts/pyside6-lrelease.exe')
        subprocess.run([compiler, str(CATALOG), '-qm', str(CATALOG.with_suffix('.qm'))], check=True)
    print(f'Translations checked: {len(required)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
