"""Oracle 机械臂的只读外观几何，参考 OracleGraphics.ArmJointGraphics。

主关节与肘部继续使用桌面支撑解；外壳曲线、细杆和底座支架不反向施力。
中心线保持原有 7 单位边界余量，最大外壳厚度另限幅，覆盖绘制插值帧。
"""
from dataclasses import dataclass
from math import pi, sin, sqrt

from .geometry import Bounds, Vec2
from .oracle_appearance import arm_elbow, normalized, perpendicular
from .oracle_navigation import Bezier, EdgeRegion


def detail_scale(scale):
    # 轨道距屏幕边缘 18，主杆距中央区域 7。长臂可以加长，外壳与底座
    # 横向厚度最多采用默认 0.6 比例，给抗锯齿及转动件保留余量。
    return min(scale, .6)


def base_support_region(world):
    # 圆角中底座侧轴会略靠近屏幕边缘，细支架使用自己的 3 单位安全边距。
    # 不能使用主关节的 18 单位外边界，否则支架在过角时会突然折起/展开。
    region = EdgeRegion(world, body=False)
    o = region.outer = Bounds(3, 3, world.width-3, world.height-3)
    h = region.hole
    region.boxes = (Bounds(o.left, o.top, o.right, h.top),
                    Bounds(h.right, o.top, o.right, o.bottom),
                    Bounds(o.left, h.bottom, o.right, o.bottom),
                    Bounds(o.left, o.top, h.left, o.bottom))
    return region


def fit_ray(origin, target, region):
    if region.segment_safe(origin, target):
        return target
    lo, hi = 0., 1.
    for _ in range(12):
        t = (lo+hi)*.5
        if region.segment_safe(origin, origin.lerp(target, t)):
            lo = t
        else:
            hi = t
    return origin.lerp(target, lo)


def fit_bend(a, b, candidate, region):
    def safe(p):
        return region.segment_safe(a, p) and region.segment_safe(p, b)
    if safe(candidate):
        return candidate
    origin = a.lerp(b, .5)
    lo, hi = 0., 1.
    for _ in range(12):
        t = (lo+hi)*.5
        if safe(origin.lerp(candidate, t)):
            lo = t
        else:
            hi = t
    return origin.lerp(candidate, lo)


def ik_bend(a, b, first, second, sign, region):
    d = max((b-a).length(), 1e-9)
    axis = normalized(b-a)
    along = max(0., min(d, (d*d+first*first-second*second)/(2*d)))
    height = sqrt(max(0., first*first-along*along))
    return fit_bend(a, b, a+axis*along+perpendicular(axis)*(height*sign), region)


def safe_curve(start, c1, c2, end, region):
    # 在同一侧接触边界时，只收弧度，不裁掉外壳像素。控制点从直线向
    # 原版曲线连续展开，凸包递归验证包括两次绘制之间的插值位置。
    line1, line2 = start.lerp(end, 1/3), start.lerp(end, 2/3)
    curve = Bezier(start, c1, c2, end)
    if curve.certified_safe(region):
        return curve
    lo, hi = 0., 1.
    for _ in range(9):
        t = (lo+hi)*.5
        curve = Bezier(start, line1.lerp(c1, t), line2.lerp(c2, t), end)
        if curve.certified_safe(region):
            lo = t
        else:
            hi = t
    return Bezier(start, line1.lerp(c1, lo), line2.lerp(c2, lo), end)


@dataclass(frozen=True, slots=True)
class ShellStrip:
    # 每个截面为中心、法线和半宽；主体与高光使用同一组截面。
    sections: tuple

    def outline(self, width=1.):
        left = [p-n*(r*width) for p, n, r in self.sections]
        right = [p+n*(r*width) for p, n, r in self.sections]
        return left + list(reversed(right))


@dataclass(frozen=True, slots=True)
class ArmFrame:
    start: Vec2
    end: Vec2
    elbow: Vec2
    root_circle: Vec2
    strips: tuple[ShellStrip, ShellStrip]
    piston: Vec2
    metal_end: Vec2


def make_arm_frame(a, b, length, index, scale, region):
    ds = detail_scale(scale)
    elbow = (ik_bend(a, b, length/3, length/3, -1, region) if index == 3
             else arm_elbow(a, b, length, index, region))
    incoming, outgoing = normalized(elbow-a), normalized(b-elbow)
    middle = normalized(incoming+outgoing, normalized(b-a))
    start = a+incoming*min(.025*length+2*ds, (elbow-a).length()*.4)
    end = b-outgoing*min(.0125*length+2*ds, (b-elbow).length()*.4)
    curves = (safe_curve(start, start+incoming*((elbow-start).length()*.2),
                         elbow-middle*((elbow-start).length()*.2), elbow, region),
              safe_curve(elbow, elbow+middle*((end-elbow).length()*.2),
                         end-outgoing*((end-elbow).length()*.2), end, region))
    count = max(3, int(length/10))
    strips = []
    for half, curve in enumerate(curves):
        sections = []
        for i in range(count):
            t = i/(count-1)
            u = 1-t
            derivative = ((curve.b-curve.a)*(u*u) + (curve.c-curve.b)*(2*u*t)
                          + (curve.d-curve.c)*(t*t))
            side = perpendicular(normalized(derivative, incoming if half == 0 else outgoing))
            profile = .6+.5*(1-sin(pi*t))+.3*max(sin(min(1., t/.3)*pi),
                                                               sin(max(0., (t-.7)/.3)*pi))
            if i == count-1:
                profile = .5
            radius = (7., 5., 4., 3.)[index]*ds*profile
            offset = 0.
            if (half == 0 and t > .75) or (half == 1 and t < .25):
                radius *= .5
                offset = radius*(1 if index % 2 == 0 else -1)
            sections.append((curve.sample(t)+side*offset, side, radius))
        strips.append(ShellStrip(tuple(sections)))
    root = a+incoming*min((12 if index == 0 else 2)*ds, (elbow-a).length()*.4)
    piston = fit_bend(elbow, b, elbow+normalized(a.lerp(b, .8)-elbow)*(length/4), region)
    # MirosLegSmallPart 原图 4×25，只挂在肘部；固定倍率而非拉满整根杆。
    metal_length = 25*(2 if index == 0 else 1 if index == 1 else .5)*ds
    target = a.lerp(b, .2)
    metal_end = elbow+normalized(target-elbow)*min(metal_length, (target-elbow).length())
    metal_end = fit_ray(elbow, metal_end, region)
    return ArmFrame(a, b, elbow, root, tuple(strips), piston, metal_end)


def base_outline(base, normal, scale, width=30., height=17., inner_width=20.):
    ds = detail_scale(scale)
    origin = base-normal*(10*ds)
    side = perpendicular(normal)
    profile = ((-inner_width*.5, -height), (-width, -height*.75),
               (-width, height*.75), (-width*.8, height), (-width*.5, height),
               (-width*.3, -height*.1), (width*.3, -height*.1),
               (width*.5, height), (width*.8, height), (width, height*.75),
               (width, -height*.75), (inner_width*.5, -height))
    return [origin+side*(x*ds)+normal*(y*ds) for x, y in profile]
