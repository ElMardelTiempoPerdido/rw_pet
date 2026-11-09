"""Prince 普通/失重力度、连续过渡和拖动接管回归"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import degrees, sin
import unittest

from rw_creature_pet.oracle.motion.prince import PrincePosture, turn
from rw_creature_pet.oracle.motion.prince_spine import TAIL, BEND_LIMITS, bend_angle
from rw_creature_pet.oracle.motion.prince_robe import COLUMNS, PIN_LENGTH, RobeLayer
from rw_creature_pet.oracle.prince_assets import robe_layout
from rw_creature_pet.oracle.scene import OracleHead
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.test_prince_autonomous_support import scene_at


class PrinceMotionForceTests(unittest.TestCase):
    def test_same_movement_has_more_tail_lag_and_longer_settling_in_drift(self):
        results = []
        for weight in (0., 1.):
            posture = PrincePosture(Vec2(), Vec2(0, -1), Vec2(), 19.)
            head = OracleHead.at(posture.target)
            errors = []
            for tick in range(400):
                direction = turn(Vec2(0, -1), .65*sin(tick/40))
                origin = Vec2(12*sin(tick/38), 0.)
                posture.step(head, origin, direction, Vec2(), weightlessness=weight)
                errors.append((posture.points[TAIL].position-posture.spine.targets[TAIL]).length())
                points = [p.position for p in posture.points]
                goals = posture.spine.targets
                for a, b, g, h in zip(points, points[1:], goals, goals[1:]):
                    self.assertLess(abs((b-a).length()-(h-g).length()), .08)
                for a, b, c, limit in zip(points, points[1:], points[2:], BEND_LIMITS):
                    self.assertLess(abs(degrees(bend_angle(b-a, c-b))), limit+2.)
            for tick in range(400):
                posture.step(head, origin, direction, Vec2(), weightlessness=weight)
                if posture.settled:
                    break
            self.assertTrue(posture.settled)
            self.assertEqual(head.position, posture.target)
            results.append((sum(errors)/len(errors), tick+1))
        normal, drift = results
        self.assertGreater(drift[0], normal[0]*1.4)
        self.assertGreater(drift[1], normal[1]*1.3)
        self.assertLess(normal[1], 100)
        self.assertLess(drift[1], 240)

    def test_lower_layers_have_more_inertia_in_drift_keep_seam_and_wake_on_exit(self):
        art = robe_layout()
        coords = tuple(Vec2(art.width*x/(COLUMNS-1), y)
                       for y in (0., PIN_LENGTH, art.height/2, art.height)
                       for x in range(COLUMNS))
        for back in (False, True):
            peaks = []
            for weight in (0., 1.):
                layer = RobeLayer(coords, coords, back=back)
                peak = 0.
                for tick in range(300):
                    shift = Vec2(8*sin(tick/12), 0.)
                    goals = tuple(p+shift for p in coords)
                    layer.step(goals, Vec2(), weightlessness=weight)
                    for i, (uv, p) in enumerate(zip(coords, layer.points)):
                        distance = (p.position-goals[i]).length()
                        if uv.y <= PIN_LENGTH:
                            self.assertEqual(distance, 0.)
                        self.assertLessEqual(distance, layer.limit*layer.weights[i]+1e-8)
                        peak = max(peak, distance)
                peaks.append(peak)
                # 重力不变时也必须响应力度变化，静止失重可休眠，退出后可再次收敛
                for _ in range(500):
                    layer.step(goals, Vec2(), weightlessness=weight)
                self.assertTrue(layer.settled)
                layer.step(goals, Vec2(), weightlessness=1.-weight)
                self.assertFalse(layer.settled)
                for _ in range(500):
                    layer.step(goals, Vec2(), weightlessness=1.-weight)
                self.assertTrue(layer.settled)
            self.assertGreater(peaks[1], peaks[0]*1.3)

    def test_scene_blends_forces_then_drag_takes_over_without_rebuilding_body(self):
        scene = scene_at()
        scene.behavior.start_drift(scene)
        scene.behavior.drift_next_move = 0
        spine = scene.prince_posture.spine
        robe = scene.appearance.prince_robe
        last_weight = spine.weightlessness
        for _ in range(150):
            scene.step()
            self.assertLessEqual(abs(spine.weightlessness-last_weight), 1/120+1e-8)
            last_weight = spine.weightlessness
            for layer in robe.layers:
                self.assertEqual(layer.weightlessness, spine.weightlessness)
            goals, _ = robe.goals(scene.appearance)
            for i, uv in enumerate(robe.coords):
                if uv.y <= PIN_LENGTH:
                    self.assertEqual(robe.front.points[i].position, goals[i])
                    self.assertEqual(robe.back.points[i].position, goals[i])
        self.assertEqual(spine.weightlessness, 1.)
        positions = tuple(p.position for p in spine.points)
        scene.drag.set_enabled(True)
        self.assertTrue(scene.drag.press(scene.head.position, lambda _: True))
        self.assertEqual(positions, tuple(p.position for p in spine.points))
        scene.step()
        self.assertIs(scene.prince_posture.spine, spine)
        self.assertEqual(spine.weightlessness, 0.)
        self.assertTrue(all(layer.weightlessness == 0. for layer in robe.layers))
        self.assertGreater(scene.pose.weightlessness, .9)
        for _ in range(180):
            scene.step()
        scene.drag.release()
        for _ in range(1000):
            scene.step()
            if not scene.drag.controlling and scene.appearance.sleeping:
                break
        self.assertFalse(scene.drag.controlling)
        self.assertTrue(scene.appearance.sleeping)
        self.assertEqual(spine.weightlessness, 0.)

    def test_grab_force_is_independent_of_unfinished_drift_fade(self):
        postures = [PrincePosture(Vec2(), Vec2(0, -1), Vec2(), 19.) for _ in range(2)]
        heads = [OracleHead.at(p.target) for p in postures]
        grab = (TAIL, postures[0].points[TAIL].position+Vec2(7., -3.))
        for _ in range(140):
            for weight, posture, head in zip((0., 1.), postures, heads):
                posture.step(head, Vec2(), Vec2(0, -1), Vec2(), grab=grab,
                             gravity=.3, weightlessness=weight)
            self.assertEqual(tuple(p.position for p in postures[0].points),
                             tuple(p.position for p in postures[1].points))

    def test_normal_exit_restores_forces_gradually_and_returns_to_sleep(self):
        scene = scene_at()
        scene.behavior.start_drift(scene)
        scene.behavior.drift_next_move = 0
        for _ in range(180):
            scene.step()
        spine = scene.prince_posture.spine
        before = tuple(p.position for p in spine.points)
        scene.stop()
        self.assertEqual(before, tuple(p.position for p in spine.points))
        last_weight = 1.
        for _ in range(1600):
            scene.step()
            self.assertLessEqual(abs(spine.weightlessness-last_weight), 1/120+1e-8)
            last_weight = spine.weightlessness
            self.assertTrue(all(layer.weightlessness == last_weight
                                for layer in scene.appearance.prince_robe.layers))
            if scene.appearance.sleeping and scene.pose.settled:
                break
        self.assertTrue(scene.appearance.sleeping)
        self.assertTrue(spine.settled)
        self.assertEqual(last_weight, 0.)


if __name__ == '__main__':
    unittest.main()
