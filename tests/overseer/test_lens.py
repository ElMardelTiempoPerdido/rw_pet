import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from dataclasses import replace
import unittest

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.shared.geometry import Bounds, Vec2
from rw_creature_pet.shared.timing import FixedStepper
from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.events import EventPhase, OverseerEvents, SpawnContext
from rw_creature_pet.overseer.graphics.lens import ObservationLens
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.overseer.graphics.render import OverseerRenderer


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.config = replace(OverseerConfig(), observation_probability=1, observation_interval=.1)
        self.lens = ObservationLens(self.config, 42)

    def step(self, count=1, **kwargs):
        options = dict(eligible=True, visible=True)
        options.update(kwargs)
        for _ in range(count):
            self.lens.step(tick_rate=40, **options)

    def test_interval_single_roll_duration_and_no_overlapping_observations(self):
        self.step(3)
        self.assertEqual(self.lens.check_count, 0)
        self.step()
        self.assertEqual(self.lens.check_count, 1)
        self.assertEqual(self.lens.observation_count, 1)
        self.assertGreaterEqual(self.lens.remaining, 3)
        self.assertLessEqual(self.lens.remaining, 7)
        self.step(29)
        self.assertAlmostEqual(self.lens.up, 1)
        for _ in range(400):
            self.step()
            self.assertEqual(self.lens.observation_count, 1)
            if self.lens.up == self.lens.previous_up == 0:
                break
        else:
            self.fail('观察未自然合拢')
        # 完全合拢的这一帧已经推进 1 tick，仍需走完剩余间隔才抽签。
        while self.lens.check_remaining > .025+1e-8:
            self.step()
            self.assertEqual(self.lens.observation_count, 1)
        self.step()
        self.assertEqual(self.lens.observation_count, 2)

    def test_no_target_hidden_and_zero_probability_do_not_roll(self):
        rng = self.lens.random.getstate(), self.lens.visual_random.getstate()
        for _ in range(400):
            self.lens.step(eligible=False, visible=False, tick_rate=40)
        self.assertEqual((self.lens.random.getstate(), self.lens.visual_random.getstate()), rng)
        self.assertEqual(self.lens.check_count, 0)
        self.lens.configure(replace(self.config, observation_probability=0))
        self.step(100)
        self.assertEqual((self.lens.random.getstate(), self.lens.visual_random.getstate()), rng)

    def test_friend_uses_longer_duration_and_switching_back_restores_normal_range(self):
        from rw_creature_pet.overseer.graphics.friend.light import OBSERVATION_DURATION
        model = Overseer(config=self.config, seed=53)
        for appearance, limits in (('friend', OBSERVATION_DURATION),
                                   ('standard', ObservationLens.DURATION),
                                   ('friend', OBSERVATION_DURATION)):
            model.set_appearance(appearance)
            model.show()
            count = model.lens.observation_count
            target = model.root+model.normal*250
            for _ in range(200):
                model.step(target)
                if model.lens.observation_count > count:
                    break
            self.assertEqual(model.lens.observation_count, count+1)
            self.assertGreaterEqual(model.lens.remaining, limits[0])
            self.assertLessEqual(model.lens.remaining, limits[1])
            if appearance == 'friend':
                self.assertGreater(model.lens.remaining, ObservationLens.DURATION[1])
            for _ in range(40):
                model.step(target)
            self.assertEqual(model.lens.up, 1.)
            model.request_withdraw()
            model.step(target)
            self.assertEqual(model.lens.remaining, 0.)
            self.assertTrue(0 < model.lens.up < 1.)
            for _ in range(60):
                model.step(target)
            self.assertEqual(model.lens.up, 0.)

    def test_interrupt_close_is_smooth_and_setting_interval_restarts_wait(self):
        self.step(40)
        self.assertEqual(self.lens.up, 1)
        self.lens.configure(replace(self.config, observation_probability=0, observation_interval=2))
        self.step()
        self.assertEqual(self.lens.remaining, 0)
        self.assertAlmostEqual(self.lens.up, 1-1/30)
        self.step(40)
        self.assertEqual(self.lens.up, 0)
        self.lens.configure(replace(self.config, observation_interval=2))
        self.step(79)
        self.assertEqual(self.lens.observation_count, 1)
        self.step()
        self.assertEqual(self.lens.observation_count, 2)

    def test_pause_does_not_advance_timer_animation_or_randomness(self):
        self.step(10)
        snapshot = (self.lens.up, self.lens.remaining, self.lens.check_remaining,
                    self.lens.random.getstate(), self.lens.visual_random.getstate(),
                    self.lens.flicker_random.getstate(), self.lens.effect_tick, self.lens.line_noise)
        clock = FixedStepper(40)
        clock.set_paused(True)
        clock.advance(60, self.step)
        self.assertEqual(snapshot, (self.lens.up, self.lens.remaining, self.lens.check_remaining,
                                   self.lens.random.getstate(), self.lens.visual_random.getstate(),
                                   self.lens.flicker_random.getstate(), self.lens.effect_tick, self.lens.line_noise))

    def test_closing_breaks_lines_and_snaps_endpoints_without_dimming_survivors(self):
        self.step(40)
        center, gaze = Vec2(400, 300), Vec2(.6, .4)
        full = self.lens.segments(center, gaze, 1, 1)
        self.assertEqual(len(full), self.lens.line_count)
        self.assertFalse(any(p == center for a, b, _ in full for p in (a, b)))
        counts, snaps, frames = [], 0, set()
        for _ in range(60):
            self.step()
            self.lens.up = self.lens.previous_up = .5
            before = self.lens.flicker_random.getstate(), self.lens.line_noise, self.lens.effect_tick
            lines = self.lens.segments(center, gaze, 1, 1)
            self.assertEqual(lines, self.lens.segments(center, gaze, 1, 1))
            self.assertEqual(before, (self.lens.flicker_random.getstate(), self.lens.line_noise, self.lens.effect_tick))
            self.assertTrue(all(opacity == .85 for _, _, opacity in lines))
            counts.append(len(lines))
            snaps += sum(p == center for a, b, _ in lines for p in (a, b))
            frames.add(lines)
        self.assertTrue(.35 < sum(counts)/(len(counts)*self.lens.line_count) < .65)
        self.assertGreater(snaps, 0)
        self.assertGreater(len(frames), 40)
        self.step(40, eligible=False)
        self.assertEqual(self.lens.segments(center, gaze, 1, 1), ())
        snapshot = self.lens.effect_tick, self.lens.flicker_random.getstate()
        self.step(80, eligible=False)
        self.assertEqual(snapshot, (self.lens.effect_tick, self.lens.flicker_random.getstate()))

    def test_avoidance_expiry_and_relocation_end_observation(self):
        model = Overseer(config=replace(self.config, relocation_probability=1,
                                        duration_min=30, duration_max=30))
        events = OverseerEvents(model, seed=5)
        context = SpawnContext(model.bounds)
        events.start(context)
        target = Vec2(480, 300)
        for _ in range(125):
            events.step(target, context_factory=lambda: context)
        self.assertEqual(model.lens.up, 1)
        root, count = model.root, events.event_count
        events.step(target, threat=root, context_factory=lambda: context)
        self.assertEqual(model.lens.remaining, 0)
        self.assertLess(model.lens.up, 1)
        for _ in range(100):
            events.step(target, threat=root, context_factory=lambda: context)
            if model.root != root:
                break
        self.assertNotEqual(root, model.root)
        self.assertEqual(model.lens.up, 0)
        self.assertEqual(events.event_count, count)
        self.assertEqual(model.lens.check_remaining, .1)
        for _ in range(125):
            events.step(target, context_factory=lambda: context)
        self.assertEqual(model.lens.up, 1)
        events.remaining = .025
        events.step(target, context_factory=lambda: context)
        self.assertEqual(events.phase, EventPhase.EXITING)
        self.assertEqual(model.lens.remaining, 0)
        for _ in range(80):
            events.step(target, context_factory=lambda: context)
        self.assertFalse(model.active)
        self.assertEqual((model.lens.up, model.lens.previous_up), (0, 0))

    def test_observation_randomness_does_not_change_body_or_event_randomness(self):
        models = [Overseer(config=replace(self.config, observation_probability=p)) for p in (0, 1)]
        events = [OverseerEvents(m, seed=5) for m in models]
        for e in events:
            e.preview(e.model.bounds, Anchor(Edge.BOTTOM, .5))
        for _ in range(500):
            for e in events:
                e.step(Vec2(480, 300), context_factory=lambda: SpawnContext(e.model.bounds))
        a, b = models
        self.assertEqual(a.head.position, b.head.position)
        self.assertEqual(a.random.getstate(), b.random.getstate())
        self.assertEqual(events[0].random.getstate(), events[1].random.getstate())
        self.assertGreater(b.lens.observation_count, 0)
        self.assertEqual(a.lens.observation_count, 0)

    def test_projected_geometry_stays_local_through_gaze_and_retraction(self):
        self.step(50)
        center = Vec2(400, 300)
        for gaze in (Vec2(), Vec2(1, 0), Vec2(-1, 0), Vec2(0, 1), Vec2(0, -1), Vec2(.7, .7)):
            for extension in (.01, .2, .5, 1):
                for size in (.5, 1):
                    lines = self.lens.segments(center, gaze, extension, size, .5)
                    if extension == 1:
                        self.assertEqual(len(lines), self.lens.line_count)
                    for a, b, opacity in lines:
                        self.assertLessEqual((a-center).length(), self.lens.MAX_EXTENT)
                        self.assertLessEqual((b-center).length(), self.lens.MAX_EXTENT)
                        self.assertTrue(0 <= opacity <= 1)

    def test_four_edge_render_is_cached_and_contains_lens_without_wall_leak(self):
        app = QApplication.instance() or QApplication([])
        renderer = OverseerRenderer()
        for edge in Edge:
            model = Overseer(Bounds(0, 0, 300, 300), self.config)
            model.show(anchor=Anchor(edge, .5))
            for _ in range(125):
                model.step(Vec2(150, 150))
            self.assertEqual(model.lens.up, 1)
            before = (model.lens.random.getstate(), model.lens.visual_random.getstate(), model.revision,
                      model.lens.flicker_random.getstate(), model.lens.effect_tick)
            for mode, density in (('classic', 1), ('adaptive', 1.5), ('adaptive', 2)):
                image = QImage(320, 320, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                p = QPainter(image)
                try:
                    renderer.draw(p, model, .5, pixel_mode=mode, raster_scale=density)
                    cached = renderer.image
                    renderer.draw(p, model, .5, pixel_mode=mode, raster_scale=density)
                    self.assertIs(renderer.image, cached)
                finally:
                    p.end()
                self.assertLess(cached.width()*cached.height(), 60000)
                self.assertTrue(any(bytes(image.constBits())))
                for rect in ((300, 0, 20, 320), (0, 300, 320, 20)):
                    outside = image.copy(*rect)
                    self.assertFalse(any(bytes(outside.constBits())))
            self.assertEqual(before, (model.lens.random.getstate(), model.lens.visual_random.getstate(), model.revision,
                                     model.lens.flicker_random.getstate(), model.lens.effect_tick))
