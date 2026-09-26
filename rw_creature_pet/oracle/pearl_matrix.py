"""斜珍珠矩阵：整组软牵引、空间滞回及带外形余量的四边迁移。

Oracle.SetUpMarbles 的 3×5 缺一格布局；允许抽取一颗，保留槽位再归队。
使用一个 PearlState 导引锚点，避免为每颗珠子重复规划和解算边界。
"""
from dataclasses import dataclass
from math import ceil, cos, radians, sin, sqrt
from random import Random

from ..shared.geometry import Bounds, Vec2
from .navigation import EdgeRegion
from .pearl import PearlColorSlot, PearlState
from .pearl_layout import PearlGroupRegion as MatrixRegion, balanced_colors, group_follow_boxes


class ExtractedPearlRegion(EdgeRegion):
    """单颗珠体和右上角投影的非对称余量；覆盖所有矩阵槽位。"""

    def __init__(self, world):
        w, h, inner = world.width, world.height, world.inner
        # 可见范围为左 4、上 15、右 15、下 4，再留一个像素取整余量。
        self.outer = Bounds(5, 16, w-16, h-5)
        self.hole = Bounds(inner.left-16, inner.top-5, inner.right+5, inner.bottom+16)
        self.boxes = (Bounds(5, 16, w-16, self.hole.top),
                      Bounds(self.hole.right, 16, w-16, h-5),
                      Bounds(5, self.hole.bottom, w-16, h-5),
                      Bounds(5, 16, self.hole.left, h-5))


@dataclass(frozen=True, slots=True)
class MatrixPearl:
    slot: tuple[int, int]
    offset: Vec2
    glyph_id: int
    color_slot: PearlColorSlot


class PearlMatrix:
    SPACING = 17.
    FOLLOW_INSET = 32.
    # 留出像素取整/珠体边缘和一条可弯曲的锚点走廊；小场景整体缩紧间距。
    PIXEL_PAD = 2.
    MIN_CORRIDOR = 16.

    def __init__(self, world, body_region, center, normal, width, height, count=14):
        if type(count) is not int or not 1 <= count <= 64:
            raise ValueError('矩阵珠数量必须为 1～64 的整数')
        self.world = world
        self.extracted = self.extracted_member = None
        self._extracted_replan_ticks = 0
        self._extra_revision = 0
        angle = radians(-32.7346)
        # 原版 y 向上，这里转换为屏幕 y 向下；四边均保持同一矩阵朝向。
        axis, across = Vec2(sin(angle), -cos(angle)), Vec2(-cos(angle), -sin(angle))
        if count == 14:
            slots = [(k, l) for k in range(3) for l in range(5) if (k, l) != (2, 2)]
        else:
            rows = max(1, round(sqrt(count*3/5)))
            columns = ceil(count/rows)
            slots = [(i//columns, i % columns) for i in range(count)]
        points = [(across*k+axis*l)*self.SPACING for k, l in slots]
        left, right = min(p.x for p in points), max(p.x for p in points)
        top, bottom = min(p.y for p in points), max(p.y for p in points)
        reserve = 19+2*self.PIXEL_PAD+self.MIN_CORRIDOR
        available_x = min(world.inner.left-reserve, width/2+world.body_margin-4-23)
        available_y = min(world.inner.top-reserve, height/2+world.body_margin-4-23)
        self.layout_scale = min(1., available_x/max(1., right-left), available_y/max(1., bottom-top))
        points = [p*self.layout_scale for p in points]
        # 珠体 ±4；字形从珠心向右 15、向上 15。锚点位于整个可见框中心。
        left, right = min(p.x for p in points)-4, max(p.x for p in points)+15
        top, bottom = min(p.y for p in points)-15, max(p.y for p in points)+4
        midpoint = Vec2((left+right)/2, (top+bottom)/2)
        self.half_size = Vec2((right-left)/2+self.PIXEL_PAD, (bottom-top)/2+self.PIXEL_PAD)
        random = Random(12843)  # 不消耗人偶行为或单珠的随机流。
        original = tuple(2 if slot in ((2, 0), (1, 3)) else 1 for slot in slots) if count == 14 else ()
        colors = balanced_colors(count, (0, 12, 2), original)
        self.pearls = tuple(MatrixPearl(slot, p-midpoint, random.randrange(14), color)
                            for slot, p, color in zip(slots, points, colors))
        self.region = MatrixRegion(world, self.half_size)
        self.body_region = body_region
        self.width, self.height = width, height
        self.follow_bounds = None
        self._replan_ticks = 0
        # 与单颗观察珠优先分居两侧，空间不足时整组投影，绝不逐颗夹紧。
        preferred = center-Vec2(normal.y, -normal.x)*110
        boxes = self._follow_boxes(center)
        home = min((box.clamp(preferred) for box in boxes), key=lambda p: (p-preferred).length())
        self.anchor = PearlState(home, world, self.region)

    @property
    def revision(self):
        return self.anchor.revision+self._extra_revision

    @property
    def settled(self):
        return self.anchor.settled and (self.extracted is None or self.extracted.settled)

    def extract(self, slot):
        """最多一颗离队；重复请求返回正在观察/归队的珠子，不复制珠子。"""
        member = next((p for p in self.pearls if p.slot == slot), None)
        if member is None:
            raise ValueError(f'不存在的矩阵槽位：{slot}')
        if self.extracted is not None:
            return self.extracted
        pearl = PearlState(self.anchor.position+member.offset, self.world,
                           ExtractedPearlRegion(self.world), member.glyph_id, color_slot=member.color_slot)
        pearl.previous_position = self.anchor.previous_position+member.offset
        pearl.velocity = self.anchor.velocity
        pearl.settled = pearl.velocity.length() == 0.
        pearl.returning_home = False
        self.extracted, self.extracted_member = pearl, member
        self._extracted_replan_ticks = 0
        self._extra_revision += 1
        return pearl

    def _step_extracted(self):
        pearl = self.extracted
        if pearl is None:
            return
        # 槽位随真实矩阵锚点移动；不能返回抽取时的旧绝对坐标。
        pearl.home = self.anchor.position+self.extracted_member.offset
        self._extracted_replan_ticks = max(0, self._extracted_replan_ticks-1)
        if (pearl.returning_home and pearl.target != pearl.home
                and self._extracted_replan_ticks == 0):
            pearl._set_target(pearl.home, catch_up=True)
            self._extracted_replan_ticks = pearl.REPLAN_TICKS
        before = pearl.revision
        pearl.step()
        self._extra_revision += pearl.revision-before
        if (pearl.returning_home and self.anchor.settled and pearl.settled
                and (pearl.position-pearl.home).length() < 1e-6):
            # 只有真正到达当前槽位后才重新使用整组采样，避免吸附跳变。
            self.extracted = self.extracted_member = None
            self._extra_revision += 1

    def _follow_boxes(self, center):
        x, y = self.width/2, self.height/2
        self.follow_bounds = Bounds(center.x-x, center.y-y, center.x+x, center.y+y)
        return group_follow_boxes(center, self.body_region, self.region, self.width, self.height, self.half_size)

    def step(self, center):
        boxes = self._follow_boxes(center)
        anchor = self.anchor
        self._replan_ticks = max(0, self._replan_ticks-1)
        if not any(box.contains(anchor.home) for box in boxes):
            candidates = []
            for box in boxes:
                dx = min(self.FOLLOW_INSET, (box.right-box.left)*.25)
                dy = min(self.FOLLOW_INSET, (box.bottom-box.top)*.25)
                candidates.append(Bounds(box.left+dx, box.top+dy, box.right-dx, box.bottom-dy).clamp(anchor.home))
            anchor.home = min(candidates, key=lambda p: (p-anchor.home).length())
        if anchor.target != anchor.home and self._replan_ticks == 0:
            anchor._set_target(anchor.home, catch_up=True)
            self._replan_ticks = anchor.REPLAN_TICKS
        anchor.step()
        self._step_extracted()

    def samples(self, alpha=1.):
        center = self.anchor.sample(alpha)
        for member in self.pearls:
            position = (self.extracted.sample(alpha) if member is self.extracted_member
                        else center+member.offset)
            yield position, member.glyph_id, member.color_slot
