import unittest
from math import pi

from rw_creature_pet.config import DebugConfig
from rw_creature_pet.scene import DebugScene
from rw_creature_pet.geometry import Vec2
from rw_creature_pet.gait import FootPhase


class RhythmTests(unittest.TestCase):
    def scene(self):
        s = DebugScene(DebugConfig(world_width=5000, world_height=5000, floor_y=4900))
        s.place_on_background(2400)
        return s

    def test_turn_advances_during_swing_and_preserves_support(self):
        for target, angle in ((Vec2(0, 1), pi / 2), (Vec2(-1, 0), pi)):
            s = self.scene()
            s.background.set_direction(Vec2(1, 0))
            for _ in range(160):
                s.step()
            s.background.set_direction(target)
            advanced_during_swing = False
            for tick in range(120):
                old_heading = s.background.heading
                feet = [(f.phase, f.position) for f in s.feet]
                s.step()
                if any(f.phase == FootPhase.SWING for f in s.feet):
                    advanced_during_swing |= abs(s.background.heading - old_heading) > .001
                self.assertGreaterEqual(s.background.grip_count, 2)
                for foot, (phase, position) in zip(s.feet, feet):
                    if foot.phase == phase == FootPhase.STANCE:
                        self.assertEqual(foot.position, position)
                if abs((angle - s.background.heading + pi) % (2*pi) - pi) < .05:
                    break
            self.assertLess(tick, 100)
            self.assertTrue(advanced_during_swing)

    def test_intent_profiles_swing_distance_and_stop(self):
        speeds = []
        for tracking in (False, True):
            s = self.scene()
            if tracking:
                s.background.set_goal(Vec2(4500, 2500), s.body, s.world)
            else:
                s.background.set_direction(Vec2(1, 0))
            s.step()
            self.assertGreater(s.background.move_intent, 0)
            self.assertLess(s.background.move_intent, .1)
            durations = set()
            for _ in range(160):
                s.step()
                durations.update(f.swing_tick for f in s.feet if f.phase == FootPhase.STANCE and f.steps)
            start = s.body.chunks[1].position
            for _ in range(200):
                s.step()
            speeds.append((s.body.chunks[1].position - start).length() / 5)
            self.assertTrue(durations)
            self.assertLess(max(durations), 6)
            s.background.set_direction(Vec2())
            for _ in range(300):
                s.step()
            positions = [c.position for c in s.body.chunks]
            for _ in range(600):
                s.step()
            self.assertEqual(s.background.move_intent, 0)
            self.assertTrue(all((c.position-p).length() < 1e-8 for c, p in zip(s.body.chunks, positions)))
        self.assertTrue(30 < speeds[0] < 35)
        self.assertTrue(45 < speeds[1] < 60)
        self.assertGreater(speeds[1], speeds[0] * 1.5)

    def test_longer_reach_takes_longer_without_moving_stance_feet(self):
        durations = []
        for distance in (4, 20):
            s = self.scene()
            foot = s.feet[0]
            foot.phase = FootPhase.SWING
            foot.target = foot.position + Vec2(distance, 0)
            # 保证目标仍在半径内，用起点后移模拟长距离换抓点。
            if distance == 20:
                foot.target = foot.position
                foot.position = foot.position - Vec2(distance, 0)
            for tick in range(1, 10):
                s.step()
                if foot.phase == FootPhase.STANCE:
                    break
            self.assertEqual(foot.phase, FootPhase.STANCE)
            self.assertEqual(foot.position, foot.target)
            durations.append(tick)
        self.assertGreater(durations[1], durations[0])
