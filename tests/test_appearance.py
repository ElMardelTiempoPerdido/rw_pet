import copy
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtGui import QColor, QImage, QPainter

from rw_creature_pet.appearance import WhiteAppearance
from rw_creature_pet.atlas import Atlas, AtlasError, extract_atlas
from rw_creature_pet.config import DEFAULT_GAME_DIR, DebugConfig
from rw_creature_pet.geometry import Vec2
from rw_creature_pet.render_lizard import LizardRenderer, strip_mesh, tail_mesh
from rw_creature_pet.scene import DebugScene


class AppearanceTests(unittest.TestCase):
    def test_original_white_parameters_and_mesh_topology(self):
        s = DebugScene(DebugConfig())
        p = WhiteAppearance()
        self.assertEqual(p.head_graphics, (0, 0, 0, 0, 3))
        self.assertEqual((p.tail_segments, p.tail_length_factor, p.tail_stiffness, p.tail_stiffness_decline), (5, 1.2, 800, .1))
        for i, segment in enumerate(s.appearance.tail):
            self.assertAlmostEqual(segment.radius, [8, 6.4, 4.8, 3.2, 1.6][i])
            self.assertAlmostEqual(segment.length, [14.4, 8.64, 7.68, 6.72, 5.76][i])
        vertices, triangles = strip_mesh([Vec2(i * 8, 10) for i in range(5)], [5, 8, 8, 8, 8])
        self.assertEqual((len(vertices), len(triangles)), (16, 8))
        vertices, triangles = tail_mesh(s.body.chunks[2].position, s.appearance.tail, 1, 8, 1)
        self.assertEqual((len(vertices), len(triangles)), (19, 17))
        self.assertTrue(all(0 <= index < len(vertices) for tri in triangles for index in tri))

    def test_tail_remains_finite_attached_and_above_floor_during_turns(self):
        s = DebugScene(DebugConfig())
        s.gait.enabled = True
        for tick in range(2000):
            if tick % 220 == 0:
                s.gait.set_speed(.65 if tick % 440 == 0 else -.65)
            s.step()
            previous = s.body.chunks[2].position
            for segment in s.appearance.tail:
                self.assertTrue(math.isfinite(segment.position.x + segment.position.y + segment.velocity.length()))
                self.assertLessEqual(segment.position.y + segment.radius, s.world.floor_y + 1e-6)
                self.assertLessEqual((segment.position - previous).length(), segment.length + 1e-5)
                previous = segment.position
        s.reset()
        self.assertTrue(all(p.position == p.previous_position and p.velocity == Vec2() for p in s.appearance.tail))

    def test_wall_pose_rotates_with_fixed_head_view_and_split_limb_layers(self):
        class Recorder(LizardRenderer):
            def __init__(self):
                self.calls = []

            def _sprite(self, painter, name, position, angle=0, scale_x=1, scale_y=1, *args, **kwargs):
                self.calls.append((name, angle, scale_x, scale_y))

            def _mesh(self, painter, vertices, triangles):
                self.calls.append(('mesh', len(vertices)))

        renderer = Recorder()
        canvas = QImage(800, 800, QImage.Format.Format_ARGB32)
        s = DebugScene(DebugConfig(world_width=800, world_height=800, floor_y=760))
        s.place_on_background(380)
        center = s.body.chunks[1].position
        original = copy.deepcopy(s)
        baseline = None
        for angle in range(0, 361):
            s = copy.deepcopy(original)
            c, sn = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            for point in [*s.body.chunks, s.appearance.head, *s.appearance.tail, *s.feet]:
                delta = point.position - center
                point.position = center + Vec2(delta.x*c-delta.y*sn, delta.x*sn+delta.y*c)
                point.previous_position = point.position
            renderer.calls = []
            painter = QPainter(canvas)
            try:
                renderer.draw(painter, s, 1)
            finally:
                painter.end()
            names = [call[0] for call in renderer.calls]
            self.assertTrue(all(name.startswith('LizardArm_') for name in names[:2]))
            self.assertEqual(renderer.calls[2:4], [('mesh', 19), ('mesh', 16)])
            self.assertTrue(all(name.startswith('LizardArm_') for name in names[-7:-5]))
            head = renderer.calls[-5:]
            self.assertEqual([call[0] for call in head],
                             ['LizardJaw3.0', 'LizardLowerTeeth3.0', 'LizardUpperTeeth3.0', 'LizardHead3.0', 'LizardEyes3.3'])
            self.assertTrue(all(call[2:4] == (1, 1) for call in head))
            for call in renderer.calls[:2]+renderer.calls[-7:-5]:
                frame = int(call[0].split('_')[1])
                self.assertTrue(1 <= frame <= 9 or 28 <= frame <= 36)
            signature = [(call[0], call[2:4]) for call in renderer.calls if call[0] != 'mesh']
            if baseline is None:
                baseline = signature
            self.assertEqual(signature, baseline)

    def test_grounded_tail_settles_with_raised_chest_and_wakes(self):
        for left in (False, True):
            s = DebugScene(DebugConfig())
            s.gait.enabled = True
            s.gait.set_speed(0)
            for _ in range(200): s.step()
            if left:
                s.gait.set_speed(-.65)
                for _ in range(90): s.step()
                s.gait.set_speed(0)
            s.gait.posture = 'raised'
            for _ in range(1500): s.step()
            positions = [t.position for t in s.appearance.tail]
            widths = [t.stretched for t in s.appearance.tail]
            for _ in range(1000):
                s.step()
                previous = s.body.chunks[2].position
                for t, point, width in zip(s.appearance.tail, positions, widths):
                    self.assertLess((t.position-point).length(), 1e-6)
                    self.assertAlmostEqual(t.stretched, width)
                    self.assertLessEqual(t.position.y+t.radius, s.world.floor_y+1e-6)
                    self.assertLessEqual((t.position-previous).length(), t.length+1e-5)
                    previous = t.position
            s.gait.set_speed(.65 if not left else -.65)
            for _ in range(100): s.step()
            self.assertGreater((s.appearance.tail[-1].position-positions[-1]).length(), 10)

    def test_atlas_trim_tint_cache_and_missing_frame(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            image = QImage(4, 4, QImage.Format.Format_ARGB32)
            image.fill(QColor('white'))
            image.save(str(folder / 'rainWorld.png'))
            entry = {'frame': {'x': 1, 'y': 1, 'w': 2, 'h': 2}, 'trimmed': True,
                     'sourceSize': {'w': 8, 'h': 8}, 'spriteSourceSize': {'x': 3, 'y': 2}}
            (folder / 'rainWorld.json').write_text(json.dumps({'frames': {'test.png': entry}}), encoding='utf-8')
            atlas = Atlas(folder)
            sprite = atlas.sprite('test', '#141414')
            self.assertEqual((sprite.width(), sprite.height()), (8, 8))
            self.assertEqual(sprite.pixelColor(0, 0).alpha(), 0)
            self.assertEqual(sprite.pixelColor(3, 2), QColor('#141414'))
            self.assertIs(sprite, atlas.sprite('test', '#141414'))
            self.assertEqual(atlas.sprite('test').pixelColor(3, 2), QColor('white'))
            with self.assertRaises(AtlasError):
                atlas.sprite('missing')
            with self.assertRaises(AtlasError):
                extract_atlas(folder)

    @unittest.skipUnless((DEFAULT_GAME_DIR / 'RainWorld_Data/resources.assets').is_file(), '需要本机游戏图集')
    def test_real_atlas_rendering_is_read_only(self):
        root = extract_atlas(DEFAULT_GAME_DIR)
        stamp = (root / 'rainWorld.png').stat().st_mtime_ns
        self.assertEqual(extract_atlas(DEFAULT_GAME_DIR), root)
        self.assertEqual((root / 'rainWorld.png').stat().st_mtime_ns, stamp)
        atlas = Atlas(root)
        renderer = LizardRenderer(atlas)
        s = DebugScene(DebugConfig())
        s.gait.enabled = True
        for _ in range(80):
            s.step()
        before = copy.deepcopy((s.body.chunks, s.gait.feet, s.appearance.head, s.appearance.tail))
        canvas = QImage(480, 240, QImage.Format.Format_ARGB32)
        canvas.fill(QColor('#17202b'))
        painter = QPainter(canvas)
        renderer.draw(painter, s, .5)
        painter.end()
        self.assertEqual(before, (s.body.chunks, s.gait.feet, s.appearance.head, s.appearance.tail))
        self.assertGreater(sum(canvas.pixelColor(x, y).red() > 240 for x in range(120, 330) for y in range(100, 180)), 500)


if __name__ == '__main__':
    unittest.main()
