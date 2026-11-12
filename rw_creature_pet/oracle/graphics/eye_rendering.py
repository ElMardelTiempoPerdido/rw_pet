"""眼睛绘制方案选择；仅供开发比较，不写入角色或用户设置"""
from .eyes import PixelEye
from .eyes_shape_aware import ShapeAwareEye


# shape_aware：圆形保形，其他眼形柔化采样（当前默认）
# stable_pixels：上一版的小角度保形、滞回及大角度二值绘制
EYE_RENDER_MODE = 'shape_aware'


def make_eye(*args, **kwargs):
    if EYE_RENDER_MODE == 'shape_aware':
        return ShapeAwareEye(*args, **kwargs)
    if EYE_RENDER_MODE == 'stable_pixels':
        return PixelEye(*args, **kwargs)
    raise ValueError(f'Unknown eye render mode: {EYE_RENDER_MODE}')
