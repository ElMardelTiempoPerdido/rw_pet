"""朋友？观察光的锥面光线和四帧光点，只在宿主仿真步更新随机状态"""
from dataclasses import dataclass
from math import cos, hypot, pi, radians, sin, sqrt, tan
from random import Random

from ..lens import Motion
from ....shared.geometry import Vec2


PIXEL_COLOR = '#ffb000'
PIXEL_OPACITY = .95
RAY_SIGNAL_RANGE = (.82, .94)  # 常驻信号完整度；越低局部断开越多，(1., 1.) 关闭额外缺损
RAY_LENGTHS = (.50, .66, 1., .59, .80)  # 五条母线的长度比例
RAY_START = 10.  # 避开脸盘，逻辑像素
ROTATION_TURNS_PER_SECOND = .055
SPARK_COUNT = 4  # 同时存在的槽位上限，空档期间不绘制
SPARK_LIFETIME = (.65, 1.35)  # 秒，四帧均分一次生命周期
SPARK_WAIT = (.18, .85)  # 消失后到下一次生成的等待范围
SPARK_DISTANCE = (.18, .95)  # 相对光束长度的深度范围
SPARK_FRAMES = (
    ((0, 0),),
    ((-1, 0), (1, 0), (0, -1), (0, 1)),
    ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1),
     (-2, 0), (2, 0), (0, -2), (0, 2)),
    ((-2, 0), (2, 0), (0, -2), (0, 2)),
)


def pixel_extent(length, root_radius, *, ray_half_angle, spark_half_angle):
    ray_far = length*max(RAY_LENGTHS)
    spark_far = length*SPARK_DISTANCE[1]
    return max(hypot(ray_far, root_radius+ray_far*tan(radians(ray_half_angle))),
               hypot(spark_far, root_radius+spark_far*tan(radians(spark_half_angle))))+3


@dataclass(slots=True)
class Spark:
    position: tuple[float, float, float]  # 归一化锥内位置，在本次生命内保持不变
    lifetime: float
    age: float = 0.
    previous_age: float = 0.

    def frame(self, alpha):
        age = self.previous_age+(self.age-self.previous_age)*alpha
        return min(3, int(max(0., age/self.lifetime)*4))


class FriendLightPixels:
    def __init__(self, seed):
        self.random = Random(seed ^ 0xF21E1D)
        self.noise_random = Random(seed ^ 0x51A1)  # 不改变原来的旋转及光点随机序列
        self.noise_offset = (seed & 255, (seed >> 8) & 255)
        self.rotation = Motion.at(self.random.random())
        self.reset()

    def reset(self):
        self.active = False
        self.signal = Motion.at(.5)
        self.tick = 0
        self.turn = self.previous_turn = 0.
        self.sparks = [None]*SPARK_COUNT
        self.waits = [0.]*SPARK_COUNT
        self.line_show = (0.,)*len(RAY_LENGTHS)

    def step(self, *, opening, visible, emitting, tick_rate):
        if not visible or opening <= 0:
            if self.active:
                self.reset()
            return
        if not self.active:
            self.active = True
            self.waits = [self.random.uniform(0., .6) for _ in self.sparks]
        dt = 1/tick_rate
        self.tick += 1
        self.previous_turn = self.turn
        self.turn += ROTATION_TURNS_PER_SECOND*dt
        # 与普通镜片相同的缓动随机旋转，叠加慢速环转以显示锥面关系
        self.rotation.step(self.random, 1/70, rotation=True)
        self.signal.step(self.noise_random, 1/18)
        self.line_show = tuple(self.random.random() for _ in RAY_LENGTHS)
        for i, spark in enumerate(self.sparks):
            if spark is not None:
                spark.previous_age = spark.age
                spark.age += dt
                if spark.age >= spark.lifetime:
                    self.sparks[i] = None
                    self.waits[i] = self.random.uniform(*SPARK_WAIT)
            elif emitting:
                self.waits[i] -= dt
                if self.waits[i] <= 0:
                    angle = self.random.uniform(0., 2*pi)
                    radius = sqrt(self.random.random())
                    position = (cos(angle)*radius, sin(angle)*radius,
                                self.random.uniform(*SPARK_DISTANCE))
                    self.sparks[i] = Spark(position, self.random.uniform(*SPARK_LIFETIME))

    def signal_strength(self, alpha):
        low, high = RAY_SIGNAL_RANGE
        return max(0., min(1., low+(high-low)*self.signal.sample(alpha)))

    def project(self, center, matrix, extension, length, root_radius, alpha, *,
                ray_half_angle, spark_half_angle):
        """只读投影；所有线沿锥面母线，光点在锥内随朝向变化，帧图案保持屏幕像素方向"""
        if not self.active:
            return (), ()
        ray_slope = tan(radians(ray_half_angle))
        spark_slope = tan(radians(spark_half_angle))
        turn = self.previous_turn+(self.turn-self.previous_turn)*alpha
        angle = (turn+self.rotation.sample(alpha))*2*pi
        cz, sz = cos(angle), sin(angle)

        def point(x, y, z):
            x, y = x*cz-y*sz, x*sz+y*cz
            return center+Vec2(matrix[0]*x+matrix[1]*y+matrix[2]*z,
                               matrix[3]*x+matrix[4]*y+matrix[5]*z)*extension

        lines = []
        for i, fraction in enumerate(RAY_LENGTHS):
            azimuth = i*2*pi/len(RAY_LENGTHS)
            ends = []
            for z in (min(RAY_START, length*fraction*.5), length*fraction):
                radius = root_radius+ray_slope*z
                ends.append(point(cos(azimuth)*radius, sin(azimuth)*radius, z))
            lines.append((ends[0], ends[1], PIXEL_OPACITY))
        sparks = []
        for spark in self.sparks:
            if spark is not None:
                x, y, distance = spark.position
                z = distance*length
                radius = root_radius+spark_slope*z
                sparks.append((point(x*radius, y*radius, z), spark.frame(alpha)))
        return tuple(lines), tuple(sparks)
