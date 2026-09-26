"""透明桌面的保守外形包围盒，包含前后物理帧，供缓存与清除旧像素使用。"""
from PySide6.QtCore import QRectF


def point_bounds(points, padding):
    points = tuple(points)
    if not points:
        return QRectF()
    left, right = min(p.x for p in points), max(p.x for p in points)
    top, bottom = min(p.y for p in points), max(p.y for p in points)
    return QRectF(left-padding, top-padding, right-left+2*padding, bottom-top+2*padding)


def body_bounds(scene):
    # 33px 头图、袖口、领边均含在 20px 余量内。线缆允许垂入中央，
    # 必须取真实节点，不能仅使用活动带或人偶质点作为清除范围。
    soft = point_bounds((v for p in scene.appearance.points
                         for v in (p.previous_position, p.position)), 20.)
    # 外壳弯折至多 24，活塞可伸出 length/4，另含底座和抗锯齿余量。
    arm = point_bounds((v for p in (*scene.arm.joints, scene.body.chunks[1])
                        for v in (p.previous_position, p.position)),
                       32.+max(scene.arm.lengths)/4)
    return soft.united(arm)


def visual_bounds(scene):
    result = body_bounds(scene)
    if scene.halo_visible:
        halo = scene.halo
        result = result.united(point_bounds((halo.previous_center, halo.center), halo.extent+2))
    for group in (scene.pearl_matrix, scene.pearl_orbits, scene.fixed_pearls):
        if group is not None:
            points = (p for alpha in (0., 1.) for p, _, _ in group.samples(alpha))
            bounds = point_bounds(points, 20.)  # 含 15px 字形及珍珠高光。
            if not bounds.isEmpty():
                result = result.united(bounds)
    return result
