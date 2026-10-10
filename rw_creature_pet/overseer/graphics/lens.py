"""持续观察及眼前线框镜片；只在仿真步抽签，投影/绘制不消耗随机数。

参考 OverseerAI.LensUpdate 与 OverseerGraphics.HologramMatrix：双层多边形镜筒、
外围三角片、两组旋转和独立形变。桌面触发改为明确时间尺度的随机事件。
"""
from dataclasses import dataclass
from math import cos, pi, sin
from random import Random

from ...shared.geometry import Vec2


def lerp(a, b, t):
    return a+(b-a)*t


@dataclass(slots=True)
class Motion:
    value: float
    previous: float
    start: float
    goal: float
    progress: float = 1.
    speed: float = 0.

    @classmethod
    def at(cls, value):
        return cls(value, value, value, value)

    def step(self, rng, probability, *, rotation=False):
        self.previous = self.value
        if self.progress >= 1 and rng.random() < probability:
            self.start = self.value
            self.goal = (self.value+rng.uniform(-.8, .8)*rng.random()**2 if rotation
                         else rng.random())
            self.progress = 0.
            self.speed = .02/max(.02, abs(self.goal-self.start))
        self.progress = min(1., self.progress+self.speed)
        self.value = lerp(self.start, self.goal, self.progress**2*(3-2*self.progress))

    def sample(self, alpha):
        return lerp(self.previous, self.value, alpha)


class ObservationLens:
    OPEN_TICKS = 30  # 原版每个 40 Hz tick 增减 1/30，约 0.75 秒。
    DURATION = (3., 7.)  # 桌面单次持续观察；不扩大用户设置表单。
    MAX_EXTENT = 42.  # 相对眼部的保守半径，包含线宽与收拢偏移。

    def __init__(self, config, seed):
        self.random = Random(seed ^ 0x1E115)  # 不影响出现、换位或触须的随机序列。
        self.visual_random = Random(seed ^ 0xA117)
        self.flicker_random = Random(seed ^ 0xF11C)  # 闪断不改变观察抽签或原有形变序列
        self.noise_offset = (seed & 255, (seed >> 8) & 255)
        self.shapes, count = self._shape(Random(seed ^ 0x501))
        self.line_count = sum(len(points) if closed else len(points)-1
                              for _, _, points, _, closed in self.shapes)
        self.rotations = [Motion.at(self.visual_random.random()) for _ in range(2)]
        self.movements = [Motion.at(self.visual_random.random()) for _ in range(count+1)]
        self.check_count = self.observation_count = 0
        self.reset(config)

    def reset(self, config):
        self.config = config
        self.up = self.previous_up = self.remaining = 0.
        self.check_remaining = config.observation_interval
        self.effect_tick = 0
        self.line_noise = ((0., 1., 1., 1.),)*self.line_count

    def configure(self, config):
        if config.observation_interval != self.config.observation_interval:
            self.check_remaining = config.observation_interval
        self.config = config
        if config.observation_probability == 0:
            self.remaining = 0.

    def opening(self, alpha=1.):
        return lerp(self.previous_up, self.up, alpha)

    def step(self, *, eligible, visible, tick_rate, animate_hologram=True, duration=None):
        self.previous_up = self.up
        dt = 1/tick_rate
        if not eligible or self.config.observation_probability == 0:
            self.remaining = 0.
            self.check_remaining = self.config.observation_interval
        elif self.remaining > 0:
            self.remaining = max(0., self.remaining-dt)
        elif self.up == 0 and self.previous_up == 0:
            self.check_remaining = max(0., self.check_remaining-dt)
            if self.check_remaining < 1e-9:
                self.check_remaining = self.config.observation_interval
                self.check_count += 1
                if self.random.random() < self.config.observation_probability:
                    self.remaining = self.random.uniform(*(self.DURATION if duration is None else duration))
                    self.observation_count += 1
        self.up = (min(1., self.up+1/self.OPEN_TICKS) if self.remaining > 0
                   else max(0., self.up-1/self.OPEN_TICKS))
        if self.up < 1e-9:
            self.up = 0.
        if not visible:
            self.up = self.previous_up = 0.
            return
        # 朋友？只复用观察时序，不计算未显示的镜片噪声及几何动画
        if animate_hologram and max(self.up, self.previous_up) > 0:
            self.effect_tick += 1
            self.line_noise = tuple(tuple(self.flicker_random.random() for _ in range(4))
                                    for _ in range(self.line_count))
            for i, motion in enumerate(self.rotations):
                motion.step(self.visual_random, 1/(40 if i == 0 else 70), rotation=True)
            for motion in self.movements:
                motion.step(self.visual_random, .05)

    @staticmethod
    def _shape(rng):
        """固定个体形状：镜筒和三角片使用原版量级，避免逐帧生成顶点。"""
        sides, petals = rng.randint(3, 6), rng.randint(3, 8)
        radii = (rng.uniform(4, 8), rng.uniform(3, 5))
        depths = (rng.uniform(12, 20), rng.uniform(23, 32))
        rings = [tuple((cos(i*2*pi/sides)*r, sin(i*2*pi/sides)*r, z)
                       for i in range(sides)) for r, z in zip(radii, depths)]
        alternate = [tuple((x*.65, y*.65, z+3) for x, y, z in ring) for ring in rings]
        # (旋转组, 形变通道, 原始顶点, 另一姿态顶点, 闭合)
        shapes = [(0, 0, ring, alt, True) for ring, alt in zip(rings, alternate)]
        shapes += [(0, 0, (rings[0][i], rings[1][i]),
                    (alternate[0][i], alternate[1][i]), False) for i in range(sides)]
        for i in range(petals):
            angle = i*2*pi/petals
            width = pi/petals*rng.uniform(.3, .6)
            inner, outer = rng.uniform(9, 11), rng.uniform(15, 18)
            z0, z1 = rng.uniform(7, 16), rng.uniform(17, 25)
            points = tuple((cos(a)*r, sin(a)*r, z) for a, r, z in
                           ((angle-width, inner, z0), (angle+width, inner, z0), (angle, outer, z1)))
            alt = tuple((x*.8, y*.8, z+5) for x, y, z in points)
            shapes.append((1, i+1, points, alt, True))
        return tuple(shapes), petals

    def segments(self, center, gaze, extension, size, alpha=1.):
        """OnPlanePos 的视线倾斜和局部旋转；返回只读的二维线段/透明度。"""
        opening = self.opening(alpha)
        strength = min(extension, opening)
        if strength <= 0:
            return ()
        # 原版收回时沿深度拉长；桌面压拢，保持局部窗口的有限绘制范围。
        origin = center+gaze*(30*(1-extension))
        scale = (.75+.25*size)*extension
        cx, sx, cy, sy = cos(-gaze.y), sin(-gaze.y), cos(gaze.x), sin(gaze.x)
        rotations = [(cos(m.sample(alpha)*2*pi), sin(m.sample(alpha)*2*pi)) for m in self.rotations]
        result = []
        line_index = 0
        for group, movement, points, alternate, closed in self.shapes:
            morph = self.movements[movement].sample(alpha)
            cz, sz = rotations[group]
            projected = []
            for a, b in zip(points, alternate):
                x, y, z = (lerp(v, w, morph)*scale for v, w in zip(a, b))
                x, y = x*cz-y*sz, x*sz+y*cz
                y, z = y*cx-z*sx, y*sx+z*cx
                x = z*sy+x*cy
                projected.append(origin+Vec2(x, y))
            pairs = zip(projected, projected[1:]+projected[:1] if closed else projected[1:])
            for a, b in pairs:
                show, snap, start, end = self.line_noise[line_index]
                line_index += 1  # 隐藏的线也保留编号，不把随机状态转交给下一条
                if show >= strength:
                    continue
                if snap < .5:
                    if start >= strength:
                        a = origin
                    if end >= strength:
                        b = origin
                # alpha 作为信号完整度供遮罩使用，保留下来的线维持亮度
                result.append((a, b, .85))
        return tuple(result)
