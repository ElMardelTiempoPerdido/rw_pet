"""Bell 的近距离鼠标注视，以及滞后的轻微躲避反应"""
from ...interaction.config import InteractionConfig
from ...interaction.hover_attention import HoverAttention
from .mouse_avoidance import OracleMouseAvoidance


class OracleMouseReaction:
    FIELDS = ('hover_radius', 'hover_dwell_seconds', 'hover_probability', 'hover_open_probability')

    def __init__(self, config=InteractionConfig()):
        self.config = config
        self.attention = HoverAttention(*(getattr(config, name) for name in self.FIELDS))
        self.avoidance = OracleMouseAvoidance()
        self.pointer = None

    @property
    def active(self):
        return self.attention.active or self.avoidance.engaged

    def configure(self, scene, config):
        if any(getattr(self.config, name) != getattr(config, name) for name in self.FIELDS):
            self.cancel(scene)
            rng = self.attention.random.getstate()
            self.attention = HoverAttention(*(getattr(config, name) for name in self.FIELDS))
            self.attention.random.setstate(rng)
        if not config.hover_avoidance_enabled:
            self.avoidance.cancel(scene)
        self.config = config

    def cancel(self, scene):
        if self.active:
            scene.eyes.attention_target = None
        self.avoidance.cancel(scene)
        self.attention.cancel()
        self.pointer = None

    def step(self, scene):
        if scene.drag.controlling:
            self.cancel(scene)
            return
        # 持续躲避在短暂越界期间沿用本轮头眼意愿，不重新抽签或打断注视
        started = (self.attention.step(1/scene.TICK_RATE, self.pointer, scene.body.chunks[0].position)
                   if not self.avoidance.engaged else False)
        if started:
            scene.window_reaction.cancel(scene)
        self.avoidance.step(scene, active=self.attention.active, pointer=self.pointer,
                            enabled=self.config.hover_avoidance_enabled)
        if self.active:
            scene.eyes.attention_target = float(self.attention.opened)
        # 不活跃时，window_reaction.step 已恢复窗口或基础观察的眼睛意愿。

    def desired_look(self, scene, ordinary):
        if not self.active:
            return ordinary
        target = self.avoidance.gaze_target if self.avoidance.engaged else self.attention.target
        delta = (target-scene.body.chunks[0].position)*.01
        return delta*min(1., 1/max(delta.length(), 1e-9))
