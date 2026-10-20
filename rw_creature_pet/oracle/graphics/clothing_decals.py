"""按自然垂手的参考网格放置原尺寸 PNG，再映射到当前衣料，不新增物理"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPolygonF, QTransform

from ...shared.geometry import Vec2
from ..clothing_config import CLOTHING_DECAL_FIELDS
from .appearance import HangingHand, normalized
from .face_assets import decal_image, decal_key
from .shoulders import follow_gown_root


def clothing_key(shape):
    return tuple(decal_key(getattr(shape, name)) for name in CLOTHING_DECAL_FIELDS) if shape else ()


def active_decals(shape, part):
    if shape is None:
        return ()
    return tuple(decal for name in CLOTHING_DECAL_FIELDS
                 if (decal := getattr(shape, name)).enabled and decal.image_path and decal.part == part)


def reference_cloth(app):
    """固定的自然下垂参考姿态，含初始垂坠量；运行中不能随衣料坐标重新定位贴图"""
    n = app.CLOTH_DIVS
    return tuple(Vec2(x, -y+app.CLOTH_SLACK*(i//n)/(n-1))
                 for i, (x, y) in enumerate(app._cloth_local))


def clothing_mesh(renderer, app, shape, part, current):
    """返回逻辑像素参考坐标、当前顶点及与原衣料相同的三角形拓扑"""
    key = (shape, tuple(app._cloth_local), app.CLOTH_DIVS, app.CLOTH_SLACK)
    cached = getattr(renderer, '_clothing_reference', None)
    if cached is None or cached[0] != key:
        cached = renderer._clothing_reference = (key, {})
    meshes = cached[1]
    if part not in meshes:
        rest = reference_cloth(app)
        n = app.CLOTH_DIVS
        if part == 'robe':
            origin = rest[n//2]
            coords = tuple(p-origin for p in rest)
            triangles = tuple(ids for y in range(n-1) for x in range(n-1)
                              for i in (y*n+x,)
                              for ids in ((i, i+1, i+n+1), (i, i+n+1, i+n)))
        else:
            sign = -1 if part == 'left_sleeve' else 1
            upper, direction = Vec2(), Vec2(0, -1)
            hand = normalized(Vec2(sign*.3, .8))*HangingHand.MAX_REACH
            shoulder = renderer.sleeve_shoulder(upper, direction, sign, shape)
            edges = renderer.sleeve_edges(shoulder, hand, direction, sign, shape)
            column = 0 if sign < 0 else n-1
            boundary = tuple((app._cloth_local[i][1], rest[i]) for i in range(column, n*n, n))
            edges = follow_gown_root(edges, upper, direction, sign, hand, shape, boundary)
            points = tuple(p for edge in edges for p in edge)
            # 正视自然下垂时以袖子包围盒上边中央为零点；两侧都 X 向右，不自动镜像
            origin = Vec2((min(p.x for p in points)+max(p.x for p in points))*.5,
                          min(p.y for p in points))
            coords = tuple(p-origin for p in points)
            triangles = tuple(ids for i in range(0, len(points)-2, 2)
                              for ids in ((i, i+1, i+2), (i+1, i+2, i+3)))
        meshes[part] = coords, triangles
    coords, triangles = meshes[part]
    vertices = current if part == 'robe' else tuple(p for edge in current for p in edge)
    return coords, vertices, triangles


def draw_texture_mesh(painter, image, rect, coords, vertices, triangles):
    """逐三角形仿射映射；继承调用方的部位/领口裁剪和画布变换"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    for ids in triangles:
        first, second, third = (coords[i] for i in ids)
        if (max(first.x, second.x, third.x) <= rect.left()
                or min(first.x, second.x, third.x) >= rect.right()
                or max(first.y, second.y, third.y) <= rect.top()
                or min(first.y, second.y, third.y) >= rect.bottom()):
            continue
        a, b, c = (vertices[i] for i in ids)
        u, v = second-first, third-first
        determinant = u.x*v.y-v.x*u.y
        x, y = b-a, c-a
        if abs(determinant) < 1e-9 or abs(x.x*y.y-y.x*x.y) < 1e-9:
            continue
        xx, yx = (x.x*v.y-y.x*u.y)/determinant, (x.y*v.y-y.y*u.y)/determinant
        xy, yy = (y.x*u.x-x.x*v.x)/determinant, (y.y*u.x-x.y*v.x)/determinant
        transform = QTransform(xx, yx, xy, yy,
                               a.x-xx*first.x-xy*first.y, a.y-yx*first.x-yy*first.y)
        clip = QPainterPath()
        clip.addPolygon(QPolygonF([QPointF(p.x, p.y) for p in (a, b, c)]))
        clip.closeSubpath()
        painter.save()
        painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        painter.setWorldTransform(transform, True)
        painter.drawImage(rect, image)
        painter.restore()
    painter.restore()


def draw_clothing_decals(renderer, painter, scene, part, current):
    shape = scene.config.active_custom_appearance
    decals = active_decals(shape, part)
    if not decals:
        return
    mesh = clothing_mesh(renderer, scene.appearance, shape, part, current)
    for decal in decals:
        image = decal_image(decal)
        if image.isNull():
            continue
        rect = QRectF(decal.offset_x-image.width()*.5, decal.offset_y, image.width(), image.height())
        draw_texture_mesh(painter, image, rect, *mesh)
