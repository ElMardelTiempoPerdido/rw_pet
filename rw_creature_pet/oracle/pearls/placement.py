"""固定悬浮点避让矩阵槽位；仅选点时搜索，不增加逐珠碰撞解算"""
from math import cos, sin, tau

from ...shared.geometry import Vec2


class MatrixHomeClearance:
    RADIUS = 24.
    # 选新点时多留一点余量，避免矩阵稍移就再次挪珠
    TARGET_RADIUS = 28.
    GRID_STEPS = 8
    DIRECTIONS = tuple(Vec2(cos(i*tau/8), sin(i*tau/8)) for i in range(8))

    def __init__(self, matrix=None):
        self.matrix = matrix
        self._key = None
        self._points = ()

    @property
    def key(self):
        return (self.matrix, self.matrix.anchor.home) if self.matrix is not None else None

    def choose(self, preferred, boxes):
        key = self.key
        if key is None:
            return preferred
        if key != self._key:
            # 使用将要停靠的槽位；抽出阅读时仍占位，归队后不会与固定珠重叠
            self._points = tuple(self.matrix.anchor.home+p.offset for p in self.matrix.pearls)
            self._key = key
        points = self._points

        def clearance(p):
            return min((p.x-q.x)**2+(p.y-q.y)**2 for q in points)

        if clearance(preferred) >= self.RADIUS**2:
            return preferred
        nearest = min(points, key=lambda p: (p-preferred).length())
        left, right = min(p.x for p in points), max(p.x for p in points)
        top, bottom = min(p.y for p in points), max(p.y for p in points)
        radius = self.TARGET_RADIUS
        probes = [nearest+d*radius for d in self.DIRECTIONS]
        probes.extend((Vec2(left-radius, preferred.y), Vec2(right+radius, preferred.y),
                       Vec2(preferred.x, top-radius), Vec2(preferred.x, bottom+radius)))
        candidates = {preferred}
        for box in boxes:
            candidates.update(box.clamp(p) for p in probes)
            # 固定上限的小网格补充角落/狭长交集中的候选，不随桌面尺寸增加搜索量
            for x in range(self.GRID_STEPS+1):
                for y in range(self.GRID_STEPS+1):
                    candidates.add(Vec2(box.left+(box.right-box.left)*x/self.GRID_STEPS,
                                        box.top+(box.bottom-box.top)*y/self.GRID_STEPS))
        scored = [(clearance(p), (p-preferred).length(), p) for p in candidates]
        for distance in (self.TARGET_RADIUS, self.RADIUS):
            safe = [item for item in scored if item[0] >= distance**2-1e-6]
            if safe:
                return min(safe, key=lambda item: (item[1], item[2].x, item[2].y))[2]
        # 密集矩阵或窄活动带没有足够空间时尽量拉开，不越界或反复随机试点
        return min(scored, key=lambda item: (-item[0], item[1], item[2].x, item[2].y))[2]
