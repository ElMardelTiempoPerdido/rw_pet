"""主动手势的肩外扇形、任意身体朝向、惯性限位和松手过渡。"""
from math import atan2, cos, pi, sin
import unittest

from rw_creature_pet.oracle.appearance import HangingHand, perpendicular, rotate
from rw_creature_pet.oracle.config import DragReactionConfig, OracleConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


def dot(a, b):
    return a.x*b.x+a.y*b.y


class HandSectorTests(unittest.TestCase):
    def scene(self):
        scene = OracleScene(OracleConfig(halo_enabled=False, pearl_fixed_count=0,
            drag_reactions=DragReactionConfig(gesture_probability=0., voice_probability=0.)))
        scene.drag.set_enabled(True)
        scene.drag.press(scene.head.position, lambda _: True)
        return scene

    def test_targets_and_physical_hands_stay_in_sectors_while_body_turns_and_moves(self):
        for angle in (0., pi/2, pi, -pi/2):
            for gesture in ('flutter', 'alternating', 'protest'):
                with self.subTest(angle=angle, gesture=gesture):
                    scene = self.scene()
                    app, r = scene.appearance, scene.drag_reactions
                    app.direction = rotate(Vec2(0, -1), angle)
                    for hand, force in zip(app.hands, app.hand_forces()):
                        hand.pin(app.upper+force*(15/force.length()))
                    r.start_gesture(gesture, scene)
                    r.duration = 3.
                    for tick in range(110):
                        r.step(scene)
                        app.direction = rotate(Vec2(0, -1), angle+.45*sin(tick*.08))
                        host = Vec2(1.5*sin(tick*.15), 1.5*cos(tick*.13))
                        app.upper += host
                        app.last_body_velocity = host
                        pointer = app.upper+Vec2(40*sin(tick*.09), 40*cos(tick*.09))
                        targets = r.hand_targets(app, pointer)
                        forces = r.hand_forces(app, pointer)
                        for i, (hand, natural, extra, target) in enumerate(zip(app.hands, app.hand_forces(), forces, targets)):
                            shoulder = hand.shoulder(app.upper, app.direction, i)
                            outward = perpendicular(app.direction)*(-1 if i == 0 else 1)
                            if target is not None:
                                delta = target-shoulder
                                target_angle = atan2(dot(delta, app.direction), dot(delta, outward))
                                self.assertGreaterEqual(target_angle, hand.SWING_MIN-1e-8)
                                self.assertLessEqual(target_angle, hand.SWING_MAX+1e-8)
                                self.assertAlmostEqual(delta.length(), 15.5)
                            weight = r.hand_weight(i)
                            hand.step(app.upper, host, natural+extra, shoulder=shoulder, weight=weight)
                            hand.constrain_swing(app.upper, app.direction, i, host, weight)
                            anchor, maximum = hand.reach_limit(app.upper, shoulder)
                            self.assertLessEqual((hand.position-anchor).length(), maximum+1e-8)
                            if weight > 0:
                                delta = hand.position-shoulder
                                actual = atan2(dot(delta, app.direction), dot(delta, outward))
                                self.assertGreaterEqual(actual, -pi+(hand.SWING_MIN+pi)*weight-1e-8)
                                self.assertLessEqual(actual, pi+(hand.SWING_MAX-pi)*weight+1e-8)
                                if weight == 1.:
                                    self.assertGreaterEqual(dot(delta, outward), -1e-8)

    def test_constraint_removes_only_velocity_into_boundary_and_preserves_reach(self):
        origin, up, outward, host = Vec2(100, 80), Vec2(0, -1), Vec2(1, 0), Vec2(2, -1)
        for angle in (-80*pi/180, 80*pi/180):
            for radius in (8., 25.):
                shoulder = HangingHand.shoulder(origin, up, 1)
                hand = HangingHand.at(shoulder+(outward*cos(angle)+up*sin(angle))*radius)
                hand.reach_weight = 1.
                limit = hand.SWING_MIN if angle < 0 else hand.SWING_MAX
                normal = (outward*(-sin(limit))+up*cos(limit))*(-1 if angle < 0 else 1)
                hand.drive_velocity = host+normal*4
                hand.constrain_swing(origin, up, 1, host, 1.)
                delta = hand.position-shoulder
                self.assertAlmostEqual(atan2(dot(delta, up), dot(delta, outward)), limit)
                self.assertLessEqual(delta.length(), 16.000001)
                self.assertAlmostEqual(delta.length(), min(radius, 16.))
                self.assertLessEqual(dot(hand.drive_velocity-host, normal), 1e-8)
                self.assertEqual(hand.velocity, hand.position-hand.previous_position)

    def test_raised_hands_keep_length_at_different_angles_and_in_fast_flutter(self):
        for tilt in (0., pi/2, pi, -pi/2):
            scene = self.scene()
            app, r = scene.appearance, scene.drag_reactions
            app.direction = rotate(Vec2(0, -1), tilt)
            r.start_gesture('flutter', scene)
            r.weight = 1.
            r.hand_lifts = [1., 1.]  # 最大幅度仍要经过完整的臂长回归。
            shoulders = [hand.shoulder(app.upper, app.direction, i) for i, hand in enumerate(app.hands)]
            for i, hand in enumerate(app.hands):
                outward = perpendicular(app.direction)*(-1 if i == 0 else 1)
                hand.pin(shoulders[i]+outward*15.5)
                hand.reach_weight = 1.
            for tick in range(500):
                # 先分别保持扇形的下端/中点/上端，再以较快且不同的节奏连续摆动。
                r.flutter_phases = ([(-pi/2, 0., pi/2)[tick//80]]*2 if tick < 240
                                    else [tick*2*pi*1.9/40, tick*2*pi*1.3/40])
                forces = r.hand_forces(app, app.upper)
                for i, (hand, natural, force) in enumerate(zip(app.hands, app.hand_forces(), forces)):
                    hand.step(app.upper, Vec2(), natural+force, shoulder=shoulders[i], weight=1.)
                    hand.constrain_swing(app.upper, app.direction, i, Vec2(), 1.)
                    length = (hand.position-shoulders[i]).length()
                    self.assertGreater(length, 14.5, '改变摆角不能把袖子明显收短')
                    self.assertLessEqual(length, 16.+1e-8)
                    if tick in (79, 159, 239):
                        self.assertAlmostEqual(length, 15.5, delta=.1)

    def test_each_gesture_can_stay_low_and_only_some_reach_high(self):
        for gesture in ('flutter', 'alternating', 'protest'):
            scene = self.scene()
            app, r = scene.appearance, scene.drag_reactions
            peaks = []
            for _ in range(128):
                r.start_gesture(gesture, scene)
                r.weight = 1.
                r.phase = pi/2
                r.flutter_phases = [pi/2, pi/2]
                r.flutter_strengths = [1., 1.]
                limits = r.hand_lifts.copy()
                # 指针在正上方：单手抗议也必须服从本次抽到的低幅度。
                pointer = app.upper+app.direction*1000
                state = r.random.getstate()
                for i, hand in enumerate(app.hands):
                    if gesture == 'alternating':
                        r.phase = pi/2+i*pi  # 分别取两手在相差半周期时的最高点。
                    target = r.hand_targets(app, pointer)[i]
                    if target is None:
                        continue
                    delta = target-hand.shoulder(app.upper, app.direction, i)
                    outward = perpendicular(app.direction)*(-1 if i == 0 else 1)
                    angle = atan2(dot(delta, app.direction), dot(delta, outward))*180/pi
                    peaks.append(angle)
                    self.assertGreaterEqual(angle, -18.-1e-8)
                    self.assertLessEqual(angle, 43.+1e-8)
                    self.assertAlmostEqual(delta.length(), 15.5)
                self.assertEqual(state, r.random.getstate(), '读取目标不逐帧重新抽幅度')
                for _ in range(4):
                    r._choose_flutter_rhythm()
                    r._step_flutter()
                    self.assertEqual(limits, r.hand_lifts, '换节奏仍保留本组动作的抬手上限')
            self.assertGreater(sum(angle < 20 for angle in peaks), len(peaks)*.6)
            self.assertGreater(sum(angle < 0 for angle in peaks), len(peaks)*.15)
            self.assertGreater(sum(angle > 30 for angle in peaks), len(peaks)*.05)

    def test_alternating_keeps_opposite_strokes_with_a_fixed_rhythm(self):
        scene = self.scene()
        app, r = scene.appearance, scene.drag_reactions
        # 上一次随机扑腾的同向意图不能泄漏到固定交替动作。
        r.start_gesture('flutter', scene)
        r.flutter_shared = r.flutter_shared_target = 1.
        r.start_gesture('alternating', scene)
        r.duration = 4.
        r.hand_lifts = [.6, .8]
        frequency, state = r.frequency, r.random.getstate()
        previous = None
        opposed = samples = 0
        for tick in range(140):
            r.step(scene)
            self.assertEqual(r.frequency, frequency)
            self.assertEqual(r.random.getstate(), state, '固定交替过程中不重新抽节奏')
            targets = r.hand_targets(app, app.upper)
            heights = [dot(target-app.upper, app.direction) for target in targets]
            if previous is not None:
                changes = [new-old for new, old in zip(heights, previous)]
                self.assertLessEqual(changes[0]*changes[1], 1e-8)
            previous = heights
            for i, (hand, natural, force) in enumerate(zip(app.hands, app.hand_forces(), r.hand_forces(app, app.upper))):
                shoulder = hand.shoulder(app.upper, app.direction, i)
                hand.step(app.upper, Vec2(), natural+force, shoulder=shoulder, weight=r.hand_weight(i))
                hand.constrain_swing(app.upper, app.direction, i, Vec2(), r.hand_weight(i))
            if tick > 20:
                a, b = [dot(hand.velocity, app.direction) for hand in app.hands]
                opposed += a*b < 0
                samples += 1
        self.assertGreater(opposed, samples*.8, '过渡后实际手部也应主要反向划动')

    def test_cancel_and_regrab_do_not_snap_extended_hands_back_to_body_limit(self):
        for regrab in (False, True):
            scene = self.scene()
            app, r = scene.appearance, scene.drag_reactions
            r.start_gesture('flutter', scene)
            r.weight = 1.
            for i, hand in enumerate(app.hands):
                shoulder = hand.shoulder(app.upper, app.direction, i)
                outward = perpendicular(app.direction)*(-1 if i == 0 else 1)
                hand.pin(shoulder+outward*15.5)
                hand.reach_weight = 1.
            before = [hand.position for hand in app.hands]
            scene.drag.release(cancel=True)
            if regrab:
                scene.drag.press(scene.head.position, lambda _: True)
            scene.step()
            for hand, old in zip(app.hands, before):
                self.assertLess((hand.position-old).length(), 1.)
                self.assertGreater((hand.position-app.upper).length(), 18.)
            scene.drag.release(cancel=True)
            for _ in range(1300):
                scene.step()
            self.assertTrue(app.sleeping)
            for hand in app.hands:
                self.assertEqual(hand.reach_weight, 0.)
                self.assertAlmostEqual((hand.position-app.upper).length(), 15., places=5)

    def test_no_constraint_for_rest_and_release_fades_out_before_hands_settle(self):
        scene = self.scene()
        app, r = scene.appearance, scene.drag_reactions
        r.start_gesture('flutter', scene)
        for _ in range(35):
            scene.step()
        before = [(h.position, h.drive_velocity) for h in app.hands]
        scene.drag.release()
        self.assertEqual(before, [(h.position, h.drive_velocity) for h in app.hands])
        for _ in range(1300):
            scene.step()
        self.assertFalse(r.gesturing)
        self.assertTrue(app.sleeping)
        for i, hand in enumerate(app.hands):
            state = (hand.position, hand.previous_position, hand.drive_velocity, hand.velocity)
            hand.constrain_swing(app.upper, app.direction, i, Vec2(), r.hand_weight(i))
            self.assertEqual(state, (hand.position, hand.previous_position, hand.drive_velocity, hand.velocity))


if __name__ == '__main__':
    unittest.main()
