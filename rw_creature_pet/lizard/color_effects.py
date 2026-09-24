"""白蜥蜴颜色效果；固定 tick 更新，不采样背景，不影响运动随机数。"""
from colorsys import hls_to_rgb
from math import pi, sin
from random import Random

WHITE = (1., 1., 1.)
DARK = (20/255, 20/255, 20/255)


def mix(a, b, t):
    return tuple(x + (y-x)*t for x, y in zip(a, b))


def hex_color(color):
    return '#' + ''.join(f'{max(0, min(255, round(v*255))):02x}' for v in color)


class ColorEffects:
    def __init__(self):
        self.rng = Random(0)  # 调试序列，不代表 Unity ID 兼容。
        self.excitement = .2
        self.phase = self.rng.random()
        self.flash = 0
        self.stun = 0
        self.dominance = 0.
        self.hue = self.rng.random()
        self.display_color = WHITE
        self.amount = 0.
        self.ticks = 0
        self.body = self.previous_body = WHITE
        self.head = self.previous_head = WHITE

    def trigger(self, effect):
        if effect == 'flash':
            self.flash = max(self.flash, 25)
        elif effect == 'stun':
            self.stun = max(self.stun, 15)
        elif effect == 'display':
            self.dominance = 1.
        else:
            raise ValueError('未知颜色效果')

    def sync_previous(self):
        self.previous_body, self.previous_head = self.body, self.head

    def update(self):
        self.sync_previous()
        self.ticks += 1
        r = self.rng.random
        self.dominance = max(0., self.dominance - 1/(60+60*r()))
        if self.dominance > 0:
            d = self.dominance
            self.hue = (self.hue + r()*d*d*.2) % 1
            self.display_color = mix(self.display_color, hls_to_rgb(self.hue, .5, 1), max(0., min(1., (d**.5-.5)*2))*r())
            target = 1-sin(min(1., d**.5/1.1)*pi)
            self.amount += (target-self.amount)*.1
        else:
            # 无拟态时展示结束回白；原版这里转回背景拟态。
            self.amount *= .9
            if self.amount < .0001:
                self.amount = 0.
                self.display_color = WHITE
        self.body = mix(WHITE, self.display_color, self.amount)
        if self.stun:
            self.phase = r()
        else:
            self.phase += .0025 + .0675*max(self.excitement, self.dominance) + r()*.001
        a = 1-(.5+.5*sin(self.phase*2*pi))**(1.5+self.excitement*1.5)
        if self.stun > 10:
            a = r()
        self.head = mix(self.body, mix(DARK, self.display_color, self.amount), a)
        if self.flash and (self.flash > 15 or self.ticks % 2 == 0):
            self.head = WHITE
        self.flash = max(0, self.flash-1)
        self.stun = max(0, self.stun-1)

    def colors(self, alpha):
        return (hex_color(mix(self.previous_body, self.body, alpha)),
                hex_color(mix(self.previous_head, self.head, alpha)))
