import unittest
from rw_creature_pet.desktop import DesktopMotion, EdgeWorld
from rw_creature_pet.geometry import Vec2


class DesktopTests(unittest.TestCase):
    def test_scaling_and_edge_grip_limits(self):
        for size in ((1920, 1040), (1280, 680), (800, 600)):
            for scale in (.5, 1.5, 4):
                m = DesktopMotion(*size, scale=scale)
                w = m.scene.world
                self.assertAlmostEqual(w.width*m.scale, size[0])
                self.assertAlmostEqual(w.floor_y*m.scale, size[1])
                center = Vec2(w.width/2, w.floor_y/2)
                self.assertIsNone(w.background_grip(center, center, 25))
                edge = Vec2(15, w.floor_y/2)
                self.assertEqual(w.background_grip(edge, edge, 25), edge)
        for scale in (0, float('nan'), 5):
            with self.assertRaises(ValueError):
                DesktopMotion(1920, 1040, scale)

    def test_floor_reverses_and_stays_grounded(self):
        m = DesktopMotion(1280, 680)
        turns = 0
        previous = m.scene.gait.speed
        grounded = 0
        for _ in range(3500):
            m.step()
            if m.scene.gait.speed != previous:
                turns += 1
                previous = m.scene.gait.speed
            grounded += sum(f.phase.value == '支撑' and abs(f.position.y-m.scene.world.floor_y) < 1e-6 for f in m.scene.feet) >= 2
            self.assertTrue(all(c.position.y+c.radius <= m.scene.world.floor_y+1e-5 for c in m.scene.body.chunks))
        self.assertGreaterEqual(turns, 2)
        self.assertGreater(grounded, 2000)

    def test_wall_completes_ring_with_fixed_stance_feet(self):
        m = DesktopMotion(1280, 680, mode='wall')
        s = m.scene
        visited = set()
        for _ in range(6000):
            old = [(f.phase, f.position) for f in s.feet]
            m.step()
            visited.add(m.route_index)
            self.assertTrue(s.background.attached)
            self.assertTrue(all(s.world.in_edge(c.position) for c in s.body.chunks))
            self.assertLess(max(s.body.connection_error(c) for c in s.body.connections), .002)
            for f, (phase, p) in zip(s.feet, old):
                if f.phase == phase and f.phase.value == '支撑':
                    self.assertEqual(f.position, p)
        self.assertEqual(visited, {0, 1, 2, 3})
