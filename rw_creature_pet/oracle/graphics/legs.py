"""悬浮人偶的腿形：分开的腿根、小幅膝弯和独立于长度的粗细"""
from dataclasses import dataclass
from math import hypot

from ...shared.geometry import Vec2


@dataclass(frozen=True, slots=True)
class LegShape:
    # 长度指自然姿态沿身体轴从腿根至脚中心的距离，不包含脚的半径
    length: float
    ROOT_HALF = 2.5
    FOOT_HALF = 4.
    ROOT_WIDTH = 2.3  # 半宽
    FOOT_WIDTH = 2.3
    FOOT_TIP = 2.  # 沿脚端方向延伸，保留原来 4px 脚贴图的末端范围
    FOOT_CORNER_RADIUS = 2

    @property
    def reach(self):
        # 两段完全展开时的真实可达距离，与自然姿态使用同一组段长
        bend = min(.8, self.length*.08)
        spread = (self.FOOT_HALF-self.ROOT_HALF)*.5
        return hypot(self.length*.5, spread+bend)+hypot(self.length*.5, spread-bend)

    def root(self, lower, direction, sign):
        side = Vec2(-direction.y, direction.x)
        return lower+side*(sign*self.ROOT_HALF)

    def goal(self, lower, direction, sign):
        side = Vec2(-direction.y, direction.x)
        return lower+side*(sign*self.FOOT_HALF)-direction*self.length

    def rest_knee(self, lower, direction, sign):
        root = self.root(lower, direction, sign)
        foot = self.goal(lower, direction, sign)
        side = Vec2(-direction.y, direction.x)
        # 长腿仍只轻微弯曲，不按长度放大成向两侧拱起的膝盖
        return root.lerp(foot, .5)+side*(sign*min(.8, self.length*.08))

    def curves(self, lower, direction, sign, knee, foot):
        root = self.root(lower, direction, sign)
        upper, lower_leg = knee-root, foot-knee
        a, b = max(1e-9, upper.length()), max(1e-9, lower_leg.length())
        tangent = upper*(1/a)+lower_leg*(1/b)
        tangent *= min(a, b)*.18/max(1e-9, tangent.length())
        # 两条曲线经过真实膝节点，接头共用切线，摆腿时不产生尖折或脱节
        return ((root, root+upper*(1/3), knee-tangent, knee),
                (knee, knee+tangent, foot-lower_leg*(1/3), foot))
