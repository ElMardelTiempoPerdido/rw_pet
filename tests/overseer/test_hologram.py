import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter

from rw_creature_pet.overseer.hologram import LensHologramRenderer, noise_masks
from rw_creature_pet.shared.geometry import Vec2


def pixels(image):
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.width(), 4).copy()


class HologramTests(unittest.TestCase):
    def render(self, strength=1, *, lines=None, density=1, tick=5, background=0):
        image = QImage(round(100*density), round(100*density), QImage.Format.Format_RGBA8888_Premultiplied)
        image.fill(background)
        lines = lines if lines is not None else [(Vec2(8, y), Vec2(85, y), .85) for y in range(8, 85, 3)]
        painter = QPainter(image)
        try:
            painter.scale(density, density)
            LensHologramRenderer().draw(painter, lines, QColor('#ffffff'), strength, tick, (0, 0))
        finally:
            painter.end()
        return image

    def test_masks_are_shared_binary_and_remove_more_pixels_as_signal_falls(self):
        masks = noise_masks()
        self.assertIs(masks, noise_masks())
        for phase in range(3):
            alpha = [pixels(masks[level][phase])[:, :, 3] for level in (0, 16, 32)]
            self.assertTrue(all(set(np.unique(a)) == {0, 255} for a in alpha))
            self.assertLess(np.count_nonzero(alpha[0]), np.count_nonzero(alpha[1]))
            self.assertLess(np.count_nonzero(alpha[1]), np.count_nonzero(alpha[2]))
            self.assertTrue(np.all(alpha[0] <= alpha[1]))
            self.assertTrue(np.all(alpha[1] <= alpha[2]))
        self.assertFalse(np.array_equal(pixels(masks[16][0]), pixels(masks[16][1])))

    def test_pixel_dropout_preserves_surviving_brightness_and_moves_with_ticks(self):
        strong = pixels(self.render())[:, :, 3]
        weak = pixels(self.render(.5))[:, :, 3]
        self.assertEqual(set(np.unique(strong)), {0, 217})
        self.assertEqual(set(np.unique(weak)), {0, 217})
        self.assertLess(np.count_nonzero(weak), np.count_nonzero(strong))
        self.assertFalse(np.array_equal(weak, pixels(self.render(.5, tick=6))[:, :, 3]))
        self.assertEqual(self.render(.5), self.render(.5))

    def test_mask_does_not_erase_underlying_body_or_background(self):
        bg = QColor('#823451')
        image = self.render(.3, background=bg)
        self.assertTrue(np.all(pixels(image)[:, :, 3] == 255))
        self.assertEqual(image.pixelColor(50, 95), bg)

    def test_noise_stays_world_aligned_when_local_bounds_change_at_all_scales(self):
        lines = [(Vec2(20, 24), Vec2(60, 24), .85)]
        extra = (Vec2(4, 8), Vec2(10, 8), .85)
        for density in (1, 1.5, 2, 4):
            image = self.render(.5, lines=lines, density=density)
            larger = self.render(.5, lines=lines+[extra], density=density)
            rect = (round(15*density), round(20*density), round(50*density), round(10*density))
            self.assertEqual(image.copy(*rect), larger.copy(*rect), density)

    def test_closed_or_empty_lens_does_not_prepare_or_draw_masks(self):
        with patch('rw_creature_pet.overseer.hologram.noise_masks') as prepare:
            self.assertFalse(pixels(self.render(0)).any())
            self.assertFalse(pixels(self.render(lines=[])).any())
            prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
