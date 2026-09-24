import math
import unittest

from rw_creature_pet.geometry import Vec2
from rw_creature_pet.gait import FootPhase
from tests.test_wall_observation import placed, rotate


def bend(scene):
    front, middle, rear = [c.position for c in scene.body.chunks]
    a, b = front-middle, middle-rear
    return (math.atan2(a.y,a.x)-math.atan2(b.y,b.x)+math.pi) % (2*math.pi)-math.pi


class BodyFollowingTests(unittest.TestCase):
    def test_stop_retains_curve_observe_then_resume_all_directions(self):
        for i in range(8):
            angle = i*math.pi/4
            s = placed(angle)
            identities = [id(p) for p in [*s.body.chunks,*s.appearance.tail]]
            s.background.set_direction(rotate(Vec2(1,0),angle))
            for _ in range(90): s.step()
            s.background.set_direction(rotate(Vec2(0,1),angle))
            for _ in range(23): s.step()
            original_bend = bend(s)
            self.assertGreater(abs(original_bend), .3)
            s.background.set_direction(Vec2())
            for _ in range(350): s.step()
            self.assertAlmostEqual(bend(s), original_bend, delta=.03)
            positions = [c.position for c in s.body.chunks]
            feet = [f.position for f in s.feet]
            for _ in range(800): s.step()
            self.assertLess(max((c.position-p).length() for c,p in zip(s.body.chunks,positions)), 1e-7)
            self.assertEqual(feet,[f.position for f in s.feet])
            s.appearance.observe(s.body.chunks[0].position+rotate(Vec2(80,-100),angle),200)
            for _ in range(600): s.step()
            self.assertAlmostEqual(bend(s), original_bend, delta=.03)
            s.background.set_direction(rotate(Vec2(-1,0),angle))
            for _ in range(180):
                old = [p.position for p in [*s.body.chunks,s.appearance.head,*s.appearance.tail]]
                old_feet = [(f.phase,f.position) for f in s.feet]
                s.step()
                self.assertTrue(s.background.attached)
                self.assertLess(max(s.body.connection_error(c) for c in s.body.connections), .002)
                self.assertLess(max((p.position-q).length() for p,q in zip(s.body.chunks,old[:3])), 2)
                self.assertLess(max((p.position-q).length() for p,q in zip([*s.body.chunks,s.appearance.head,*s.appearance.tail],old)), 12)
                for f,(phase,point) in zip(s.feet,old_feet):
                    if f.phase == phase == FootPhase.STANCE:
                        self.assertEqual(f.position,point)
            self.assertEqual(identities,[id(p) for p in [*s.body.chunks,*s.appearance.tail]])
            self.assertGreater((s.body.chunks[1].position-positions[1]).length(), 25)

    def test_nearby_goal_stops_with_curve(self):
        s = placed()
        s.background.set_direction(Vec2(1,0))
        for _ in range(90): s.step()
        goal = s.body.chunks[1].position+Vec2(5,25)
        s.background.set_goal(goal,s.body,s.world)
        for _ in range(1000):
            s.step()
            if s.background.arrived: break
        self.assertTrue(s.background.arrived)
        self.assertGreater(abs(bend(s)), .15)
        positions = [c.position for c in s.body.chunks]
        for _ in range(500): s.step()
        self.assertLess((s.body.chunks[1].position-goal).length(), .6)
        self.assertLess(max((c.position-p).length() for c,p in zip(s.body.chunks,positions)), .2)
