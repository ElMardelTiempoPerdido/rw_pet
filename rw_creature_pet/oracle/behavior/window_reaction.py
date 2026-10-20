"""Bell 的临时窗口注视；叠加在基础视线之上，不接管移动或珍珠任务。"""
from ...interaction.window_attention import WindowAttention
from ...shared.geometry import Vec2


class OracleWindowReaction:
    PROBABILITY = .35
    OPEN_PROBABILITY = .15
    DURATION = (5., 20.)

    def __init__(self):
        self.attention = WindowAttention(self.PROBABILITY, self.OPEN_PROBABILITY, self.DURATION)
        self.returning = False
        self.saved_look = Vec2()

    @property
    def busy(self):
        return self.attention.active or self.returning

    @staticmethod
    def allowed(scene):
        return not scene.drag.controlling and not scene.mouse_reaction.active

    def notice(self, scene, identity, target, *, changed, enabled=True):
        if not enabled or not self.allowed(scene):
            self.cancel(scene)
            return
        busy, active = self.busy, self.attention.active
        started = self.attention.notice(identity, target, changed=changed)
        if started:
            if not busy:
                self.saved_look = scene.look_direction
            self.returning = False
        elif active and not self.attention.active:
            self.returning = True

    def cancel(self, scene):
        self.attention.cancel()
        self.returning = False
        scene.eyes.attention_target = None

    def step(self, scene):
        if not self.allowed(scene):
            self.cancel(scene)
            return
        active = self.attention.active
        self.attention.step(1/40)
        if active and not self.attention.active:
            self.returning = True
        scene.eyes.attention_target = (float(self.attention.opened)
                                       if self.attention.active and scene.config.character.has_eyes else None)

    def desired_look(self, scene, ordinary):
        if self.attention.active:
            delta = (self.attention.target-scene.body.chunks[0].position)*.01
            return delta*min(1., 1/max(delta.length(), 1e-9))
        if self.returning:
            if (scene.look_direction-self.saved_look).length() < .001:
                self.returning = False
            return self.saved_look
        return ordinary
