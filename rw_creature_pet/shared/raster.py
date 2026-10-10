"""显示倍率对应的像素画布密度，不改变世界坐标或物理尺寸"""


def pixel_density(mode, scale, coarse_pixels_4x=False):
    scale = round(max(1., min(4., scale)), 6)
    if mode == 'classic' or scale == 3. or (scale == 4. and coarse_pixels_4x):
        return 1.
    return 2. if scale == 4. else scale
