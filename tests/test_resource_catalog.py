"""资源归属、加载契约与设置影响必须保持一致，不依赖本机安装 DLC"""
import ast
from copy import deepcopy
import json
import os
import subprocess
import sys
import tomllib
import unittest
from unittest.mock import Mock

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.audio.voice import VOICE_CLIPS
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.graphics.outfit_definition import MAID
from rw_creature_pet.presets.appearance import image_paths
from rw_creature_pet.presets.registry import schema_paths
from rw_creature_pet.resources import Availability as A, CatalogError, load_catalog
from rw_creature_pet.resources.catalog import CATALOG_PATH, parse_catalog
from rw_creature_pet.shared.paths import PACKAGE_ROOT
from tools.maintenance.audit_resources import report


class ResourceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()

    def test_declared_settings_and_configured_sources_exist(self):
        self.catalog.validate_settings(schema_paths(AppConfig))
        paths = set(schema_paths(AppConfig)) - {'oracle.voice'}
        with self.assertRaisesRegex(CatalogError, 'oracle.voice'):
            self.catalog.validate_settings(paths)

    def test_normal_start_requires_base_atlas_only(self):
        self.assertEqual(self.catalog.required, ('main_atlas',))
        self.assertEqual(self.catalog.resources['main_atlas'].origins, ('base_game',))
        self.assertIs(self.catalog.required_state({}), A.UNKNOWN)
        self.assertIs(self.catalog.required_state({'main_atlas': A.AVAILABLE, 'bell_voice': A.UNAVAILABLE}), A.AVAILABLE)
        self.assertIs(self.catalog.required_state({'main_atlas': A.UNAVAILABLE}), A.UNAVAILABLE)

    def test_voice_availability_is_option_specific_and_independent_of_body(self):
        bindings = self.catalog.bindings_for('oracle.voice')
        self.assertEqual({item.option for _, item in bindings}, set(VOICE_CLIPS))
        states = {'bell_voice': A.UNAVAILABLE}
        self.assertIs(self.catalog.setting_state('voice_bell', states), A.UNAVAILABLE)
        self.assertIs(self.catalog.setting_state('voice_none', states), A.AVAILABLE)
        self.assertEqual([key for key, _ in self.catalog.bindings_for('oracle.voice', option='none')], ['voice_none'])
        self.assertFalse(any('oracle.body_appearance' in item.paths for _, item in self.catalog.impacts_for('bell_voice')))
        self.assertIs(self.catalog.setting_state('voice_controls', states), A.UNKNOWN)

    def test_playback_provenance_does_not_add_watcher_runtime_dependency(self):
        curve = self.catalog.resources['pearl_playback_curve']
        self.assertEqual(curve.origins, ('watcher',))
        self.assertTrue(all(source.root == 'package' for source in curve.sources))
        states = {'main_atlas': A.AVAILABLE, 'pearl_playback_curve': A.AVAILABLE, 'bell_voice': A.UNAVAILABLE}
        self.assertIs(self.catalog.feature_state('pearl_playback', states), A.AVAILABLE)
        states['pearl_playback_curve'] = A.UNAVAILABLE
        self.assertIs(self.catalog.feature_state('pearls', states), A.AVAILABLE)

    def test_shared_projection_opacity_and_drag_switch_survive_missing_optional_assets(self):
        states = {'pearl_glyphs': A.UNAVAILABLE, 'scan_images': A.UNAVAILABLE, 'bell_voice': A.UNAVAILABLE}
        self.assertIs(self.catalog.setting_state('scan_projection', states), A.UNAVAILABLE)
        self.assertIs(self.catalog.feature_state('halo', states), A.AVAILABLE)
        self.assertIs(self.catalog.setting_state('projection_opacity', states), A.AVAILABLE)
        self.assertEqual(self.catalog.settings['projection_opacity'].mode, 'any')
        self.assertIs(self.catalog.setting_state('drag_reactions', states), A.UNKNOWN)
        self.assertIs(self.catalog.feature_state('drag_reactions', states), A.AVAILABLE)

    def test_unknown_is_not_unavailable_and_states_are_strict(self):
        self.assertIs(self.catalog.setting_state('voice_bell', {}), A.UNKNOWN)
        for states in ({'bell_voice': False}, {'misspelled_asset': A.UNAVAILABLE}):
            with self.subTest(states=states), self.assertRaises(CatalogError):
                self.catalog.feature_state('voice_bell', states)
        self.assertIs(self.catalog.feature_state('prince', {'prince_visuals': A.UNAVAILABLE}), A.UNAVAILABLE)
        self.assertIs(self.catalog.feature_state('prince', {'prince_visuals': A.AVAILABLE}), A.UNKNOWN)

    def test_reverse_impacts_are_narrow(self):
        glyph_impacts = {key for key, _ in self.catalog.impacts_for('pearl_glyphs')}
        self.assertEqual(glyph_impacts, {'game_directory', 'projection_opacity', 'pearl_glyph_colors'})
        voice_impacts = {key for key, _ in self.catalog.impacts_for('bell_voice')}
        self.assertNotIn('pearl_playback', voice_impacts)
        self.assertNotIn('halo', voice_impacts)
        with self.assertRaises(KeyError):
            self.catalog.impacts_for('missing_id')

    def test_atlas_sprite_inventory_matches_current_renderers(self):
        from rw_creature_pet.lizard.render import LizardRenderer
        from rw_creature_pet.oracle.graphics.render import OracleRenderer
        atlas = Mock()
        LizardRenderer(atlas)
        self.assertEqual({call.args[0] for call in atlas.sprite.call_args_list},
                         set(self.catalog.features['lizard_visuals'].sprites))
        self.assertEqual(set(OracleRenderer.SPRITES), set(self.catalog.features['oracle_visuals'].sprites))
        # 捕捉构造器预取以外的贴图，例如播放气泡 LizardBubble6
        for filename, feature_ids in (
            ('oracle/graphics/render.py', ('oracle_visuals', 'pearls', 'pearl_playback')),
            ('overseer/graphics/render.py', ('overseer_standard',)),
        ):
            declared = {sprite for key in feature_ids for sprite in self.catalog.features[key].sprites}
            tree = ast.parse((PACKAGE_ROOT/filename).read_text(encoding='utf-8'))
            actual = set()
            for call in ast.walk(tree):
                if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or call.func.attr != 'sprite':
                    continue
                index = 1 if isinstance(call.func.value, ast.Name) and call.func.value.id == 'self' else 0
                if len(call.args) > index and isinstance(call.args[index], ast.Constant):
                    if isinstance(call.args[index].value, str):
                        actual.add(call.args[index].value)
            self.assertLessEqual(actual, declared, filename)

    def test_custom_slots_and_maid_densities_match_real_definitions(self):
        custom = self.catalog.resources['custom_images']
        paths = {path for source in custom.sources for path in source.paths}
        self.assertEqual(paths, set(image_paths(OracleConfig(), full=True)))
        self.assertEqual(paths, set(self.catalog.settings['custom_images'].paths))
        self.assertEqual(self.catalog.settings['custom_images'].effect, 'related')
        maid = {path for source in self.catalog.resources['maid_images'].sources for path in source.paths}
        self.assertEqual(maid, {variant.asset for part in MAID.components for variant in part.variants})

    def test_packaged_resources_exist_and_have_no_game_path(self):
        result = report(self.catalog, check_package=True)
        self.assertTrue(result['package_files'])
        self.assertTrue(all(result['package_files'].values()))
        for key in ('prince_visuals', 'prince_layout', 'friend_head', 'maid_images', 'pearl_playback_curve'):
            self.assertTrue(all(source.root == 'package' for source in self.catalog.resources[key].sources), key)

    def test_build_manifests_include_catalog_and_python_module(self):
        root = PACKAGE_ROOT.parent
        project = tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))
        self.assertIn('catalog.toml', project['tool']['setuptools']['package-data']['rw_creature_pet.resources'])
        spec = (root/'tools/packaging/bell.spec').read_text(encoding='utf-8')
        self.assertIn("'rw_creature_pet/resources/catalog.toml'", spec)
        self.assertIn("'rw_creature_pet.resources'", spec)

    def test_invalid_manifest_references_and_typo_fields_are_rejected(self):
        original = tomllib.loads(CATALOG_PATH.read_text(encoding='utf-8'))
        edits = (
            lambda d: d.update(format_version=True),
            lambda d: d['resources']['main_atlas'].update(optional=True),
            lambda d: d['features']['voice_bell'].update(resources=['nonexistent']),
            lambda d: d['resources']['bell_voice'].update(origins=['nonexistent']),
            lambda d: d['resources']['bell_voice'].update(sources=[]),
            lambda d: d['resources']['main_atlas']['sources'][0].update(paths=['../escape']),
            lambda d: d['resources']['main_atlas']['sources'][0].update(paths=['C:/game']),
            lambda d: d['settings']['voice_bell'].update(mode='sometimes'),
            lambda d: d['settings']['voice_bell'].update(effect='disabled'),
            lambda d: d['settings']['voice_bell'].update(features=['nonexistent']),
            lambda d: d['settings']['voice_none'].update(option='bell'),
            lambda d: d['settings']['voice_bell'].update(paths=['oracle.voice', 'oracle.voice']),
        )
        for index, edit in enumerate(edits):
            with self.subTest(index=index):
                data = deepcopy(original)
                edit(data)
                with self.assertRaises(CatalogError):
                    parse_catalog(data)

    def test_audit_command_runs_without_game_extraction(self):
        result = subprocess.run([sys.executable, '-m', 'tools.maintenance.audit_resources', '--check-package', '--json'],
                                cwd=PACKAGE_ROOT.parent, capture_output=True, text=True, encoding='utf-8',
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(set(data['resources']), set(self.catalog.resources))
        self.assertTrue(all(data['package_files'].values()))


if __name__ == '__main__':
    unittest.main()
