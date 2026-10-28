"""Prince 离边距离、自然长度与各边缘方向配置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.prince_tentacles import (
    Tentacle, TentacleMotion, default_study, edge_directions, load_study, make_path,
)
from rw_creature_pet.oracle.motion.prince_tentacles import (
    GripRail, PrinceTentacles, SupportTentacle, edge_direction,
)
from rw_creature_pet.oracle.scene import OracleScene, OracleWorld
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.test_prince_tentacle_motion import host_at


class PrinceTentacleConfigTests(unittest.TestCase):
    def scene(self, study, side='right', **values):
        config = OracleConfig(body_appearance='prince', physics_backend='python',
            world_width=960, world_height=720, edge_fraction=.35, base_side=side,
            pearl_matrix_enabled=False, pearl_orbits_enabled=False,
            pearl_fixed_count=0, halo_enabled=False, **values)
        return OracleScene(config, prince_study=study)

    def test_file_loading_validates_motion_lengths_and_screen_directions(self):
        data = '''version = 1
[motion]
body_edge_distance = 120
[[tentacles]]
points = [[0, 0], [120, 0]]
length = 180
grip_reach = 0.7
root_directions = { top = [0, 2], right = [3, 0], bottom = [0, 1], left = [-1, 0] }
grip_directions = { top = [0, -1], right = [1, 0], bottom = [0, 1], left = [-1, 0] }
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'触手.toml'
            path.write_text(data, encoding='utf-8')
            study = load_study(path)
        self.assertEqual(study.motion.body_edge_distance, 120)
        part = study.tentacles[0]
        self.assertEqual(part.length, 180)
        self.assertEqual(part.grip_reach, .7)
        self.assertEqual(part.root_directions[0], Vec2(0, 1))
        self.assertEqual(make_path(part).length, 120)
        for value in (True, float('nan'), -1, 3000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Tentacle.parse({'points': [[0, 0], [20, 0]], 'length': value}, 0)
        for value in (True, float('nan'), -.1, 1.1):
            with self.subTest(grip_reach=value), self.assertRaises(ValueError):
                Tentacle.parse({'points': [[0, 0], [20, 0]], 'grip_reach': value}, 0)
        for data in ({'body_edge_distance': False}, {'body_edge_distance': float('inf')},
                     {'body_edge_distance': -1}, {'distance': 100}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                TentacleMotion.parse(data)
        for data in ({'top': [0, 1]}, {key: [0, 0] for key in ('top', 'right', 'bottom', 'left')},
                     {'up': [0, 1]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                edge_directions(data, 'directions')

    def test_start_reset_and_release_share_distance_on_four_edges(self):
        study = replace(default_study(), motion=TentacleMotion(120))
        for side in ('top', 'right', 'bottom', 'left'):
            with self.subTest(side=side):
                scene = self.scene(study, side)
                start = scene.body.chunks[0].position
                distances = (start.x, start.y, scene.world.width-start.x, scene.world.height-start.y)
                self.assertAlmostEqual(min(distances), 120)
                self.assertIs(scene.prince_tentacles.study, study)
                scene.drag.set_enabled(True)
                scene.drag.press(scene.head.position, lambda _: True)
                scene.drag.release()
                self.assertLess((scene.drag.home-start).length(), 1e-6)
                scene.reset()
                self.assertEqual(scene.body.chunks[0].position, start)

    def test_load_per_edge_grip_reach_and_reject_invalid_values(self):
        data = '''version = 1
[[tentacles]]
points = [[0, 0], [200, 0]]
grip_reach = { left = 0.8, bottom = 0.6, right = 0.4, top = 0.2 }
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'tentacles.toml'
            path.write_text(data, encoding='utf-8')
            part = load_study(path).tentacles[0]
        self.assertEqual(part.grip_reach, (.2, .4, .6, .8))
        minimal = {'points': [[0, 0], [200, 0]]}
        self.assertEqual(Tentacle.parse(minimal, 0).grip_reach, .65)
        for value in (False, float('nan'), float('inf'), -.1, 1.1, '0.5'):
            table = dict(top=value, right=.4, bottom=.6, left=.8)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'grip_reach.top'):
                Tentacle.parse(dict(minimal, grip_reach=table), 0)
        for table in ({}, {'top': .5}, dict(top=.2, right=.4, bottom=.6, left=.8, up=.5), [.5]*4):
            with self.subTest(table=table), self.assertRaises(ValueError):
                Tentacle.parse(dict(minimal, grip_reach=table), 0)

    def test_each_edge_uses_own_grip_reach_without_changing_other_edges(self):
        world = OracleWorld(960, 720, .35)
        rail = GripRail(world)
        study = default_study()
        ratios = (.2, .4, .6, .8)
        directions = (Vec2(1, 0), Vec2(0, 1), Vec2(-1, 0), Vec2(0, -1))
        part = replace(study.tentacles[0], length=200, grip_reach=ratios, grip_directions=directions)
        changed = replace(part, grip_reach=(.9, *ratios[1:]))
        for i, point in enumerate((Vec2(480, 0), Vec2(960, 360), Vec2(480, 720), Vec2(0, 360))):
            with self.subTest(edge=i):
                host = host_at(world, rail, rail.project(point))
                support = PrinceTentacles(host, replace(study, tentacles=(part,)))
                root = support.part_root(part)
                # 配置给出理想抓点；实际初始化会为长触手保留松弛余量
                grip = rail.sample(support.ideal_grip(part, root))[0]
                delta = grip-root
                along_edge = delta.x*directions[i].x+delta.y*directions[i].y
                self.assertAlmostEqual(along_edge, 200*ratios[i])
                updated = rail.sample(support.ideal_grip(changed, root))[0]
                self.assertAlmostEqual((updated-grip).length(), 140 if i == 0 else 0)

    def test_grip_reach_blends_with_direction_at_corner(self):
        world = OracleWorld(640, 480, .35)
        rail = GripRail(world)
        study = default_study()
        part = replace(study.tentacles[0], length=200, grip_reach=(.2, .8, .6, .4),
            grip_directions=(Vec2(0, -1), Vec2(1, 0), Vec2(0, 1), Vec2(-1, 0)))
        support = PrinceTentacles(host_at(world, rail, rail.project(Vec2(640, 80))),
                                  replace(study, tentacles=(part,)))
        root = Vec2(560, 80)
        support.outward = Vec2(.5, -.5)
        middle = rail.sample(support.ideal_grip(part, root))[0]
        # 混合顶部 (0, -40) 与右侧 (160, 0) 的偏移，再投影到内缩抓附边
        self.assertAlmostEqual(middle.x, world.width-rail.inset)
        self.assertAlmostEqual(middle.y, 60)
        support.outward = Vec2(.499, -.501)
        before = rail.sample(support.ideal_grip(part, root))[0]
        support.outward = Vec2(.501, -.499)
        after = rail.sample(support.ideal_grip(part, root))[0]
        self.assertLess((after-before).length(), .1)

    def test_uniform_grip_reach_table_matches_shared_number(self):
        world = OracleWorld(640, 480, .35)
        rail = GripRail(world)
        study = default_study()
        for definition in study.tentacles:
            scalar = replace(definition, grip_reach=.65)
            table = replace(definition, grip_reach=(.65,)*4)
            for s in (rail.length*i/12 for i in range(12)):
                support = PrinceTentacles(host_at(world, rail, s), replace(study, tentacles=(scalar,)))
                for outward in (support.outward, Vec2(.5, -.5), Vec2(-.25, .75)):
                    support.outward = outward
                    root = support.part_root(definition)
                    a = support.ideal_grip(scalar, root)
                    b = support.ideal_grip(table, root)
                    self.assertLess(abs(rail.delta(a, b)), 1e-8)

    def test_large_distance_is_clamped_and_bell_does_not_use_it(self):
        study = replace(default_study(), motion=TentacleMotion(1024))
        for side in ('top', 'right', 'bottom', 'left'):
            scene = self.scene(study, side)
            point = scene.body.chunks[0].position
            self.assertTrue(scene.body_region.contains(point))
            self.assertLess((scene.project_target(point)-point).length(), 1e-6)
            support = scene.prince_tentacles
            longest = max(support.parts, key=lambda p: p.reference_length)
            self.assertLessEqual((longest.grip-support.part_root(longest.definition)).length(),
                                 longest.reference_length*support.AUTO_REACH)
        config = replace(scene.config, body_appearance='bell', base_side='right')
        bell = OracleScene(config, prince_study=study)
        self.assertAlmostEqual(bell.world.width-bell.body.chunks[0].position.x, bell.world.rail_inset+64)
        self.assertIsNone(bell.prince_tentacles)

    def test_length_changes_chain_without_scaling_artwork(self):
        world = OracleWorld(640, 480, .35)
        rail = GripRail(world)
        grip_s = rail.project(Vec2(624, 240))
        root = Vec2(570, 240)
        original = default_study().tentacles[0]
        for length in (80., 160.):
            definition = replace(original, length=length)
            part = SupportTentacle(definition, root, Vec2(1, 0), grip_s, rail)
            self.assertEqual(part.reference_length, length)
            self.assertEqual(make_path(definition), make_path(original))
            self.assertEqual(definition.widths, original.widths)
            self.assertEqual(definition.bumps, original.bumps)
            for _ in range(450):
                part.step(root, Vec2(1, 0), rail)
            self.assertLessEqual(part.path(1).length, length+1e-6)
            self.assertGreater(part.path(1).length, length*.9)

    def test_each_edge_root_direction_is_used_in_screen_coordinates(self):
        values = (Vec2(1, 0), Vec2(0, 1), Vec2(-1, 0), Vec2(0, -1))
        world = OracleWorld(640, 480, .35)
        rail = GripRail(world)
        definition = replace(default_study().tentacles[0], root_directions=values)
        for point, expected in zip((Vec2(320, 0), Vec2(640, 240), Vec2(320, 480), Vec2(0, 240)), values):
            s = rail.project(point)
            tip = rail.sample(s)[0]
            outward = rail.normal(s)*-1
            root = tip-outward*80
            part = SupportTentacle(definition, root, outward, s, rail)
            self.assertEqual(part.preferred_direction(outward, root, tip), expected)
        # 相邻相反方向不会在角落放大为突然反转的单位向量
        opposite = (Vec2(1, 0), Vec2(-1, 0), Vec2(1, 0), Vec2(-1, 0))
        before = edge_direction(opposite, Vec2(.499, -.501))
        after = edge_direction(opposite, Vec2(.501, -.499))
        self.assertLess((after-before).length(), .01)

    def test_grip_direction_and_reach_choose_allowed_edge_points(self):
        world = OracleWorld(640, 480, .35)
        rail = GripRail(world)
        s = rail.project(Vec2(640, 240))
        host = host_at(world, rail, s)
        base = default_study()
        definition = replace(base.tentacles[0], length=200, grip_reach=.5)
        for y in (-1, 1):
            d = Vec2(0, y)
            part = replace(definition, grip_directions=(d, d, d, d))
            support = PrinceTentacles(host, replace(base, tentacles=(part,)))
            root = support.part_root(part)
            grip = support.parts[0].grip
            self.assertAlmostEqual(grip.x, world.width-rail.inset)
            self.assertAlmostEqual(grip.y-root.y, y*100)
        world = OracleWorld(640, 480, .35, allowed_edges=('left', 'top'))
        rail = GripRail(world)
        host = host_at(world, rail, rail.project(Vec2(320, 0)))
        support = PrinceTentacles(host, replace(base, tentacles=(part,)))
        grip = support.parts[0].grip
        self.assertTrue(grip.x == rail.inset or grip.y == rail.inset)

    def test_crossing_directly_to_opposite_edge_updates_direction(self):
        world = OracleWorld(640, 480, .35)
        rail = GripRail(world)
        host = host_at(world, rail, rail.project(Vec2(320, 480)))
        support = PrinceTentacles(host)
        self.assertEqual(support.outward, Vec2(0, 1))
        host.appearance.upper = Vec2(320, 96)
        for _ in range(80):
            support.step(host)
        self.assertEqual(support.outward, Vec2(0, -1))
        for part in support.parts:
            self.assertEqual(part.preferred_direction(support.outward,
                support.part_root(part.definition), part.grip), part.definition.root_directions[0])

    def test_clipped_grip_preference_does_not_replant_in_place(self):
        world = OracleWorld(640, 480, .35)
        rail = GripRail(world)
        host = host_at(world, rail, rail.project(Vec2(640, 240)), depth=110)
        host.drag = SimpleNamespace(controlling=True, active=False)
        base = default_study()
        parts = tuple(replace(p, length=100, grip_reach=1,
            grip_directions=(Vec2(0, -1),)*4) for p in base.tentacles)
        support = PrinceTentacles(host, replace(base, tentacles=parts))
        support.begin_drag()
        for i, old in enumerate(support.parts):
            root = support.part_root(old.definition)
            ideal = support.ideal_grip(old.definition, root, old.reference_length)
            target = support.reachable_target(old, ideal)
            self.assertGreater(abs(rail.delta(ideal, target)), support.REPLANT_DISTANCE)
            part = SupportTentacle(old.definition, root, support.outward, target, rail)
            part.length_limit = old.length_limit
            support.parts[i] = part
        grips = tuple(p.grip for p in support.parts)
        for _ in range(100):
            support.step(host)
            self.assertTrue(all(p.attached and not p.transferring for p in support.parts))
            self.assertEqual(tuple(p.grip for p in support.parts), grips)


if __name__ == '__main__':
    unittest.main()
