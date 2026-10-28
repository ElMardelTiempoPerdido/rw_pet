"""触手固定抓点、逐条换点、跨边、角色切换与渲染范围"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import isfinite
from types import SimpleNamespace
import unittest

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.scene import OracleScene, OracleWorld
from rw_creature_pet.oracle.motion.prince_tentacles import GripRail, PrinceTentacles, SupportTentacle
from rw_creature_pet.oracle.prince_tentacles import default_study, make_path
from rw_creature_pet.oracle.graphics.damage import body_bounds, visual_bounds
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.graphics.prince_tentacles import draw_bump
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.shared.geometry import Vec2


def scene_at(side='right', **values):
    return OracleScene(OracleConfig(body_appearance='prince', physics_backend='python',
        base_side=side, pearl_matrix_enabled=False, pearl_orbits_enabled=False,
        pearl_fixed_count=0, halo_enabled=False, **values))


def host_at(world, rail, s, depth=76.):
    base = rail.sample(s)[0]
    upper = base+rail.normal(s)*depth
    posture = SimpleNamespace(frame=lambda *_: SimpleNamespace(chest=upper, chest_direction=Vec2(0, -1)))
    return SimpleNamespace(world=world, base=base, prince_posture=posture,
                           appearance=SimpleNamespace(upper=upper, direction=Vec2(0, -1)))


class TentacleTensionTests(unittest.TestCase):
    def setUp(self):
        self.rail = GripRail(OracleWorld(640, 480, .3))
        self.s = self.rail.project(Vec2(639, 200))
        self.tip = self.rail.sample(self.s)[0]
        self.outward = Vec2(1, 0)

    def part(self, definition):
        length = make_path(definition).length
        root = self.tip-Vec2(length*.6, 0)
        return SupportTentacle(definition, root, self.outward, self.s, self.rail), root

    def test_inertial_chain_straightens_under_tension_then_sags_and_sleeps(self):
        for definition in default_study().tentacles:
            with self.subTest(name=definition.name):
                part, rest_root = self.part(definition)
                part.length_limit = part.reference_length*PrinceTentacles.MAX_DRAG_STRETCH
                for tick in range(81):
                    ratio = .6+min(tick/40, 1.)*.55
                    root = self.tip-Vec2(part.reference_length*ratio, 0)
                    part.step(root, self.outward, self.rail)
                    self.assertEqual(part.nodes[0].position, root)
                    self.assertEqual(part.nodes[-1].position, self.tip)
                    if ratio >= 1.:
                        self.assertLess(max(abs(p.position.y-self.tip.y) for p in part.nodes), .001)
                    self.assertLessEqual(part.path(1).length, part.length_limit+1e-6)
                for _ in range(500):
                    before = tuple(n.position for n in part.nodes)
                    part.step(rest_root, self.outward, self.rail)
                    if part.sleeping:
                        # 休眠只冻结当前姿态，最后一帧不能跳到另一条目标轮廓
                        self.assertLess(max((n.position-p).length() for n,p in zip(part.nodes,before)), .03)
                        break
                self.assertTrue(part.sleeping)
                self.assertGreater(max(p.position.y-self.tip.y for p in part.nodes), 5.)
                resting = part.path(1)
                for _ in range(80):
                    self.assertFalse(part.step(rest_root, self.outward, self.rail))
                self.assertEqual(part.path(1), resting)

    def test_gravity_always_points_down_on_all_four_edges(self):
        definition = default_study().tentacles[-1]
        for side in (Vec2(320, 0), Vec2(640, 240), Vec2(320, 480), Vec2(0, 240)):
            with self.subTest(side=side):
                s = self.rail.project(side)
                tip, _ = self.rail.sample(s)
                inward = self.rail.normal(s)
                root = tip+inward*70
                part = SupportTentacle(definition, root, inward*-1, s, self.rail)
                part.ROOT_DIRECTION_FORCE = part.BEND_STIFFNESS = 0.
                for i,node in enumerate(part.nodes):
                    node.position = node.previous_position = root.lerp(tip,i/(len(part.nodes)-1))
                middle = part.nodes[len(part.nodes)//2]
                before = middle.position
                part.step(root, inward*-1, self.rail)
                self.assertAlmostEqual(middle.position.x,before.x)
                self.assertAlmostEqual(middle.position.y-before.y,part.GRAVITY)

    def test_launch_mirrors_horizontally_without_rotating_downward_bias(self):
        part, _ = self.part(default_study().tentacles[0])
        root = Vec2(320,240)
        right = part.preferred_direction(Vec2(1,0),root,root+Vec2(100,-80))
        left = part.preferred_direction(Vec2(-1,0),root,root+Vec2(-100,-80))
        top = part.preferred_direction(Vec2(0,-1),root,root+Vec2(-80,-100))
        self.assertGreater(right.y,0)
        self.assertAlmostEqual(right.y,left.y)
        self.assertAlmostEqual(right.x,-left.x)
        # 长触手在顶部仍先下垂，再回抓上方，不将右边的下垂旋转为侧向
        self.assertGreater(top.y,0)

    def test_interior_reference_shape_is_not_a_running_force(self):
        base = default_study().tentacles[0]
        points = (Vec2(0,0),Vec2(20,0),Vec2(30,30),Vec2(60,30),Vec2(90,0))
        a = replace(base,points=points,smoothness=0)
        b = replace(base,points=tuple(Vec2(p.x,-p.y) for p in points),smoothness=0)
        first, root = self.part(a)
        second, _ = self.part(b)
        self.assertAlmostEqual(first.reference_length,second.reference_length)
        for tick in range(240):
            moving = root+Vec2(0,min(tick,30)*.5)
            for part in (first,second):
                part.step(moving,self.outward,self.rail)
            self.assertEqual(first.path(1),second.path(1))
        self.assertGreater(max(p.position.y-first.nodes[-1].position.y for p in first.nodes),5.)

    def test_moving_root_does_not_translate_whole_chain_or_slide_grip(self):
        part, root = self.part(default_study().tentacles[0])
        for _ in range(450):
            part.step(root,self.outward,self.rail)
        positions = [n.position for n in part.nodes]
        moved = root+Vec2(0,-2)
        part.step(moved,self.outward,self.rail)
        self.assertEqual(part.nodes[0].position,moved)
        self.assertEqual(part.nodes[-1].position,self.tip)
        middle = len(part.nodes)//2
        self.assertLess((part.nodes[middle].position-positions[middle]).length(),(moved-root).length()*.75)


class TentacleMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_tip_decorations_fit_inside_workarea_on_every_edge(self):
        for side in ('top', 'right', 'bottom', 'left'):
            scene = scene_at(side, world_width=640, world_height=480, edge_fraction=.35, base_fraction=.6)
            scene.behavior.enabled = False
            for _ in range(200):
                scene.look_target = scene.body.chunks[0].position+Vec2(-60, 0)
                scene.step()
            world, support = scene.world, scene.prince_tentacles
            for scale in (1., 1.5, 2.):
                with self.subTest(side=side, scale=scale):
                    width, height, margin = round(world.width*scale), round(world.height*scale), 24
                    image = QImage(width+2*margin, height+2*margin, QImage.Format.Format_ARGB32_Premultiplied)
                    image.fill(0)
                    painter = QPainter(image)
                    try:
                        painter.translate(margin, margin)
                        painter.scale(scale, scale)
                        painter.setPen(Qt.PenStyle.NoPen)
                        for part in support.parts:
                            path = part.path(1)
                            for bump in (*part.definition.bumps, *part.definition.cores):
                                draw_bump(painter, path, bump, QColor('#6644CC'))
                    finally:
                        painter.end()
                    cropped = QImage(image.size(), image.format())
                    cropped.fill(0)
                    painter = QPainter(cropped)
                    painter.drawImage(margin, margin, image.copy(margin, margin, width, height))
                    painter.end()
                    # 在工作区外额外留画布，确认末端装饰没有被窗口裁掉的像素
                    self.assertEqual(image, cropped)

    def test_inset_grips_do_not_move_body_home_after_release(self):
        for side in ('top', 'right', 'bottom', 'left'):
            with self.subTest(side=side):
                scene = scene_at(side)
                initial = scene.body.chunks[0].position
                scene.drag.set_enabled(True)
                self.assertTrue(scene.drag.press(scene.head.position, lambda _: True))
                scene.drag.release()
                self.assertLess((scene.drag.home-initial).length(), 1e-6)

    def test_release_returns_to_supporting_edge_after_crossing_screen_midline(self):
        scene = scene_at('top')
        support = scene.prince_tentacles
        scene.drag.set_enabled(True)
        self.assertTrue(scene.drag.press(scene.head.position, lambda _: True))
        support.guard = next(p for p in support.parts if p.grip.y == support.rail.inset)
        upper = Vec2(scene.world.width*.5, scene.world.height*.6)
        scene.body.chunks[0].position = upper
        scene.body.chunks[1].position = upper-scene.body.direction*scene.body.connection_length
        support.location = support.rail.project(upper)
        self.assertEqual(support.rail.normal(support.location), Vec2(0, -1))
        scene.drag.release()
        expected = scene.project_target(Vec2(scene.drag.home.x, support.study.motion.body_edge_distance))
        self.assertAlmostEqual(scene.drag.home.y, expected.y)

    def test_world_grips_hold_then_only_one_tentacle_replants(self):
        world = OracleWorld(640, 480, .3)
        rail = GripRail(world)
        start = rail.project(Vec2(639, 200))
        support = PrinceTentacles(host_at(world, rail, start))
        initial = tuple(p.grip for p in support.parts)
        for tick in range(40):
            support.step(host_at(world, rail, start+tick*.4))
            self.assertEqual(tuple(p.grip for p in support.parts), initial)
            self.assertFalse(any(p.transferring for p in support.parts))
        released = set()
        planted = [p.grip for p in support.parts]
        for tick in range(1, 360):
            support.step(host_at(world, rail, start+16+tick*.55))
            active = [i for i, p in enumerate(support.parts) if p.transferring]
            self.assertLessEqual(len(active), 1)
            released.update(active)
            for i, p in enumerate(support.parts):
                if not p.transferring:
                    self.assertEqual(p.nodes[-1].position, p.grip)
                if p.grip != planted[i]:
                    self.assertEqual(p.grip, rail.sample(p.grip_s)[0])
                    planted[i] = p.grip
        self.assertEqual(released, {0, 1, 2})

    def test_idle_settles_without_random_replants_or_revision_churn(self):
        scene = scene_at()
        for _ in range(450):
            scene.step()
        support = scene.prince_tentacles
        self.assertTrue(support.settled)
        state = (support.revision, support.paths(), tuple(p.grip for p in support.parts))
        for _ in range(120):
            scene.step()
        self.assertEqual((support.revision, support.paths(), tuple(p.grip for p in support.parts)), state)

    def test_all_edges_corners_and_open_rail_stay_finite_and_connected(self):
        for edges in (('top', 'right', 'bottom', 'left'), ('left', 'top'), ('right',)):
            world = OracleWorld(640, 385, .3, allowed_edges=edges)
            rail = GripRail(world)
            support = PrinceTentacles(host_at(world, rail, 0))
            for tick in range(1500):
                s = tick*2. if rail.closed else min(tick*1.5, rail.length)
                support.step(host_at(world, rail, s))
                self.assertLessEqual(sum(p.transferring for p in support.parts), 1)
                for part in support.parts:
                    self.assertLess((part.nodes[0].position-support.part_root(part.definition)).length(), 1e-8)
                    for node in part.nodes:
                        self.assertTrue(isfinite(node.position.x) and isfinite(node.position.y))
                    if part.attached:
                        margins = (part.grip.x, world.width-part.grip.x,
                                   part.grip.y, world.height-part.grip.y)
                        self.assertAlmostEqual(min(margins), rail.inset)
                        self.assertEqual(part.nodes[-1].position, part.grip)
                    if not rail.closed:
                        self.assertTrue(0 <= part.grip_s <= rail.length)
            for _ in range(500):
                support.step(host_at(world, rail, s))
            self.assertTrue(support.settled)

    def test_switch_and_reset_replace_support_without_mutating_bell(self):
        scene = scene_at(hide_cords=False)
        self.assertIsNone(scene.appearance.cords)
        original = scene.prince_tentacles
        scene.reset()
        self.assertIsNot(scene.prince_tentacles, original)
        scene.config = replace(scene.config, body_appearance='bell')
        scene.sync_character()
        scene.appearance.sync_shape(scene)
        scene.appearance.sync_cords(scene)
        self.assertIsNone(scene.prince_tentacles)
        self.assertIsNotNone(scene.appearance.cords)
        scene.config = replace(scene.config, body_appearance='prince')
        scene.sync_character()
        scene.appearance.sync_shape(scene)
        scene.appearance.sync_cords(scene)
        self.assertIsNotNone(scene.prince_tentacles)
        self.assertIsNone(scene.appearance.cords)
        scene.set_target(scene.body.chunks[0].position+Vec2(0, 100))
        for _ in range(450):
            scene.step()
        scene.config = replace(scene.config, body_appearance='bell')
        scene.sync_character()
        self.assertEqual(scene.arm.joints[0].position, scene.base)
        self.assertEqual(scene.arm.joints[-1].position,
                         scene.body.chunks[0].position-scene.body.direction*scene.arm.lengths[3])

    def test_drag_recovery_after_switching_from_a_moving_mechanical_arm(self):
        scene = scene_at()
        scene.config = replace(scene.config, body_appearance='bell')
        scene.sync_character()
        scene.set_target(scene.body.chunks[0].position+Vec2(0, -90))
        for _ in range(60):
            scene.step()
        self.assertFalse(scene.arm.settled)
        scene.config = replace(scene.config, body_appearance='prince')
        scene.step()
        scene.drag.set_enabled(True)
        self.assertTrue(scene.drag.press(scene.head.position, lambda _: True))
        scene.drag.move(scene.head.position+Vec2(-40, 25))
        for _ in range(120):
            scene.step()
        scene.drag.release()
        for _ in range(1000):
            scene.step()
            if not scene.drag.recovering:
                break
        self.assertFalse(scene.drag.recovering)
        self.assertTrue(scene.prince_tentacles.settled)
        # 旧机械臂已经不再推进，也不能阻止触手状态完成恢复
        self.assertFalse(scene.arm.settled)

    def test_fixed_base_mode_replants_from_body_travel(self):
        scene = scene_at(sliding_base=False)
        initial = tuple(p.grip for p in scene.prince_tentacles.parts)
        scene.set_target(scene.body.chunks[0].position+Vec2(0, -80))
        for _ in range(450):
            scene.step()
        self.assertNotEqual(initial, tuple(p.grip for p in scene.prince_tentacles.parts))

    def test_extreme_drag_limits_actual_length_and_keeps_one_support_on_every_edge(self):
        for side in ('right', 'top', 'left', 'bottom'):
            with self.subTest(side=side):
                scene = (scene_at(side, world_width=640, world_height=480, edge_fraction=.35)
                         if side in ('right', 'bottom') else scene_at(side))
                for _ in range(220):
                    scene.step()
                support = scene.prince_tentacles
                scene.drag.set_enabled(True)
                # 右边抓取下摆，其余边抓取头部，覆盖弯曲的长力臂
                start = (scene.prince_posture.points[0].position if side == 'right'
                         else scene.head.position)
                self.assertTrue(scene.drag.press(start, lambda _: True))
                inward = scene.base_normal()
                maximum_loose = 0
                for tick in range(240):
                    scene.drag.move(start+inward*min(1800., tick*15.))
                    scene.step()
                    loose = sum(not p.attached for p in support.parts)
                    maximum_loose = max(maximum_loose, loose)
                    self.assertLessEqual(loose, 2)
                    self.assertGreaterEqual(sum(p.attached for p in support.parts), 1)
                    for part in support.parts:
                        self.assertLessEqual(part.path(1).length, part.reference_length*1.2+1e-6)
                        if part.attached:
                            self.assertEqual(part.nodes[-1].position, part.grip)
                self.assertEqual(maximum_loose, 2)
                self.assertGreater((scene.drag.controller.pointer-start).length(), 1000.)
                self.assertGreater((scene.head.position-scene.drag.controller.pointer).length(), 1000.)
                # 直接从拉伸极限松手，不先把鼠标送回原位
                scene.drag.release()
                for _ in range(1200):
                    scene.step()
                    if not scene.drag.controlling:
                        break
                    self.assertGreaterEqual(sum(p.attached for p in support.parts), 1)
                    self.assertLessEqual(sum(not p.attached for p in support.parts), 2)
                    for part in support.parts:
                        self.assertLessEqual(part.path(1).length, part.reference_length*1.2+1e-6)
                self.assertFalse(scene.drag.controlling)
                self.assertTrue(all(p.attached for p in support.parts))
                self.assertTrue(support.settled)

    def test_drag_started_mid_replant_can_release_two_but_preserves_remaining_grip(self):
        scene = scene_at()
        support = scene.prince_tentacles
        scene.set_target(scene.body.chunks[0].position+Vec2(0, -100))
        for _ in range(200):
            scene.step()
            if any(p.transferring for p in support.parts):
                break
        self.assertEqual(sum(not p.attached for p in support.parts), 1)
        scene.drag.set_enabled(True)
        scene.drag.press(scene.head.position, lambda _: True)
        scene.drag.move(scene.head.position+Vec2(-300, 0))
        saw_two = False
        for _ in range(180):
            scene.step()
            loose = sum(not p.attached for p in support.parts)
            saw_two |= loose == 2
            self.assertLessEqual(loose, 2)
            self.assertTrue(any(p.attached for p in support.parts))
            for p in support.parts:
                self.assertLessEqual(p.path(1).length, p.reference_length*1.2+1e-6)
        self.assertTrue(saw_two)

    def test_render_bounds_glow_interpolation_and_mouse_through(self):
        scene = scene_at(glow_enabled=True)
        renderer = OracleRenderer(colors=scene.config.active_colors)
        scene.set_target(scene.body.chunks[0].position+Vec2(0, 90))
        for _ in range(140):
            scene.step()
        bounds = body_bounds(scene)
        for alpha in (0., .5, 1.):
            for definition, path in scene.prince_tentacles.paths(alpha):
                for p in path.points:
                    self.assertTrue(bounds.contains(QPointF(p.x, p.y)))
                for bump in (*definition.bumps, *definition.cores):
                    p, _ = path.attachment(bump)
                    self.assertTrue(bounds.contains(QPointF(p.x, p.y)))
        self.assertTrue(visual_bounds(scene).contains(bounds))
        before = scene.prince_tentacles.paths()
        for scale in (1., 1.5, 2., 3., 4.):
            image = QImage(round(scene.world.width*scale), round(scene.world.height*scale),
                           QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            try:
                painter.scale(scale, scale)
                renderer.draw(painter, scene, .5, raster_scale=scale)
            finally:
                painter.end()
            self.assertFalse(renderer._raster_image.isNull())
            self.assertIsNotNone(renderer._body_glow)
        self.assertEqual(scene.prince_tentacles.paths(), before)
        hit = PuppetHitMap().get(renderer, scene)
        for part in scene.prince_tentacles.parts:
            self.assertFalse(hit.contains(part.grip))


if __name__ == '__main__':
    unittest.main()
