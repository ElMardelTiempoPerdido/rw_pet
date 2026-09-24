"""目录边界是实际依赖边界；导入一种生物的仿真不能拖入另一种。"""
import ast
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ImportBoundaryTests(unittest.TestCase):
    def test_simulation_imports_are_independent_and_have_no_qt_dependency(self):
        for creature, other in (('lizard', 'oracle'), ('oracle', 'lizard')):
            with self.subTest(creature=creature):
                code = (
                    f'import rw_creature_pet.{creature}.scene\n'
                    'import sys\n'
                    f'assert not any(n.startswith("rw_creature_pet.{other}") for n in sys.modules)\n'
                    'assert not any(n.startswith("PySide6") for n in sys.modules)\n'
                )
                result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_and_creature_modules_keep_dependency_direction(self):
        for package in ('shared', 'lizard', 'oracle'):
            forbidden = {'lizard', 'oracle'}-({package} if package != 'shared' else set())
            for path in (ROOT/'rw_creature_pet'/package).glob('*.py'):
                current = ['rw_creature_pet', package]
                for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                    modules = []
                    if isinstance(node, ast.ImportFrom):
                        module = node.module or ''
                        if node.level:
                            module = '.'.join(current[:len(current)-node.level+1]+([module] if module else []))
                        modules.append(module)
                    elif isinstance(node, ast.Import):
                        modules.extend(alias.name for alias in node.names)
                    for module in modules:
                        parts = module.split('.')
                        if len(parts) >= 2 and parts[0] == 'rw_creature_pet':
                            self.assertNotIn(parts[1], forbidden, f'{path.name}: {module}')
                            if package == 'shared':
                                self.assertEqual(parts[1], 'shared', f'{path.name}: {module}')
