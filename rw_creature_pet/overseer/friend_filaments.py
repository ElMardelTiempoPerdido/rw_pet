"""朋友？的双触须形态参数，物理仍复用监视者的柔性链"""
from math import cos, hypot, pi, radians, sin, sqrt

from .friend import neck_offset
from ..shared.geometry import Vec2


LENGTHS = (24., 36.)  # 短、长触须的基准弧长，随体型乘以 0.75 + 0.25 * size
COLORS = ('#BDA3E7', '#8C46FF')
TIP_COLOR = '#0000FF'
GRADIENT_START = .55  # 前段保留指定紫色，后段渐变至纯蓝
BASE_OFFSET = 2.5  # 共用连接点沿颈部方向退到脸盘之后，逻辑像素
BASE_DEPTH = 1.5  # 连接点位于颈部背向镜头一侧的深度，逻辑像素
TURN_DEPTH_SOFTNESS = .25  # 保留最小投影深度，防止极远侧视时穿过正中位置突然翻边
SIDE_VISIBILITY_GAIN = 3.  # 侧向可见性增强，1 恢复原投影；越大越容易在小角度侧视时露出触须
BACK_ANGLES = (30., 55.)  # 从颈部背面的深度方向朝身体后方偏转，投影后随转头换边
CURVE_AMPLITUDES = (2.5, -3.0)  # 短须 C 弧、长须 S 弧的侧向偏好，逻辑像素；负值翻转弯曲方向
CURVE_STRENGTH = .06  # 轻微回弯的弹性力度，0 关闭；末端仍可自由移动


def lengths(size):
    return tuple(length*(.75+.25*size) for length in LENGTHS)


def frame(model, alpha=1.):
    """颈部局部坐标：屏幕内轴线、侧向、背面深度方向的有符号投影"""
    from .model import dot, perpendicular, unit
    axis = unit(neck_offset(model, alpha), model.normal)
    side = perpendicular(axis)
    gaze, depth = model.head_gaze(alpha)
    lateral = dot(gaze, side)
    # 去掉沿颈部的分量，令背面方向垂直于颈部；不把二维投影归一化成左右两档
    span = hypot(lateral, max(depth, TURN_DEPTH_SOFTNESS*model.extension(alpha)))
    rear = -lateral/span if span > 1e-8 else 0.
    # 小角度优先向侧面展开，大角度平滑趋近完整侧视；过零连续且始终不超过原弧长
    gain = max(1., SIDE_VISIBILITY_GAIN)
    rear = gain*rear/sqrt(1+(gain*gain-1)*rear*rear)
    return axis, side, rear


def back_angle(model, index):
    return radians(BACK_ANGLES[index])+.10*sin(model.time*.8+index*1.9)


def projected_lengths(model):
    # 朝屏幕深处的分量不可见，正视时同时缩短二维约束长度，避免硬撑到固定一侧
    _, _, rear = frame(model)
    return tuple(length*hypot(rear*cos(back_angle(model, i)), sin(back_angle(model, i)))
                 for i, length in enumerate(lengths(model.config.size)))


def attachment(model, alpha=1.):
    axis, side, rear = frame(model, alpha)
    scale = (.75+.25*model.config.size)*model.extension(alpha)
    return model.eye_position(alpha)+(side*(BASE_DEPTH*rear)-axis*BASE_OFFSET)*scale


def tip_targets(model):
    axis, side, rear = frame(model)
    base = attachment(model)
    targets = []
    for i, length in enumerate(lengths(model.config.size)):
        angle = back_angle(model, i)
        direction = side*(rear*cos(angle))-axis*sin(angle)
        # 目标只弱牵引中段，末端自由摆动，避免两根始终保持直线
        targets.append(base+direction*(length*.8*model.extended))
    return targets


def bend_forces(model, index, strand, base, fallback):
    """相对当前首尾连线轻推中段，保留实际端点与惯性，不把链条固定到世界曲线上"""
    from .model import dot, perpendicular, unit
    forces = [Vec2() for _ in strand]
    if CURVE_STRENGTH <= 0 or model.extended <= 0:
        return forces
    normal = perpendicular(unit(strand[-1].position-base, fallback))
    # C/S 弧也随深度平面的投影收窄、换边，不在正视附近保留固定侧偏
    _, _, rear = frame(model)
    amplitude = CURVE_AMPLITUDES[index]*(.75+.25*model.config.size)*model.extended*rear
    # 半个正弦形成 C 弧，一个完整正弦形成带拐点的 S 弧
    frequency = pi if index == 0 else 2*pi
    for i in range(1, len(strand)-1):
        fraction = i/(len(strand)-1)
        offset = dot(strand[i].position-base, normal)
        preferred = amplitude*sin(frequency*fraction)
        force = normal*((preferred-offset)*CURVE_STRENGTH*model.extended)
        forces[i] = force
        # 让自由末端分担反作用，避免只推中段把整条触须转走而不是弯曲
        forces[-1] -= force*fraction
    return forces
