"""墙面步幅校准：各朝向等速、稳定抓附与大步后的转弯/停止。"""
from math import cos, pi, sin
from statistics import mean
import unittest

from rw_creature_pet.lizard.background import BackgroundGrip
from rw_creature_pet.lizard.config import DebugConfig
from rw_creature_pet.lizard.desktop import EdgeWorld
from rw_creature_pet.lizard.gait import FootPhase
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.lizard.scene import DebugScene
from tests.lizard.test_wall_observation import placed


def walking(angle=0, tracking=False):
    s = DebugScene(DebugConfig(world_width=5000, world_height=5000, floor_y=4900))
    s.place_on_background(2400)
    center = s.body.chunks[1].position
    for p in [*s.body.chunks, s.appearance.head, *s.appearance.tail]:
        d = p.position-center
        p.position = center+Vec2(d.x*cos(angle)-d.y*sin(angle), d.x*sin(angle)+d.y*cos(angle))
        p.previous_position = p.position
    s.background = BackgroundGrip(s.body)
    s.background.set_enabled(True, s.body, s.world)
    direction = Vec2(cos(angle), sin(angle))
    if tracking:
        s.background.set_goal(center+direction*1800, s.body, s.world)
    else:
        s.background.set_direction(direction)
    return s


class WallRhythmTests(unittest.TestCase):
    def assert_step(self, s):
        old = [(f.phase, f.position) for f in s.feet]
        before = [c.position for c in s.body.chunks]
        tail = [t.position for t in s.appearance.tail]
        s.step()
        self.assertGreaterEqual(s.background.grip_count, 2)
        self.assertLess(max(s.body.connection_error(c) for c in s.body.connections), .002)
        self.assertLess(max((c.position-p).length() for c, p in zip(s.body.chunks, before)), 2)
        self.assertLess(max((t.position-p).length() for t, p in zip(s.appearance.tail, tail)), 12)
        previous = s.body.chunks[2].position
        for segment in s.appearance.tail:
            self.assertLessEqual((segment.position-previous).length(), segment.length+1e-5)
            previous = segment.position
        starts = 0
        for f, (phase, pos) in zip(s.feet, old):
            self.assertNotEqual(f.phase, FootPhase.AIR, '正常爬行及转弯不得靠丢脚维持')
            self.assertLessEqual((f.position-s.body.chunks[f.chunk_index].position).length(), BackgroundGrip.REACH+1e-6)
            if f.phase == phase == FootPhase.STANCE:
                self.assertEqual(f.position, pos, '抓点必须固定在世界坐标')
            starts += f.phase == FootPhase.SWING and phase == FootPhase.STANCE
        self.assertLessEqual(starts, 1)
        return old

    def test_eight_headings_two_paces_stride_cadence_and_speed(self):
        for tracking in (False, True):
            speeds = []
            for i in range(8):
                s = walking(i*pi/4, tracking)
                for _ in range(180): self.assert_step(s)
                start = s.body.chunks[1].position
                last = [None]*4
                strides = [[] for _ in s.feet]
                steps = [0]*4
                for _ in range(600):
                    old = self.assert_step(s)
                    for j, (f, (phase, _)) in enumerate(zip(s.feet, old)):
                        if phase == FootPhase.SWING and f.phase == FootPhase.STANCE:
                            steps[j] += 1
                            if last[j] is not None:
                                strides[j].append((f.position-last[j]).length())
                            last[j] = f.position
                speed = (s.body.chunks[1].position-start).length()/15
                speeds.append(speed)
                self.assertTrue((49 < speed < 56) if tracking else (30 < speed < 35))
                averages = [mean(values) for values in strides]
                self.assertGreater(min(averages), 23)
                self.assertLess(max(averages), 30)
                # 空间落点允许各腿有不同步幅，但不能让某一条腿退化为高频小步。
                self.assertLess(max(averages)/min(averages), 1.2)
                self.assertLess(max(steps)/15, 2.5 if tracking else 1.5)
            self.assertLess(max(speeds)-min(speeds), .5, '不能随屏幕上下方向或斜向变速')

    def test_retarget_during_different_stride_phases_and_settle(self):
        for phase in (0, 8, 16, 24):
            for delta in (Vec2(0, 120), Vec2(-120, 0)):
                s = walking(tracking=True)
                for _ in range(160+phase): s.step()
                identities = [id(p) for p in [*s.body.chunks, *s.appearance.tail]]
                goal = s.body.chunks[1].position+delta
                s.background.set_goal(goal, s.body, s.world)
                for _ in range(650):
                    self.assert_step(s)
                    if s.background.arrived: break
                self.assertTrue(s.background.arrived)
                self.assertLess((s.body.chunks[1].position-goal).length(), .6)
                self.assertEqual(identities, [id(p) for p in [*s.body.chunks, *s.appearance.tail]])
                for _ in range(300): self.assert_step(s)
                positions = [p.position for p in s.body.chunks]
                steps = [f.steps for f in s.feet]
                for _ in range(200): self.assert_step(s)
                self.assertEqual(steps, [f.steps for f in s.feet])
                # 尾尖软节允许继续收敛，躯干与抓点必须静止；尾巴连续性在 assert_step 检查。
                self.assertLess(max((p.position-q).length() for p, q in zip(s.body.chunks, positions)), 1e-6)

    def test_wider_footholds_stay_inside_inner_and_outer_edge(self):
        # 侧展落点接近中央禁区时必须收在边缘带内，不能失附或越界取抓点。
        for center, angle in ((Vec2(22, 300), -pi/2), (Vec2(125, 300), -pi/2),
                              (Vec2(678, 300), pi/2), (Vec2(575, 300), pi/2)):
            s = placed(angle, center, edge=True)
            self.assertIsInstance(s.world, EdgeWorld)
            s.background.set_direction(Vec2(cos(angle), sin(angle)))
            for _ in range(170):
                self.assert_step(s)
                self.assertTrue(all(s.world.in_edge(f.position) for f in s.feet))
                self.assertTrue(all(s.world.in_edge(c.position) for c in s.body.chunks))
            s.background.set_direction(Vec2())
            for _ in range(150): self.assert_step(s)
