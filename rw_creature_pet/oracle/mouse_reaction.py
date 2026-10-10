"""Bell 的近距离鼠标注视；只临时覆盖头眼，不接管身体导航或珍珠。"""
from ..interaction.config import InteractionConfig
from ..interaction.hover_attention import HoverAttention


class OracleMouseReaction:
    FIELDS = ('hover_radius', 'hover_dwell_seconds', 'hover_probability', 'hover_open_probability')

    def __init__(self, config=InteractionConfig()):
        self.config = config
        self.attention = HoverAttention(*(getattr(config, name) for name in self.FIELDS))
        self.pointer = None

    @property
    def active(self):
        return self.attention.active

    def configure(self, scene, config):
        if any(getattr(self.config, name) != getattr(config, name) for name in self.FIELDS):
            self.cancel(scene)
            rng = self.attention.random.getstate()
            self.attention = HoverAttention(*(getattr(config, name) for name in self.FIELDS))
            self.attention.random.setstate(rng)
        self.config = config

    def cancel(self, scene):
        if self.active:
            scene.eyes.attention_target = None
        self.attention.cancel()
        self.pointer = None

    def step(self, scene):
        if scene.drag.controlling:
            self.cancel(scene)
            return
        started = self.attention.step(1/scene.TICK_RATE, self.pointer, scene.body.chunks[0].position)
        if started:
            scene.window_reaction.cancel(scene)
        if self.active:
            scene.eyes.attention_target = float(self.attention.opened)
        # 不活跃时，window_reaction.step 已恢复窗口或基础观察的眼睛意愿。

    def desired_look(self, scene, ordinary):
        if not self.active:
            return ordinary
        delta = (self.attention.target-scene.body.chunks[0].position)*.01
        return delta*min(1., 1/max(delta.length(), 1e-9))
