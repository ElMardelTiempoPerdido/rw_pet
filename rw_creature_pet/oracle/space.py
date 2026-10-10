"""场景空间评估：设置建议和桌面缩放保护共用，不依赖 Qt"""
from dataclasses import dataclass
from math import ceil

EDGE_FRACTION_MIN = .20
EDGE_FRACTION_MAX = .499
ARM_SCALE_MAX = .75
# 最小整体尺寸容纳身体、底座和珍珠；活动带还须通过下面的独立检查
MIN_WORLD_SIDE = 160.
MIN_CLEARANCE = 1.
COMFORT_CLEARANCE = 32.
ALL_EDGES = ('top', 'right', 'bottom', 'left')


def body_margin(arm_scale):
    return max(36., 18.+30.*arm_scale)


def minimum_world_size(arm_scale, fraction, edges=ALL_EDGES):
    depth = (2*body_margin(arm_scale)+MIN_CLEARANCE)/fraction
    # 珍珠布局在两轴预留 39px 的字符/珠体空间，即使只开启一条边也不能反转
    # 另保留最长臂段及关节的过角空间；只检查活动带深度会放行短边约 200px
    # 的场景，实际绕角可能短暂无解。该保守下限随机械臂缩放，不固定成 640×480
    span = max(MIN_WORLD_SIDE, 2*body_margin(arm_scale)+300*arm_scale+16., 40./fraction)
    return (max(span, depth if any(e in edges for e in ('left', 'right')) else 0.),
            max(span, depth if any(e in edges for e in ('top', 'bottom')) else 0.))


@dataclass(frozen=True, slots=True)
class SpaceAssessment:
    width: float
    height: float
    arm_scale: float
    fraction: float
    edges: tuple[str, ...] = ALL_EDGES

    @property
    def edge_span(self):
        spans = [self.height if e in ('top', 'bottom') else self.width for e in self.edges]
        return min(spans) if spans else 0.

    @property
    def clearance(self):
        return self.edge_span*self.fraction-2*body_margin(self.arm_scale)

    @property
    def valid(self):
        w, h = minimum_world_size(self.arm_scale, self.fraction, self.edges)
        return bool(self.edges) and self.width >= w-1e-7 and self.height >= h-1e-7

    @property
    def baseline_fits(self):
        return SpaceAssessment(self.width, self.height, ARM_SCALE_MAX, EDGE_FRACTION_MIN, self.edges).valid

    @property
    def recommendation(self):
        """优先保留机械臂和更宽的已有活动带；必要时逐档减小机械臂"""
        if min(self.width, self.height) < MIN_WORLD_SIDE or self.edge_span <= 0:
            return None
        arms = [self.arm_scale, *(a/100 for a in range(75, 34, -5) if a/100 < self.arm_scale)]
        for arm in arms:
            needed = (2*body_margin(arm)+COMFORT_CLEARANCE)/self.edge_span
            if needed > EDGE_FRACTION_MAX+1e-9:
                continue
            band = max(self.fraction, EDGE_FRACTION_MIN,
                       min(EDGE_FRACTION_MAX, ceil((needed-1e-10)*20)/20))
            if SpaceAssessment(self.width, self.height, arm, band, self.edges).valid:
                return arm, band
        return None
