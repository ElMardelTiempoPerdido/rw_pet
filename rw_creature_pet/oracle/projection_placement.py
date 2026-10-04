"""投影的机械臂避让：复用外观几何，缓存带余量的局部障碍框，不依赖 Qt。"""
from ..shared.geometry import Bounds, Vec2
from .appearance import normalized
from .arm_graphics import (arm_frame_curves, base_outline, base_support_region, detail_scale,
                           ik_bend)


def intersects_segment(box, start, end):
    """闭合线段与矩形相交；两端都在框外的穿越也算阻挡。"""
    lo, hi = 0., 1.
    for origin, delta, low, high in ((start.x, end.x-start.x, box.left, box.right),
                                    (start.y, end.y-start.y, box.top, box.bottom)):
        if abs(delta) < 1e-9:
            if not low <= origin <= high:
                return False
        else:
            a, b = sorted(((low-origin)/delta, (high-origin)/delta))
            lo, hi = max(lo, a), min(hi, b)
            if lo > hi:
                return False
    return True


class ProjectionArmObstacles:
    GAP = 5.  # 逻辑像素：外壳之外再留空隙，包含像素取整误差。

    def __init__(self):
        self.key = None
        self.boxes = ()

    def broadly_clear(self, scene, start, middle, end, width, height):
        """远离机械臂时只查四个保守框，不重新求外壳曲线。"""
        parts = (*scene.arm.joints, scene.body.chunks[1])
        for i, (a, b) in enumerate(zip(parts, parts[1:])):
            # 肘部最多偏离主段 24；活塞可再伸 length/4，另含关节、底座支架。
            pad = 24+scene.arm.lengths[i]/4+10*detail_scale(scene.config.arm_scale)+self.GAP
            points = (a.position, a.previous_position, b.position, b.previous_position)
            box = Bounds(min(p.x for p in points)-pad-width/2, min(p.y for p in points)-pad-height/2,
                         max(p.x for p in points)+pad+width/2, max(p.y for p in points)+pad+height/2)
            if intersects_segment(box, start, middle) or intersects_segment(box, middle, end):
                return False
        return True

    def update(self, scene):
        parts = (*scene.arm.joints, scene.body.chunks[1])
        positions = tuple(part.position for part in parts)
        previous = tuple(part.previous_position for part in parts)
        normals = (scene.base_normal(0.), scene.base_normal())
        key = (positions, previous, normals, scene.arm_region, scene.config.arm_scale,
               scene.world.width, scene.world.height, scene.world.edge_fraction)
        if key == self.key:
            return self
        boxes = []
        # 细分外壳沿曲线分段包围，避免用整条机械臂的大矩形误封住大量空白。
        # 前后物理帧均纳入；额外运动余量覆盖渲染插值时的弯折变化。
        motion = max((a-b).length() for a, b in zip(positions, previous))
        def add(points, radius=0.):
            pad = radius+self.GAP+motion
            boxes.append(Bounds(min(p.x for p in points)-pad, min(p.y for p in points)-pad,
                                max(p.x for p in points)+pad, max(p.y for p in points)+pad))

        ds = detail_scale(scene.config.arm_scale)
        support_region = base_support_region(scene.world)
        poses = [(positions, normals[1])]
        if positions != previous or normals[0] != normals[1]:
            poses.append((previous, normals[0]))
        for points, normal in poses:
            frames = [arm_frame_curves(a, b, scene.arm.lengths[i], i, scene.config.arm_scale,
                                      scene.arm_region) for i, (a, b) in enumerate(zip(points, points[1:]))]
            base = points[0]
            add(base_outline(base, normal, scene.config.arm_scale))
            # 底座两侧支架及圆盘。
            tangent, origin = Vec2(-normal.y, normal.x), base-normal*(10*ds)
            target = base.lerp(frames[0][0], .25)
            for sign in (-1, 1):
                add((origin+tangent*(17*ds*sign),), 5*ds)
                anchor = origin+normal*(11*ds)+tangent*(17*ds*sign)
                knee = ik_bend(anchor, target, 25*ds, 45*ds, sign, support_region)
                add((anchor, knee), ds)
                add((knee, target), ds)
                add((knee,), 2.5*ds)
            for index, (elbow, incoming, curves) in enumerate(frames):
                a, b = points[index:index+2]
                length = scene.arm.lengths[index]
                for curve in curves:
                    # 四段控制点凸包包含曲线；再含收直后的对应区间。
                    # safe_curve 只在线与原曲线之间收弧，不必重复它的边界迭代。
                    quarters = tuple(q for half in curve.split() for q in half.split())
                    for n, q in enumerate(quarters):
                        add((q.a, q.b, q.c, q.d, curve.a.lerp(curve.d, n/4),
                             curve.a.lerp(curve.d, (n+1)/4)), (7., 5., 4., 3.)[index]*ds*1.4)
                # 齿条的转动外缘比关节圆盘略大，使用外接圆。
                root = a+incoming*min((12 if index == 0 else 2)*ds, (elbow-a).length()*.4)
                add((root,), (10-index)*ds)
                add((elbow,), max(2.5, 6-index*1.5)*ds)
                metal_length = 25*(2 if index == 0 else 1 if index == 1 else .5)*ds
                target = a.lerp(b, .2)
                metal = elbow+normalized(target-elbow)*min(metal_length, (target-elbow).length())
                add((elbow, metal), 2*(1.5 if index == 0 else 1 if index == 1 else .8)*ds)
                piston = elbow+normalized(a.lerp(b, .8)-elbow)*(length/4)
                # fit_bend 将活塞收向 elbow/b 的中点，此三角形涵盖细杆与盘。
                add((elbow, b, piston), 2.5*ds)
        self.key, self.boxes = key, tuple(boxes)
        return self

    def clear_path(self, start, end, width, height):
        # 把完整投影矩形的半宽/半高加到障碍框，再检查中心的移动线段。
        # 因而边框擦过杆件、或起终点安全但中途穿过机械臂，都会被拒绝。
        return not any(intersects_segment(
            Bounds(box.left-width/2, box.top-height/2, box.right+width/2, box.bottom+height/2),
            start, end) for box in self.boxes)

    def clear(self, center, width, height):
        return self.clear_path(center, center, width, height)
