"""悬空触手各自选择探寻目标和力度，固定 40 Hz，仅输出连续的施力参数"""
from dataclasses import dataclass
from random import Random


@dataclass(frozen=True)
class SearchPose:
    angle: float = 0.
    reach: float = .64
    strength: float = 0.


class FreeTipSearch:
    ANGLE = .50  # 围绕朝边方向的最大偏转，单位为弧度
    REACH = (.45, .80)  # 相对自然长度，不使用拉伸后的长度
    STRENGTH = (.65, 1.)  # 乘在既有追踪力及其上限之外
    RELAX_CHANCE = .35
    RELAX_REACH = (.45, .60)
    RELAX_STRENGTH = (.12, .30)
    TRANSITION_TICKS = (36, 88)
    HOLD_TICKS = (8, 34)
    RELAX_TRANSITION_TICKS = (32, 68)
    RELAX_HOLD_TICKS = (16, 48)

    def __init__(self, seed=None):
        # 不共用全局随机流；测试可指定种子，桌面实例各自初始化
        self.random = Random(seed)
        self.value = SearchPose()
        self.start = self.target = self.value
        self.tick = self.duration = self.hold = 0

    def begin(self):
        # 松开时从零牵引渐入，保留随机流，使再次松开不重复上一次开场
        self.value = SearchPose()
        self._choose()

    def _choose(self):
        relaxed = self.random.random() < self.RELAX_CHANCE
        self.start = self.value
        self.target = SearchPose(
            self.random.uniform(-self.ANGLE, self.ANGLE),
            self.random.uniform(*(self.RELAX_REACH if relaxed else self.REACH)),
            self.random.uniform(*(self.RELAX_STRENGTH if relaxed else self.STRENGTH)))
        self.duration = self.random.randint(*(
            self.RELAX_TRANSITION_TICKS if relaxed else self.TRANSITION_TICKS))
        self.hold = self.random.randint(*(self.RELAX_HOLD_TICKS if relaxed else self.HOLD_TICKS))
        self.tick = 0

    def step(self):
        if self.tick >= self.duration+self.hold:
            self._choose()
        self.tick += 1
        t = min(1., self.tick/self.duration)
        # 五次缓动让目标切换和短暂停留的两端速度、加速度均连续
        eased = t*t*t*(10.+t*(-15.+6.*t))
        a, b = self.start, self.target
        self.value = SearchPose(a.angle+(b.angle-a.angle)*eased,
                                a.reach+(b.reach-a.reach)*eased,
                                a.strength+(b.strength-a.strength)*eased)
        return self.value


class WallProbe:
    """独立计时的短暂朝墙探查，覆盖普通回摆参数后逐渐退回"""
    FIRST_WAIT_TICKS = (100, 420)
    WAIT_TICKS = (180, 600)
    DURATION_TICKS = (500, 1100)
    RETARGET_TICKS = (12, 30)
    ANGLE = .24  # 围绕朝墙方向更集中地试探附近位置
    REACH = (.86, .96)
    STRENGTH = (1.15, 1.55)
    TARGET_RESPONSE = .16
    ENTER_RESPONSE = .18
    EXIT_RESPONSE = .09  # 比伸出更缓慢地放松，让惯性带出回摆

    def __init__(self, seed=None):
        # 与普通回摆使用不同的随机流，调节该动作不改变普通探寻序列
        self.random = Random(None if seed is None else f'wall-probe:{seed}')
        self.wait = self.remaining = self.retarget = 0
        self.weight = 0.
        self.pose = self.target = self.value = SearchPose()

    def begin(self):
        self.wait = self.random.randint(*self.FIRST_WAIT_TICKS)
        self.remaining = self.retarget = 0
        self.weight = 0.
        self.pose = self.target = self.value = SearchPose()

    def _pick_target(self):
        self.target = SearchPose(self.random.uniform(-self.ANGLE, self.ANGLE),
                                 self.random.uniform(*self.REACH),
                                 self.random.uniform(*self.STRENGTH))
        self.retarget = self.random.randint(*self.RETARGET_TICKS)

    @staticmethod
    def _blend(a, b, weight):
        return SearchPose(a.angle+(b.angle-a.angle)*weight,
                          a.reach+(b.reach-a.reach)*weight,
                          a.strength+(b.strength-a.strength)*weight)

    def step(self, base):
        if self.remaining == 0:
            self.wait -= 1
            if self.wait <= 0:
                self.remaining = self.random.randint(*self.DURATION_TICKS)
                self.pose = base
                self._pick_target()
        probing = self.remaining > 0
        if probing:
            self.retarget -= 1
            if self.retarget <= 0:
                self._pick_target()
            # 不等上一段完整缓动结束即可再次换探查点，避免固定的伸缩节拍
            self.pose = self._blend(self.pose, self.target, self.TARGET_RESPONSE)
            self.remaining -= 1
            if self.remaining == 0:
                self.wait = self.random.randint(*self.WAIT_TICKS)
        response = self.ENTER_RESPONSE if probing else self.EXIT_RESPONSE
        self.weight += (float(probing)-self.weight)*response
        if not probing and self.weight < .001:
            self.weight = 0.
        self.value = self._blend(base, self.pose, self.weight)
        return self.value
