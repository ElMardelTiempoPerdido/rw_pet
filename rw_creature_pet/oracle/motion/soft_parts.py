"""单端柔性带：前向限长与抗弯，独立休眠，不向人偶导航施力"""
from math import atan2, ceil, cos, pi, radians, sin

from ...shared.geometry import Vec2
from ..graphics.cords import CordPoint, close_inputs
from ..soft_part_assets import soft_part_size
from ..soft_part_config import SOFT_PART_FIELDS


def unit(vector, fallback=Vec2(0, 1)):
    length = vector.length()
    return vector*(1/length) if length > 1e-9 else fallback


def attachment_frame(config, appearance):
    up = appearance.direction
    if config.anchor == 'head':
        origin = appearance.head.position
        up = unit(origin-appearance.upper, up)
    elif config.anchor == 'waist':
        origin = appearance.lower
        up = appearance.waist_direction(up)
    else:
        origin = appearance.upper+up*3.
    side = Vec2(-up.y, up.x)
    origin += side*config.offset_x-up*config.offset_y
    angle = radians(config.angle)
    down = up*-1
    return origin, Vec2(down.x*cos(angle)-down.y*sin(angle),
                        down.x*sin(angle)+down.y*cos(angle))


class SoftStrip:
    """最多 16 个节点；前两个点定义一小段固定根部，其余节点自由下垂"""
    def __init__(self, config, root, direction, gravity):
        self.config = config
        self.width, self.length = soft_part_size(config)
        segments = max(4, min(15, ceil(self.length/4)))
        first = min(1.5, self.length/4)
        self.rest = [first]+[(self.length-first)/(segments-1)]*(segments-1)
        positions = [root]
        for i, length in enumerate(self.rest):
            # 只在初始化留极小弧度，打破倒立时完全竖直的受力对称；没有持续随机力
            angle = .035*sin(pi*i/segments)*(1 if config.offset_x >= 0 else -1)
            tangent = Vec2(direction.x*cos(angle)-direction.y*sin(angle),
                           direction.x*sin(angle)+direction.y*cos(angle))
            positions.append(positions[-1]+tangent*length)
        self.points = [CordPoint(p, p) for p in positions]
        self.revision = 0
        self.root, self.direction = root, direction
        self.gravity = gravity
        self.sleeping = False
        self.quiet_ticks = 0
        self.last_inputs = None

    def step(self, root, direction, gravity):
        config = self.config
        delta = root-self.root
        # 重置位置/分辨率变化等不连续移动整体搬移附件，避免拖出横跨屏幕的长带
        if delta.length() > max(80., self.length*2):
            for p in self.points:
                p.position += delta
                p.previous_position = p.position
                p.velocity = Vec2()
            delta = Vec2()
            self.sleeping = False
            self.quiet_ticks = 0
        self.root, self.direction, self.gravity = root, direction, gravity
        inputs = (root, direction, gravity, config.softness, config.damping)
        stable = close_inputs(inputs, self.last_inputs)
        if self.sleeping and stable:
            for i, p in enumerate(self.points[:2]):
                p.position = p.previous_position = root+direction*(self.rest[0] if i else 0)
            return False
        self.sleeping = False
        if not stable:
            self.last_inputs = inputs
            self.quiet_ticks = 0
        damping = .96-.30*config.damping
        acceleration = Vec2(0, .20*gravity)
        predicted = []
        for p in self.points:
            p.previous_position = p.position
            # 空气阻尼相对于佩戴者；匀速下移不把围巾持续吹到脸前
            predicted.append(p.position+delta+(p.velocity-delta)*damping+acceleration)
        self.points[0].position = root
        self.points[1].position = root+direction*self.rest[0]
        tangent = direction
        # 单端固定、自由末端的短链可一次前向投影精确保持绳长，不需要长线缆的多轮迭代
        max_bend = .35+2.*config.softness
        for i in range(2, len(self.points)):
            previous = self.points[i-1].position
            desired = unit(predicted[i]-previous, tangent)
            angle = atan2(tangent.x*desired.y-tangent.y*desired.x,
                          tangent.x*desired.x+tangent.y*desired.y)
            angle = max(-max_bend, min(max_bend, angle))
            tangent = Vec2(tangent.x*cos(angle)-tangent.y*sin(angle),
                           tangent.x*sin(angle)+tangent.y*cos(angle))
            self.points[i].position = previous+tangent*self.rest[i-1]
        speed = 0.
        for p in self.points:
            p.velocity = p.position-p.previous_position
            speed = max(speed, p.velocity.length())
        self.quiet_ticks = self.quiet_ticks+1 if stable and speed < .002 else 0
        if self.quiet_ticks >= 30:
            self.sleeping = True
            for p in self.points:
                p.previous_position = p.position
                p.velocity = Vec2()
        self.revision += 1
        return True


class SoftParts:
    def __init__(self, scene):
        self.parts = [None, None]
        self.revision = 0
        self.sync(scene)

    @property
    def sleeping(self):
        return all(part is None or part.sleeping for part in self.parts)

    def sync(self, scene):
        shape = scene.config.active_custom_appearance
        for index, name in enumerate(SOFT_PART_FIELDS):
            config = getattr(shape, name) if shape is not None else None
            part = self.parts[index]
            if config is None or not config.enabled:
                if part is not None:
                    self.parts[index] = None
                    self.revision += 1
                continue
            root, direction = attachment_frame(config, scene.appearance)
            width, length = soft_part_size(config)
            if part is None or length != part.length or config.anchor != part.config.anchor:
                self.parts[index] = SoftStrip(config, root, direction, scene.pose.gravity_scale)
                self.revision += 1
            elif part.config != config or width != part.width:
                # 实际长度不变时，换形状、PNG 或层级不打断已经收敛的姿态
                physical = ('offset_x', 'offset_y', 'angle', 'softness', 'damping')
                wake = any(getattr(config, key) != getattr(part.config, key) for key in physical)
                part.config = config
                part.width = width
                if wake:
                    part.sleeping = False
                    part.quiet_ticks = 0
                part.revision += 1
                self.revision += 1

    def step(self, scene):
        self.sync(scene)
        for part in self.parts:
            if part is not None:
                root, direction = attachment_frame(part.config, scene.appearance)
                if part.step(root, direction, scene.pose.gravity_scale):
                    self.revision += 1

    def reset(self, scene):
        self.parts = [None, None]
        self.revision += 1
        self.sync(scene)
