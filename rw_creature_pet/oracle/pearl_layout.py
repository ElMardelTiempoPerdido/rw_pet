"""珍珠编组共用的配色配额与外形边界；不消耗行为随机流。"""
from ..shared.geometry import Bounds
from .navigation import EdgeRegion
from .pearl import PearlColorSlot


def balanced_colors(count, weights, original=()):
    """最大余数取整；相同余数优先少数色，再均匀分散到成员顺序中。"""
    if count == len(original):
        return tuple(PearlColorSlot(color) for color in original)
    total = sum(weights)
    quotas = [count*weight//total for weight in weights]
    order = sorted(range(3), key=lambda i: (-(count*weights[i] % total), weights[i], i))
    for i in order[:count-sum(quotas)]:
        quotas[i] += 1
    used, colors = [0, 0, 0], []
    for step in range(count):
        i = max((i for i in range(3) if used[i] < quotas[i]),
                key=lambda i: ((step+1)*quotas[i]-used[i]*count, -i))
        colors.append(PearlColorSlot(i))
        used[i] += 1
    return tuple(colors)


class PearlGroupRegion(EdgeRegion):
    """包含整组珠体和字符投影的包围框中心活动区域。"""

    def __init__(self, world, half_size):
        x, y = half_size.x, half_size.y
        w, h, inner = world.width, world.height, world.inner
        self.outer = Bounds(x, y, w-x, h-y)
        self.hole = Bounds(inner.left-x, inner.top-y, inner.right+x, inner.bottom+y)
        self.boxes = (Bounds(x, y, w-x, self.hole.top),
                      Bounds(self.hole.right, y, w-x, h-y),
                      Bounds(x, self.hole.bottom, w-x, h-y),
                      Bounds(x, y, self.hole.left, h-y))


def group_follow_boxes(center, body_region, region, width, height, half_size):
    """整组包围框放进跟随矩形，且与身体共享走廊。"""
    x, y = width/2-half_size.x, height/2-half_size.y
    boxes = []
    for physical, safe in zip(body_region.boxes, region.boxes):
        if not physical.contains(center):
            continue
        l, r = max(safe.left, center.x-x), min(safe.right, center.x+x)
        t, b = max(safe.top, center.y-y), min(safe.bottom, center.y+y)
        if l <= r and t <= b:
            boxes.append(Bounds(l, t, r, b))
    return boxes
