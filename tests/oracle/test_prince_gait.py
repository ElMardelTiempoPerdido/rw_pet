"""Prince 换点时接替支撑、路线提前量与有效步幅"""
import unittest

from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.test_prince_autonomous_support import scene_at


class PrinceGaitTests(unittest.TestCase):
    def test_attached_alternative_carries_body_while_longest_is_in_flight(self):
        for side in ('top', 'right', 'bottom', 'left'):
            with self.subTest(side=side):
                scene = scene_at(side)
                support = scene.prince_tentacles
                primary = max(support.parts, key=lambda p: p.reference_length)
                primary.release(primary.grip_s+24., support.rail)
                normal = scene.base_normal()
                shift = Vec2(-normal.y, normal.x)*.5
                candidate = support.body_position+shift
                self.assertTrue(any(support.gait.carries(p, shift) for p in support.parts))
                self.assertLess((support.project_motion(scene, candidate)-candidate).length(), 1e-8)
                far = support.project_motion(scene, candidate+shift*10000.)
                self.assertTrue(any(p.attached and (
                    support.part_root(p.definition)+far-support.body_position-p.grip).length()
                    <= support.gait.reach(p)+1e-7 for p in support.parts))
                for p in support.parts:
                    p.attached = False
                self.assertEqual(support.project_motion(scene, candidate), support.body_position)

    def test_route_preview_survives_a_stop_and_does_not_pass_destination(self):
        scene = scene_at('top')
        support = scene.prince_tentacles
        origin = scene.body.chunks[0].position
        scene.set_target(origin+Vec2(180., 0.))
        expected = support.gait.preview(scene)
        self.assertGreater(expected.x, 30.)
        scene.navigator.speed = 0.
        scene.navigator.waiting_for_base = True
        support.travel = 0.
        self.assertEqual(support.gait.preview(scene), expected)
        scene.set_target(origin+Vec2(8., 0.))
        self.assertLessEqual(support.gait.preview(scene).length(), 8.+1e-8)

    def test_forward_grip_adds_runway_without_chasing_back_to_current_preference(self):
        scene = scene_at('top')
        support = scene.prince_tentacles
        primary = max(support.parts, key=lambda p: p.reference_length)
        scene.set_target(support.body_position+Vec2(180., 0.))
        shift = support.gait.preview(scene)
        target = support.gait.target(primary, shift)
        self.assertIsNotNone(target)
        self.assertTrue(support.gait.worthwhile(primary, target, shift))
        grip = support.rail.sample(target)[0]
        self.assertLessEqual((grip-support.part_root(primary.definition)).length(),
                             primary.reference_length*support.AUTO_REGRIP+1e-7)
        self.assertGreater(support.gait.runway(primary, grip, shift),
                           support.gait.runway(primary, primary.grip, shift)+12.)
        primary.grip_s, primary.grip = target, grip
        offset = support.rail.delta(target, support.ideal_grip(
            primary.definition, support.part_root(primary.definition)))
        self.assertFalse(support.gait.needs_step(primary, shift, offset))

    def test_real_walk_keeps_moving_during_handoffs_and_finishes_on_all_edges(self):
        for side in ('top', 'right', 'bottom', 'left'):
            with self.subTest(side=side):
                scene = scene_at(side)
                for _ in range(200):
                    scene.step()
                support = scene.prince_tentacles
                primary = max(support.parts, key=lambda p: p.reference_length)
                normal = scene.base_normal()
                scene.set_target(scene.body.chunks[0].position+Vec2(-normal.y, normal.x)*220.)
                carried = 0.
                for _ in range(1000):
                    before = scene.body.chunks[0].position
                    transferring = primary.transferring
                    scene.step()
                    delta = (scene.body.chunks[0].position-before).length()
                    self.assertLess(delta, 4.)
                    if transferring and primary.transferring:
                        carried += delta
                    self.assertTrue(any(p.attached for p in support.parts))
                    self.assertLessEqual(sum(p.transferring for p in support.parts), 1)
                    if primary.attached:
                        self.assertLessEqual((primary.grip-support.part_root(primary.definition)).length(),
                                             primary.reference_length*.90+.1)
                    if scene.arrived:
                        break
                self.assertGreater(carried, 10.)
                self.assertTrue(scene.arrived)


if __name__ == '__main__':
    unittest.main()
