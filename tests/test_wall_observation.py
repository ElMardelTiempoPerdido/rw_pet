import math
import unittest

from rw_creature_pet.background import BackgroundGrip
from rw_creature_pet.config import DebugConfig
from rw_creature_pet.desktop import EdgeWorld, DesktopMotion
from rw_creature_pet.gait import FootPhase
from rw_creature_pet.geometry import Vec2
from rw_creature_pet.scene import DebugScene


def rotate(p, angle):
    return Vec2(p.x*math.cos(angle)-p.y*math.sin(angle),
                p.x*math.sin(angle)+p.y*math.cos(angle))


def placed(angle=0, center=Vec2(350, 300), edge=False):
    s = DebugScene(DebugConfig(world_width=700, world_height=650, floor_y=600))
    s.place_on_background(300)
    origin = s.body.chunks[1].position
    for point in [*s.body.chunks, s.appearance.head, *s.appearance.tail]:
        point.position = center+rotate(point.position-origin, angle)
        point.previous_position = point.position
    if edge:
        s.world = EdgeWorld(700, 650, 600)
    s.background = BackgroundGrip(s.body)
    s.background.set_enabled(True, s.body, s.world)
    return s


class WallObservationTests(unittest.TestCase):
    def test_rendered_pixels_stay_outside_center(self):
        from PySide6.QtGui import QImage, QPainter
        from rw_creature_pet.atlas import Atlas, extract_atlas
        from rw_creature_pet.config import DEFAULT_GAME_DIR
        from rw_creature_pet.render_lizard import LizardRenderer
        if not DEFAULT_GAME_DIR.exists():
            self.skipTest('需要本机游戏图集')
        s = placed(-math.pi/2, Vec2(130,300), edge=True)
        s.appearance.observe(Vec2(350,300),2000)
        for _ in range(900): s.step()
        renderer = LizardRenderer(Atlas(extract_atlas(DEFAULT_GAME_DIR)))
        for alpha in (0, .5, 1):
            image = QImage(700,600,QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            try:
                renderer.draw(painter,s,alpha)
            finally:
                painter.end()
            pixels = bytes(image.bits())
            self.assertTrue(any(pixels[3::4]))
            self.assertFalse(any(any(pixels[(y*700+141)*4+3:(y*700+560)*4:4])
                                 for y in range(121,480)))

    def test_eight_headings_equivalent_bend_grips_and_recovery(self):
        baseline = None
        for i in range(8):
            angle = i*math.pi/4
            s = placed(angle)
            center = s.body.chunks[1].position
            feet = [f.position for f in s.feet]
            identities = [id(c) for c in s.body.chunks]
            s.appearance.observe(center+rotate(Vec2(80, 100), angle), 2000)
            for _ in range(900):
                old = [p.position for p in [*s.body.chunks, s.appearance.head]]
                s.step()
                self.assertEqual(feet, [f.position for f in s.feet])
                self.assertTrue(s.background.attached)
                self.assertLess(max((p.position-q).length() for p,q in zip([*s.body.chunks,s.appearance.head],old)), 2)
                self.assertLess(max(s.body.connection_error(c) for c in s.body.connections), .002)
            points = [rotate(p.position-center, -angle) for p in [*s.body.chunks,s.appearance.head,*s.appearance.tail]]
            if baseline is None:
                baseline = points
            self.assertLess(max((p-q).length() for p,q in zip(points,baseline)), 1e-5)
            self.assertGreater(s.background.look_bend, .1)
            self.assertEqual(identities, [id(c) for c in s.body.chunks])
            old = [p.position for p in [*s.body.chunks,s.appearance.head,*s.appearance.tail]]
            for _ in range(200): s.step()
            self.assertLess(max((p.position-q).length() for p,q in zip([*s.body.chunks,s.appearance.head,*s.appearance.tail],old)), 1e-6)
            s.appearance.observe(None)
            for _ in range(400): s.step()
            self.assertLess(abs(s.background.look_bend), 1e-8)
            self.assertLess(max((c.position-p).length() for c,p in zip(s.body.chunks,s.background.targets)), 1e-6)

    def test_edge_inner_outer_corners_and_moving_observation(self):
        for center, angle in ((Vec2(130,300), -math.pi/2), (Vec2(570,300), math.pi/2),
                              (Vec2(350,110), 0), (Vec2(350,490), math.pi),
                              (Vec2(55,55), math.pi), (Vec2(645,545), 0)):
            s = placed(angle, center, edge=True)
            for goal in (Vec2(350,300), center+rotate(Vec2(50,-150),angle)):
                s.appearance.observe(goal, 600)
                for _ in range(500):
                    old = [(f.phase,f.position) for f in s.feet]
                    s.step()
                    self.assertTrue(s.background.attached)
                    for p in [*s.body.chunks,s.appearance.head,*s.appearance.tail]:
                        self.assertTrue(s.world.background_contains(p.position,p.radius), (center,p))
                    previous = s.body.chunks[2].position
                    for tail in s.appearance.tail:
                        self.assertLessEqual((tail.position-previous).length(), tail.length+1e-5)
                        previous = tail.position
                    for f,(phase,point) in zip(s.feet,old):
                        if f.phase == phase == FootPhase.STANCE:
                            self.assertEqual(f.position,point)
            s.background.set_enabled(False,s.body,s.world)
            old_y = s.body.chunks[1].position.y
            s.step()
            self.assertGreater(s.body.chunks[1].position.y,old_y)

        m = DesktopMotion(800,600,mode='wall')
        s = m.scene
        for tick in range(2300):
            if tick % 250 == 0:
                s.appearance.observe(Vec2(400,300),200)
            m.step()
            self.assertTrue(s.background.attached)
            self.assertTrue(all(s.world.in_edge(p.position) for p in [*s.body.chunks,s.appearance.head,*s.appearance.tail]))
            self.assertLess(max(s.body.connection_error(c) for c in s.body.connections), .002)
            previous = s.body.chunks[2].position
            for tail in s.appearance.tail:
                self.assertLessEqual((tail.position-previous).length(), tail.length+1e-5)
                previous = tail.position
        self.assertLess(abs(s.background.look_bend), .01)
