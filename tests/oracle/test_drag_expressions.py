"""拖动表情的时序、范围、独立随机流及取消边界"""
from collections import Counter
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.drag_expression_config import DragExpressionConfig, ExpressionChoice, EXPRESSION_KINDS
from rw_creature_pet.oracle.drag_reaction_config import DragReactionConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.presets.fields import scope_for
from rw_creature_pet.presets.profile import apply_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.shared.geometry import Vec2


def make_scene(expression=None, **options):
    scene = OracleScene(OracleConfig(hide_cords=True, halo_enabled=False, physics_backend='python',
        pearl_fixed_count=0, drag_expressions=expression or DragExpressionConfig(
            probability=1., squeezed=ExpressionChoice(True)), **options))
    scene.drag.set_enabled(True)
    return scene


def begin(scene):
    assert scene.drag.press(scene.head.position, lambda _: True)


def trigger(scene):
    if not scene.drag.active:
        begin(scene)
    scene.drag_expressions.wait = 0.
    scene.drag_expressions.step(scene)
    assert scene.eyes.expression is not None


def advance(scene, ticks):
    for _ in range(ticks):
        scene.drag_expressions.step(scene)


class DragExpressionTests(unittest.TestCase):
    def test_defaults_validation_and_profile_share_roundtrip(self):
        self.assertEqual(OracleConfig.from_mapping({}).drag_expressions, DragExpressionConfig())
        self.assertEqual(AppConfig.load(Path('config.toml')).oracle.drag_expressions, DragExpressionConfig())
        self.assertFalse(DragExpressionConfig().available)
        for bad in (True, None, -1, 1.01, float('nan'), float('inf'), '0.5'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                DragExpressionConfig(probability=bad)
        for field, bad in (('enabled', 1), ('large_only', 'false'), ('weight', True),
                           ('weight', -1), ('weight', 1001), ('weight', 1.2)):
            with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                ExpressionChoice(**{field: bad})
        expression = DragExpressionConfig(probability=.73, round=ExpressionChoice(True, 7, True),
                                          slant_in=ExpressionChoice(True, 2))
        config = AppConfig(oracle=OracleConfig(drag_expressions=expression))
        for kind in EXPRESSION_KINDS:
            for field in ('enabled', 'weight', 'large_only'):
                self.assertEqual(scope_for('oracle.drag_expressions.'+kind+'.'+field).value, 'profile')
        self.assertEqual(scope_for('oracle.drag_expressions.probability').value, 'profile')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sender, receiver = ProfileLibrary(root/'sender'), ProfileLibrary(root/'receiver')
            role = sender.export(config, 'Expressions')
            archive = sender.export_share(config, root/'role.zip', name=role.name, preset_id=role.id)
            imported = receiver.import_file(archive)
            restored = apply_profile(AppConfig(), imported, imported.path.parent)
            self.assertEqual(restored.oracle.drag_expressions, expression)

    def test_only_hit_starts_delayed_attempt_and_zero_probability_never_triggers(self):
        s = make_scene()
        self.assertFalse(s.drag.press(s.head.position, lambda _: False))
        advance(s, 100)
        self.assertIsNone(s.eyes.expression)
        with patch.object(s.drag_expressions.timing_random, 'uniform', return_value=.5):
            begin(s)
        advance(s, 19)
        self.assertIsNone(s.eyes.expression)
        advance(s, 1)
        self.assertEqual(s.eyes.expression, 'squeezed')
        s.config = replace(s.config, drag_expressions=replace(s.config.drag_expressions, probability=0.))
        advance(s, 400)
        self.assertIsNone(s.eyes.expression)

    def test_enabled_weight_and_large_filter_precede_weighted_choice(self):
        s = make_scene(DragExpressionConfig(probability=1., squeezed=ExpressionChoice(True, 1),
            round=ExpressionChoice(True, 3), slant_in=ExpressionChoice(True, 0),
            slant_out=ExpressionChoice(False, 1000), chevron_up=ExpressionChoice(True, 1000, True)))
        begin(s)
        r = s.drag_expressions
        counts = Counter()
        for _ in range(1200):
            r.clear(s)
            r.wait = 0.
            r.step(s)
            counts[r.kind] += 1
        self.assertEqual(set(counts), {'squeezed', 'round'})
        self.assertTrue(.70 < counts['round']/1200 < .80, counts)
        s.config = replace(s.config, drag_expressions=DragExpressionConfig(
            probability=1., round=ExpressionChoice(True, 0), slant_in=ExpressionChoice(True, 2, True)))
        advance(s, 400)
        self.assertIsNone(s.eyes.expression)

    def test_expression_holds_without_reroll_and_has_a_gap_after_expiry(self):
        s = make_scene()
        trigger(s)
        r = s.drag_expressions
        r.remaining = .5
        state, timing, revision = r.random.getstate(), r.timing_random.getstate(), s.eyes.revision
        advance(s, 19)
        self.assertEqual(s.eyes.expression, 'squeezed')
        self.assertEqual((r.random.getstate(), r.timing_random.getstate(), s.eyes.revision), (state, timing, revision))
        advance(s, 1)
        self.assertIsNone(s.eyes.expression)
        self.assertTrue(1.5 <= r.wait <= 4.)
        advance(s, 59)
        self.assertIsNone(s.eyes.expression)

    def test_release_deadline_is_drawn_once_and_earlier_than_natural_expiry_wins(self):
        for natural, delay, ticks in ((4., .5, 20), (.25, 5., 10), (5., 5., 200), (3., 0., 0)):
            with self.subTest(natural=natural, delay=delay):
                s = make_scene()
                trigger(s)
                s.drag_expressions.remaining = natural
                with patch.object(s.drag_expressions.timing_random, 'uniform', return_value=delay) as draw:
                    s.drag.release()
                    s.drag.release()
                    self.assertEqual(draw.call_count, 1)
                    if ticks:
                        advance(s, ticks-1)
                        self.assertIsNotNone(s.eyes.expression)
                        advance(s, 1)
                    self.assertIsNone(s.eyes.expression)
                    advance(s, 400)
                    self.assertEqual(draw.call_count, 1)
                    self.assertIsNone(s.eyes.expression)

    def test_release_before_first_attempt_never_queues_and_regrab_keeps_natural_lifetime(self):
        s = make_scene()
        begin(s)
        s.drag.release()
        advance(s, 400)
        self.assertIsNone(s.eyes.expression)
        trigger(s)
        s.drag_expressions.remaining = 2.
        with patch.object(s.drag_expressions.timing_random, 'uniform', return_value=.5):
            s.drag.release()
        advance(s, 10)
        begin(s)
        self.assertIsNone(s.drag_expressions.release_remaining)
        self.assertAlmostEqual(s.drag_expressions.remaining, 1.75)
        advance(s, 11)  # 超过旧松手期限，原表情仍在
        self.assertEqual(s.eyes.expression, 'squeezed')
        advance(s, 59)
        self.assertIsNone(s.eyes.expression)

    def test_cancel_after_release_disable_and_petting_clear_immediately(self):
        for action in ('cancel', 'disable_drag', 'disable_choice', 'petting', 'prince'):
            with self.subTest(action=action):
                s = make_scene()
                trigger(s)
                with patch.object(s.drag_expressions.timing_random, 'uniform', return_value=5.):
                    s.drag.release()
                if action == 'cancel':
                    s.drag.release(cancel=True)  # 已松手时暂停也必须清除
                elif action == 'disable_drag':
                    s.drag.set_enabled(False)
                elif action == 'disable_choice':
                    s.config = replace(s.config, drag_expressions=DragExpressionConfig())
                    advance(s, 1)
                elif action == 'petting':
                    s.mouse_reaction.petting.active = True
                    advance(s, 1)
                else:
                    s.config = replace(s.config, body_appearance='prince')
                    s.sync_character()
                self.assertIsNone(s.eyes.expression)
                advance(s, 250)
                self.assertIsNone(s.eyes.expression)

    def test_large_drag_uses_recent_pointer_range_even_when_body_cannot_follow(self):
        s = make_scene(DragExpressionConfig(probability=1., round=ExpressionChoice(True, 1, True)))
        begin(s)
        body = tuple(c.position for c in s.body.chunks)
        p = s.drag.controller.pointer
        for i in range(100):
            s.drag.move(p+Vec2(i*.5, 0))  # 总位移虽大，近期窗口内范围不足
            advance(s, 1)
        self.assertFalse(s.drag_expressions.candidates())
        s.drag.move(p+Vec2(5000, 0))
        s.drag_expressions.wait = 0.
        advance(s, 1)
        self.assertEqual(s.eyes.expression, 'round')
        self.assertEqual(tuple(c.position for c in s.body.chunks), body)
        advance(s, 70)  # 停止移动后，时间窗口和短暂资格保留均消退
        self.assertFalse(s.drag_expressions.candidates())

    def test_expression_channel_does_not_change_any_existing_channel_or_autonomy(self):
        scenes = [make_scene(DragExpressionConfig(probability=1., round=ExpressionChoice(enabled)),
                            drag_reactions=DragReactionConfig(gesture_probability=1., voice_probability=1.,
                                                              eye_open_probability=1.))
                  for enabled in (False, True)]
        traces = []
        for s in scenes:
            s.appearance.step = lambda _: None
            begin(s)
            trace = []
            for _ in range(250):
                s.step()
                r = s.drag_reactions
                trace.append((r.gesturing, s.eyes.openness, r.voice.request_count,
                              s.projection.starts, s.body.chunks[0].position))
            traces.append(trace)
        self.assertEqual(*traces)
        for name in ('random', 'eye_random', 'eye_timing_random', 'voice_random'):
            self.assertEqual(getattr(scenes[0].drag_reactions, name).getstate(),
                             getattr(scenes[1].drag_reactions, name).getstate())
        self.assertEqual(scenes[0].drag_reactions.projection.random.getstate(),
                         scenes[1].drag_reactions.projection.random.getstate())
        self.assertEqual(scenes[0].behavior.random.getstate(), scenes[1].behavior.random.getstate())
        s = make_scene(drag_reactions=DragReactionConfig(enabled=False))
        trigger(s)
        self.assertEqual(s.eyes.expression, 'squeezed')
        self.assertFalse(s.drag_reactions.active)


if __name__ == '__main__':
    unittest.main()
