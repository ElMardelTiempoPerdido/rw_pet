"""Bell 与自定义模板的绘制入口；共用布料、像素化和缓存，不共用角色装饰"""
from .face_assets import decal_key
from .earphones import draw_ear, ear_assets_key
from . import prince
from .prince_robe import draw_lower_robe


class CommonStyle:
    def draw_body_back(self, renderer, painter, scene, alpha, *, density=1.):
        pass

    def head_assets_key(self, shape):
        return None

    def draw_body(self, renderer, painter, *args, **kwargs):
        return renderer.draw_body(painter, *args, **kwargs)


class BellStyle(CommonStyle):
    name = 'bell'

    def head_options(self, renderer, density):
        pixels = renderer.PHONE_PIXEL_WIDTHS.get(density)
        return pixels or (1., 1.), pixels is not None, renderer.FACE_MARK_PIXEL_WIDTHS.get(density)

    def draw_head(self, renderer, painter, *args, shape=None, **kwargs):
        renderer.draw_head_parts(painter, *args, **kwargs)

    def draw_body_decorations(self, renderer, painter, scene, alpha):
        renderer.draw_necklace(painter, scene, alpha)


class CustomStyle(CommonStyle):
    name = 'custom'

    def head_assets_key(self, shape):
        return decal_key(shape.forehead), decal_key(shape.face), ear_assets_key(shape), shape.eye_1, shape.eye_2

    def head_options(self, renderer, density):
        # 自定义部件不继承 Bell 的逐倍率笔画和标记修正
        return (1., 1.), False, None

    def draw_head(self, renderer, painter, gx, gy, openness=0., *, near_phone=None,
                  head_length=1., phone_widths=(1., 1.), phone_cosmetic=False, mark_pixels=None, shape=None, eye_closure=0.):
        near = (-1 if gx >= 0 else 1) if near_phone is None else near_phone
        draw_ear(painter, renderer.colors, shape, -near, gx, gy)
        renderer.draw_face(painter, gx, gy, openness, head_length, shape=shape, eye_closure=eye_closure)
        draw_ear(painter, renderer.colors, shape, near, gx, gy)

    def draw_body_decorations(self, renderer, painter, scene, alpha):
        # 自定义模板暂不挂载颈部饰品，附加套装仍由公共图层绘制
        pass


BELL_STYLE = BellStyle()
CUSTOM_STYLE = CustomStyle()


class PrinceStyle(CommonStyle):
    name = 'prince'

    def draw_body_back(self, renderer, painter, scene, alpha, *, density=1.):
        draw_lower_robe(renderer, painter, scene, alpha, density=density)

    def head_options(self, renderer, density):
        return (1., 1.), False, None

    def draw_head(self, renderer, painter, *args, **kwargs):
        prince.draw_head(renderer, painter, *args, **kwargs)

    def draw_body(self, renderer, painter, *args, **kwargs):
        return prince.draw_body(renderer, painter, *args, **kwargs)

    def draw_body_decorations(self, renderer, painter, scene, alpha):
        pass


PRINCE_STYLE = PrinceStyle()


def style_for(shape, body=None):
    if body == 'prince':
        return PRINCE_STYLE
    return CUSTOM_STYLE if shape is not None else BELL_STYLE
