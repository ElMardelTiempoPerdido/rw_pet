"""人偶的近距离鼠标注视、躲避和摸摸反应"""
from ...interaction.config import InteractionConfig
from ...interaction.hover_attention import HoverAttention
from ...interaction.petting import PettingMotion
from .mouse_avoidance import OracleMouseAvoidance
from ..mouse_avoidance_config import MouseAvoidanceConfig


class OracleMouseReaction:
    FIELDS = ('hover_radius', 'hover_dwell_seconds', 'hover_probability', 'hover_open_probability')

    PETTING_FIELDS = ('petting_enabled', 'petting_seconds', 'petting_grace_seconds')

    def __init__(self, config=InteractionConfig(), *, avoidance_config=MouseAvoidanceConfig()):
        self.config = config
        self.attention = HoverAttention(*(getattr(config, name) for name in self.FIELDS))
        self.avoidance = OracleMouseAvoidance(avoidance_config)
        self.petting = PettingMotion(config.petting_seconds, config.petting_grace_seconds)
        self.pointer = self.motion_pointer = None
        self.puppet_hit = self.pointer_pressed = False

    @property
    def active(self):
        return self.petting.busy or self.attention.active or self.avoidance.engaged

    def configure(self, scene, config):
        attention_changed = any(getattr(self.config, name) != getattr(config, name) for name in self.FIELDS)
        avoidance_changed = self.avoidance.config != scene.config.mouse_avoidance
        petting_changed = any(getattr(self.config, name) != getattr(config, name) for name in self.PETTING_FIELDS)
        if attention_changed or avoidance_changed or petting_changed:
            self.cancel(scene)
        if attention_changed:
            rng = self.attention.random.getstate()
            self.attention = HoverAttention(*(getattr(config, name) for name in self.FIELDS))
            self.attention.random.setstate(rng)
        if avoidance_changed:
            rng = self.avoidance.random.getstate()
            self.avoidance = OracleMouseAvoidance(scene.config.mouse_avoidance)
            self.avoidance.random.setstate(rng)
        if petting_changed:
            self.petting = PettingMotion(config.petting_seconds, config.petting_grace_seconds)
        if not config.hover_avoidance_enabled:
            self.avoidance.cancel(scene)
        self.config = config

    def cancel(self, scene):
        if self.active:
            scene.eyes.attention_target = None
        self.avoidance.cancel(scene)
        self.attention.cancel()
        self.petting.cancel()
        scene.eyes.forced_closed = False
        self.pointer = self.motion_pointer = None
        self.puppet_hit = self.pointer_pressed = False

    def sample_input(self, pointer, *, inside=False, motion_pointer=None, pressed=False):
        self.pointer, self.motion_pointer = pointer, motion_pointer
        self.puppet_hit, self.pointer_pressed = inside, pressed

    @property
    def wants_pointer(self):
        return self.attention.probability > 0 or self.config.petting_enabled

    def step(self, scene):
        if scene.drag.controlling or self.pointer_pressed:
            self.cancel(scene)
            return
        was_petting = self.petting.busy
        self.petting.step(1/scene.TICK_RATE, self.motion_pointer if self.motion_pointer is not None else self.pointer,
                          inside=self.puppet_hit, enabled=self.config.petting_enabled)
        scene.eyes.forced_closed = self.petting.active and scene.config.character.has_eyes
        if self.petting.busy:
            if not was_petting:
                self.attention.cancel()
                scene.window_reaction.cancel(scene)
            # 仅收回本轮躲避，不取消自主路线、读珠或漫游
            self.avoidance.step(scene, active=False, pointer=self.pointer, enabled=False)
            return
        if was_petting:
            self.attention.cancel()  # 结束后重新等待，不沿用即将触发的关注/躲避计时
        # 持续躲避在短暂越界期间沿用本轮头眼意愿，不重新抽签或打断注视
        started = (self.attention.step(1/scene.TICK_RATE, self.pointer, scene.body.chunks[0].position)
                   if not self.avoidance.engaged else False)
        if started:
            scene.window_reaction.cancel(scene)
        self.avoidance.step(scene, active=self.attention.active, pointer=self.pointer,
                            enabled=self.config.hover_avoidance_enabled)
        if self.active:
            scene.eyes.attention_target = float(self.attention.opened) if scene.config.character.has_eyes else None
        # 不活跃时，window_reaction.step 已恢复窗口或基础观察的眼睛意愿。

    def desired_look(self, scene, ordinary):
        if self.petting.active:
            return scene.body.direction * -.4
        if self.petting.busy or not self.active:
            return ordinary
        target = self.avoidance.gaze_target if self.avoidance.engaged else self.attention.target
        delta = (target-scene.body.chunks[0].position)*.01
        return delta*min(1., 1/max(delta.length(), 1e-9))
