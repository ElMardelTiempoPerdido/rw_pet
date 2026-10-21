"""透明桌面的保守外形包围盒，包含前后物理帧，供缓存与清除旧像素使用。"""
from PySide6.QtCore import QRectF
from ..ear_config import ear_radius
from ..motion.cape import max_deflection
from .outfits import outfit_padding


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
    points = scene.appearance.body_points if scene.config.hide_cords else scene.appearance.points
    extra = outfit_padding(scene.config)
    soft = point_bounds((v for p in points
                         for v in (p.previous_position, p.position)), 20.+extra)
    head = scene.appearance.head
    radius = ear_radius(scene.config.active_custom_appearance)+extra
    if radius > 20.+extra:
        soft = soft.united(point_bounds((head.previous_position, head.position), radius))
    # 外壳弯折至多 24，活塞可伸出 length/4，另含底座和抗锯齿余量。
    if scene.prince_tentacles is not None:
        arm = QRectF()
        for part in scene.prince_tentacles.parts:
            arm = arm.united(point_bounds((v for p in part.nodes
                                          for v in (p.previous_position, p.position)), part.padding))
    else:
        arm = point_bounds((v for p in (*scene.arm.joints, scene.body.chunks[1])
                            for v in (p.previous_position, p.position)),
                           32.+max(scene.arm.lengths)/4)
    return soft.united(arm).united(cape_bounds(scene))


def cape_bounds(scene):
    shape = scene.config.active_custom_appearance
    if shape is None or not shape.cape.enabled:
        return QRectF()
    upper = scene.body.chunks[0]
    # 单独容纳最长斗篷，旋转/倒立时同样覆盖；袖子端点仍在原有人偶范围内
    radius = shape.cape.length+shape.chest_height+shape.sleeve_cuff_width+2+max_deflection(shape.cape.length)
    return point_bounds((upper.previous_position, upper.position), radius)


def soft_part_bounds(part, alpha=None):
    """带宽覆盖网格法线；未指定插值时覆盖前后物理帧及其中任意插值姿态"""
    points = ((v for p in part.points for v in (p.previous_position, p.position)) if alpha is None
              else (p.sample(alpha) for p in part.points))
    return point_bounds(points, part.width/2+2)


def visual_bounds(scene):
    result = body_bounds(scene)
    for part in scene.soft_parts.parts:
        if part is not None:
            result = result.united(soft_part_bounds(part))
    projection = scene.projection
    if projection.visible:
        for center in (projection.previous_position, projection.position):
            result = result.united(QRectF(center.x-projection.WIDTH/2-2, center.y-projection.HEIGHT/2-2,
                                         projection.WIDTH+4, projection.HEIGHT+4))
    if scene.halo_visible:
        halo = scene.halo
        result = result.united(point_bounds((halo.previous_center, halo.center), halo.extent+2))
        for arc in scene.halo_arcs.arcs:
            box = arc.region
            result = result.united(QRectF(box.left-1, box.top-1,
                                         box.right-box.left+2, box.bottom-box.top+2))
    for group in (scene.pearl_matrix, scene.pearl_orbits, scene.fixed_pearls):
        if group is not None:
            points = (p for alpha in (0., 1.) for p, _, _ in group.samples(alpha))
            bounds = point_bounds(points, 20.)  # 含 15px 字形及珍珠高光。
            if not bounds.isEmpty():
                result = result.united(bounds)
    pearl = scene.pearl_matrix.extracted if scene.pearl_matrix is not None else None
    if pearl is not None and pearl.playback is not None:
        # 可配置的大光泡可能超出文字投影余量；同时覆盖前后帧，避免桌面残影。
        result = result.united(point_bounds((pearl.previous_position, pearl.position),
                                           scene.config.pearl_bubble_max_size/2+2))
    if scene.config.glow_enabled and scene.config.glow_opacity > 0:
        # 包含附件自身的柔光；绘制密度至少为 1，额外 3px 覆盖画布取整和模糊留白
        margin = scene.config.glow_radius+3
        result = result.adjusted(-margin, -margin, margin, margin)
    return result
