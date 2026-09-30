"""Qt 无关的事件调度；只在宿主的固定仿真步中计时，不读取墙钟。"""
from dataclasses import dataclass, replace
from enum import Enum
from math import sqrt
from random import Random

from ..shared.geometry import Bounds, Vec2
from .model import Anchor, Edge


@dataclass(frozen=True, slots=True)
class SpawnContext:
    bounds: Bounds
    edges: tuple[str, ...] = tuple(edge.value for edge in Edge)
    mouse: Vec2 | None = None
    obstacles: tuple[Bounds, ...] = ()  # 人偶外形，不包括线缆、机械臂和光环。
    puppet: Vec2 | None = None  # 人偶中心，活动期间只需一次粗略距离检测。


class EventPhase(str, Enum):
    DISABLED = 'disabled'
    WAITING = 'waiting'
    ACTIVE = 'active'
    EXITING = 'exiting'
    COOLDOWN = 'cooldown'
    PREVIEW = 'preview'


def subtract_interval(intervals, low, high):
    result = []
    for start, end in intervals:
        if high <= start or low >= end:
            result.append((start, end))
        else:
            if low > start:
                result.append((start, low))
            if high < end:
                result.append((high, end))
    return result


class OverseerEvents:
    def __init__(self, model, *, seed=None):
        self.model = model
        self.random = Random(seed)  # 与外观随机数隔离；休眠期间不抽签。
        self.check_count = self.event_count = 0
        self.relocation_count = 0
        self.last_result = ''
        self.reset()

    @property
    def config(self):
        return self.model.config

    def reset(self):
        self.model.clear()
        self._relocation_checked = False
        self.phase = EventPhase.WAITING if self.config.enabled else EventPhase.DISABLED
        self.check_remaining = self.config.check_interval
        self.remaining = self.cooldown_remaining = 0.

    def configure(self, config):
        old = self.config
        self.model.config = config
        self.model.revision += 1
        if old.enabled != config.enabled or old.check_interval != config.check_interval:
            self.check_remaining = config.check_interval
        if not config.enabled:
            if old.enabled and self.phase == EventPhase.ACTIVE:
                self.finish()
            elif self.phase in (EventPhase.WAITING, EventPhase.COOLDOWN):
                self.phase = EventPhase.DISABLED
                self.cooldown_remaining = 0.
        elif self.phase == EventPhase.DISABLED:
            self.phase = EventPhase.WAITING
        # 已抽取的本次时长/冷却不随设置滑动；新范围在下一次抽取时使用。

    def preview(self, bounds, anchor):
        self.model.show(bounds, anchor)
        self._relocation_checked = False
        self.phase = EventPhase.PREVIEW
        self.remaining = self.cooldown_remaining = 0.

    def clear(self):
        """调试清除立即隐藏；重新等待完整检查间隔，不立刻补发事件。"""
        self.reset()

    def finish(self):
        if self.phase in (EventPhase.ACTIVE, EventPhase.PREVIEW):
            self.remaining = 0.
            self.phase = EventPhase.EXITING
            self.model.request_withdraw()

    def cancel(self):
        """宿主几何失效时撤掉旧事件；只抽取一次冷却，不补发新事件。"""
        if self.model.active:
            self.remaining = 0.
            self._complete()

    def _complete(self):
        self.model.clear()
        self.last_result = '事件已退场'
        self.phase = EventPhase.COOLDOWN if self.config.enabled else EventPhase.DISABLED
        self.cooldown_remaining = (self.random.uniform(self.config.cooldown_min, self.config.cooldown_max)
                                   if self.config.enabled else 0.)
        self.check_remaining = self.config.check_interval

    def emerge(self):
        if self.phase in (EventPhase.ACTIVE, EventPhase.PREVIEW):
            self.model.request_emerge()

    def skip_cooldown(self):
        if self.phase == EventPhase.COOLDOWN:
            self.cooldown_remaining = 0.
            self.phase = EventPhase.WAITING
            self.check_remaining = self.config.check_interval

    def choose_anchor(self, context, *, avoid_root=None):
        """减去四角、鼠标和人偶占用区间，按剩余边缘长度抽取位置。"""
        b = context.bounds
        extent = self.model.reach+self.model.filament_length+12
        clearance = max(self.config.reemerge_distance, extent+12)
        candidates = []
        for edge in dict.fromkeys(Edge(value) for value in context.edges):
            horizontal = edge in (Edge.TOP, Edge.BOTTOM)
            origin = b.left if horizontal else b.top
            length = b.right-b.left if horizontal else b.bottom-b.top
            if length <= 2*extent:
                continue  # 不压缩四角余量来强行放下一只监视者。
            fixed = {Edge.TOP: b.top, Edge.RIGHT: b.right, Edge.BOTTOM: b.bottom, Edge.LEFT: b.left}[edge]
            intervals = [(origin+extent, origin+length-extent)]
            for box in context.obstacles:
                low, high = (box.top, box.bottom) if horizontal else (box.left, box.right)
                if low-extent <= fixed <= high+extent:
                    start, end = (box.left, box.right) if horizontal else (box.top, box.bottom)
                    intervals = subtract_interval(intervals, start-extent, end+extent)
            for position, radius in ((context.mouse, clearance),
                                     (context.puppet, max(self.config.puppet_reemerge_distance, extent+12)),
                                     (avoid_root, max(2*extent, clearance))):
                if position is None:
                    continue
                cross = position.y if horizontal else position.x
                along = position.x if horizontal else position.y
                distance = abs(cross-fixed)
                if distance < radius:
                    along_radius = sqrt(radius**2-distance**2)
                    intervals = subtract_interval(intervals, along-along_radius, along+along_radius)
            candidates.extend((edge, lo, hi, origin, length) for lo, hi in intervals if hi-lo > 1e-6)
        if not candidates:
            return None
        edge, low, high, origin, length = self.random.choices(
            candidates, weights=[hi-lo for _, lo, hi, _, _ in candidates])[0]
        return Anchor(edge, (self.random.uniform(low, high)-origin)/length)

    def start(self, context):
        """调试直接触发可绕过开关、抽签和冷却，仍遵守位置安全限制。"""
        if self.phase in (EventPhase.ACTIVE, EventPhase.EXITING):
            self.last_result = '已有事件，请先完成退场'
            return False
        anchor = self.choose_anchor(context)
        if anchor is None:
            self.last_result = '没有安全的边缘位置，本次跳过'
            return False
        self.model.show(context.bounds, anchor)
        self._relocation_checked = False
        self.remaining = self.random.uniform(self.config.duration_min, self.config.duration_max)
        self.cooldown_remaining = 0.
        self.phase = EventPhase.ACTIVE
        self.event_count += 1
        self.last_result = '已开始事件'
        return True

    def check(self, context_factory):
        if not self.config.enabled or self.phase != EventPhase.WAITING:
            return False
        self.check_remaining = self.config.check_interval
        self.check_count += 1
        if self.random.random() >= self.config.appearance_probability:
            self.last_result = '本次未抽中'
            return False
        return self.start(context_factory())

    def _relocate_if_hidden(self, context_factory, threat, puppet):
        model = self.model
        if not model.scared or not model.wants_out:
            self._relocation_checked = False
            return
        # 预览锁定用户选的位置；手动保持缩回和到期退场也不触发换位。
        # 连插值末帧都已不可见时才改变根部，避免残影或跨屏拉伸。
        if self.phase != EventPhase.ACTIVE or model.visible or self._relocation_checked:
            return
        self._relocation_checked = True
        if self.random.random() >= self.config.relocation_probability:
            self.last_result = '避让后留在原位，等待安全'
            return
        context = replace(context_factory(), mouse=threat, puppet=puppet)
        anchor = self.choose_anchor(context, avoid_root=model.root)
        if anchor is None:
            self.last_result = '没有其他安全位置，留在原位等待'
            return  # 本次避让不逐帧重试，直到安全后再次遇险才重新抽签。
        rng, time = model.random, model.time
        model.show(context.bounds, anchor)
        model.random, model.time = rng, time
        model.scared = True  # 新位置同样连续安全 safe_delay 后才探出。
        self.relocation_count += 1
        self.last_result = '已在墙内换位，等待安全后探出'

    def step(self, target=None, *, threat=None, puppet=None, context_factory):
        dt = 1/self.model.TICK_RATE
        if self.phase == EventPhase.ACTIVE:
            self.remaining = max(0., self.remaining-dt)
            if self.remaining < 1e-9:
                self.finish()
        elif self.phase == EventPhase.COOLDOWN:
            self.cooldown_remaining = max(0., self.cooldown_remaining-dt)
            if self.cooldown_remaining < 1e-9:
                self.phase = EventPhase.WAITING if self.config.enabled else EventPhase.DISABLED
                self.check_remaining = self.config.check_interval
        elif self.phase == EventPhase.WAITING:
            self.check_remaining = max(0., self.check_remaining-dt)
            if self.check_remaining < 1e-9:
                self.check(context_factory)
        if self.phase == EventPhase.EXITING:
            self.model.request_withdraw()  # 到期是终止，不会因为鼠标离开或探出命令复活。
        if self.model.active:
            self.model.step(target, threat=threat, puppet=puppet)
            self._relocate_if_hidden(context_factory, threat, puppet)
        if self.phase == EventPhase.EXITING and not self.model.visible:
            self._complete()
