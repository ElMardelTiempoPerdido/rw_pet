"""平地节奏的可观察约束：步幅、支撑、速度档与停止稳定性。"""
from statistics import mean
import unittest

from rw_creature_pet.lizard.config import DebugConfig
from rw_creature_pet.lizard.gait import FlatGait, FootPhase
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.lizard.scene import DebugScene


class FlatRhythmTests(unittest.TestCase):
    def scene(self, speed):
        s = DebugScene(DebugConfig(world_width=10000, world_height=500, floor_y=450))
        s.gait.enabled = True
        s.gait.set_speed(speed)
        return s

    def test_stride_cadence_and_support_at_both_paces_and_directions(self):
        speeds = {}
        for direction in (-1, 1):
            for intent in (FlatGait.SLOW_INTENT, FlatGait.TRACK_INTENT):
                s = self.scene(direction * FlatGait.MAX_SPEED * intent)
                for tick in range(200):
                    s.step()
                    if not s.gait.turning and tick > 100:
                        self.assertGreaterEqual(s.gait.grip_count, 2)
                start = s.body.chunks[1].position.x
                last_landing = [None] * 4
                strides = [[] for _ in s.feet]
                durations = []
                for _ in range(800):
                    old = [(f.phase, f.position) for f in s.feet]
                    s.step()
                    self.assertGreaterEqual(s.gait.grip_count, 2)
                    self.assertLess(max(s.body.connection_error(c) for c in s.body.connections), .002)
                    belly = s.body.chunks[1]
                    self.assertTrue(-1e-6 <= s.world.floor_y - belly.position.y - belly.radius < 1.5)
                    started = 0
                    for i, (f, (phase, point)) in enumerate(zip(s.feet, old)):
                        self.assertNotEqual(f.phase, FootPhase.AIR, '直行不得靠失附后重置脚的位置维持步态')
                        self.assertLessEqual((f.position-s.body.chunks[f.chunk_index].position).length(), FlatGait.REACH + 1e-6)
                        if f.phase == phase == FootPhase.STANCE:
                            self.assertEqual(f.position, point)
                        if f.phase == FootPhase.SWING and phase == FootPhase.STANCE:
                            started += 1
                        if f.phase == FootPhase.STANCE and phase == FootPhase.SWING:
                            if last_landing[i] is not None:
                                strides[i].append((f.position.x-last_landing[i]) * direction)
                            last_landing[i] = f.position.x
                            durations.append(f.swing_tick)
                    self.assertLessEqual(started, 1)
                averages = [mean(values) for values in strides]
                self.assertGreater(min(averages), 28, '不能退回频繁的小碎步')
                self.assertLess(max(averages) / min(averages), 1.15, '不能固定一侧长步、一侧短步')
                self.assertLess(max(durations), 8)
                speed = (s.body.chunks[1].position.x-start) * direction / 20
                self.assertTrue((29 < speed < 35) if intent == FlatGait.SLOW_INTENT else (44 < speed < 53))
                speeds[direction, intent] = speed
        for intent in (FlatGait.SLOW_INTENT, FlatGait.TRACK_INTENT):
            self.assertLess(abs(speeds[-1, intent]-speeds[1, intent]), 1)

    def test_swing_time_depends_on_distance_and_hip_speed(self):
        def duration(distance, hip_speed):
            s = self.scene(0)
            hip = s.body.chunks[0]
            hip.position = Vec2(100, s.world.floor_y-10)
            hip.velocity = Vec2(hip_speed, 0)
            foot = s.feet[0]
            foot.position = Vec2(100-distance/2, s.world.floor_y)
            s.gait._swing(foot, Vec2(100+distance/2, s.world.floor_y))
            while foot.phase == FootPhase.SWING:
                s.gait._advance_swing(foot, s.body)
                self.assertLessEqual(foot.position.y, s.world.floor_y)
                self.assertLess(foot.swing_tick, 20)
            self.assertEqual(foot.phase, FootPhase.STANCE)
            self.assertEqual(foot.position, foot.target)
            return foot.swing_tick
        self.assertLess(duration(10, 0), duration(40, 0))
        self.assertLess(duration(40, 3), duration(40, 0))

    def test_intent_changes_smoothly_and_fast_stop_settles(self):
        s = self.scene(FlatGait.MAX_SPEED * FlatGait.SLOW_INTENT)
        for _ in range(200): s.step()
        before = s.gait.move_intent
        s.gait.set_speed(FlatGait.MAX_SPEED * FlatGait.TRACK_INTENT)
        s.step()
        self.assertTrue(before < s.gait.move_intent < FlatGait.TRACK_INTENT)
        for _ in range(160): s.step()
        # 两足支撑时推进目标应弱于四足，不能把承重和牵引混为一谈。
        feedback = {}
        for _ in range(150):
            s.step()
            feedback.setdefault(s.gait.grip_count, []).append(s.gait.effective_speed)
        self.assertLess(mean(feedback[2]), mean(feedback[4]) * .7)
        s.gait.set_speed(0)
        s.gait.posture = 'raised'
        s.step()
        self.assertEqual(s.gait.effective_speed, 0)
        for _ in range(600):
            old = [(f.phase, f.position) for f in s.feet]
            s.step()
            self.assertGreaterEqual(s.gait.grip_count, 2)
            for f, (phase, pos) in zip(s.feet, old):
                self.assertNotEqual(f.phase, FootPhase.AIR)
                if f.phase == phase == FootPhase.STANCE:
                    self.assertEqual(f.position, pos, '收脚必须迈步，不能直接重置抓点')
        positions = [c.position for c in s.body.chunks]
        steps = [f.steps for f in s.feet]
        for _ in range(800): s.step()
        self.assertEqual(steps, [f.steps for f in s.feet])
        self.assertEqual(s.gait.grip_count, 4)
        for c, p in zip(s.body.chunks, positions):
            self.assertLess((c.position-p).length(), 1e-7)
            self.assertLess(c.velocity.length(), 1e-7)

    def test_maximum_speed_brakes_turns_and_leaves_boundary(self):
        for direction in (-1, 1):
            s = DebugScene(DebugConfig())
            s.gait.enabled = True
            s.gait.set_speed(direction * FlatGait.MAX_SPEED)
            identities = [id(c) for c in s.body.chunks]
            for _ in range(500): s.step()
            self.assertTrue(s.gait.blocked)
            start = s.body.chunks[1].position.x
            s.gait.set_speed(-direction * FlatGait.MAX_SPEED)
            for _ in range(180):
                previous = [c.position for c in s.body.chunks]
                s.step()
                for c, p in zip(s.body.chunks, previous):
                    self.assertLess((c.position-p).length(), 4)
                    self.assertTrue(c.radius <= c.position.x <= s.world.width-c.radius)
                self.assertLess(max(s.body.connection_error(c) for c in s.body.connections), .002)
            self.assertEqual([id(c) for c in s.body.chunks], identities)
            self.assertEqual(s.gait.facing, -direction)
            self.assertGreater((start-s.body.chunks[1].position.x)*direction, 60)
