"""固定 tick 的平地求解器（y 向下）。

重力/阻力/反弹取自原版 Lizard 构造函数；连接按原版的位置和速度
同步修正方式迭代。地形简化为地板和两侧边界。地面切向阻尼及
微速停止是本项目的稳定化处理，不声称与原版 Room 碰撞逐帧相同。
背景抓附显式传入髋部可达范围，与身体连接一起求解，不改变平地路径。
"""
from ..shared.geometry import Vec2
from .model import ConnectionKind

GRAVITY = 0.9
AIR_FRICTION = 0.999
BOUNCE = 0.1
GROUND_FRICTION = 0.5
STOP_SPEED = 0.02
SOLVER_ITERATIONS = 16
CONTACT_EPSILON = 1e-7


def solve_connection(body, connection):
    first, second = body.chunks[connection.first], body.chunks[connection.second]
    delta = second.position - first.position
    length = delta.length()
    if connection.kind == ConnectionKind.PUSH and length >= connection.distance:
        return
    if length > 1e-10:
        direction = delta * (1.0 / length)
    else:
        # 重合时仍可恢复距离，优先使用上帧方向。
        previous = second.previous_position - first.previous_position
        direction = previous * (1.0 / previous.length()) if previous.length() > 1e-10 else Vec2(-1, 0)
    correction = direction * ((connection.distance - length) * connection.elasticity)
    a = correction * connection.weight_symmetry
    b = correction * (1.0 - connection.weight_symmetry)
    first.position = first.position - a
    second.position = second.position + b
    first.velocity = first.velocity - a
    second.velocity = second.velocity + b


def _project(chunk, world, impact=False):
    """每轮位置投影；反弹与摩擦只在积分后的首次碰撞执行一次。"""
    x, y = chunk.position.x, chunk.position.y
    vx, vy = chunk.velocity.x, chunk.velocity.y
    floor = world.floor_y - chunk.radius
    if y >= floor - CONTACT_EPSILON:
        y = floor
        if vy > 0:
            vy = -vy * BOUNCE if impact else 0.0
            if abs(vy) < GRAVITY:
                vy = 0.0
        if impact:
            vx *= GROUND_FRICTION
            if abs(vx) < STOP_SPEED:
                vx = 0.0
    if x < chunk.radius:
        x = chunk.radius
        if vx < 0:
            vx = -vx * BOUNCE if impact else 0.0
    elif x > world.width - chunk.radius:
        x = world.width - chunk.radius
        if vx > 0:
            vx = -vx * BOUNCE if impact else 0.0
    chunk.position = Vec2(x, y)
    chunk.velocity = Vec2(vx, vy)


def step_body(body, world, *, gravity=GRAVITY, air_friction=AIR_FRICTION,
              reach_limits=(), background=False):
    def within_limits(previous=False):
        positions = [c.previous_position if previous else c.position for c in body.chunks]
        return (all((positions[index]-point).length() <= reach+1e-6
                    for index, point, reach in reach_limits)
                and (not background or all(world.background_contains(p, c.radius)
                                           for p, c in zip(positions, body.chunks))))

    for chunk in body.chunks:
        chunk.previous_position = chunk.position
        chunk.velocity = (chunk.velocity + Vec2(0, gravity)) * air_friction
        chunk.position = chunk.position + chunk.velocity
        _project(chunk, world, impact=True)
    for _ in range(64 if reach_limits else SOLVER_ITERATIONS):
        for connection in body.connections:
            solve_connection(body, connection)
        for chunk in body.chunks:
            _project(chunk, world)
            if background:
                projected = world.background_position(chunk.position, chunk.radius)
                chunk.velocity = chunk.velocity + (projected-chunk.position)
                chunk.position = projected
        for index, point, reach in reach_limits:
            chunk = body.chunks[index]
            offset = chunk.position-point
            if offset.length() > reach:
                projected = point + offset*(reach/offset.length())
                chunk.velocity = chunk.velocity + (projected-chunk.position)
                chunk.position = projected
        safe = within_limits() if reach_limits or background else True
        if safe and all(body.connection_error(connection) < 1e-6 for connection in body.connections):
            break
    if reach_limits and (not safe or any(body.connection_error(c) > .001 for c in body.connections)) and within_limits(previous=True):
        # 极端牵引下未收敛则保留上一帧可行姿态，等待换脚；不能拉断脚或放弃体型。
        for chunk in body.chunks:
            chunk.position = chunk.previous_position
            chunk.velocity = Vec2()
    for chunk in body.chunks:
        chunk.grounded = abs(chunk.position.y + chunk.radius - world.floor_y) <= CONTACT_EPSILON
        if chunk.grounded:
            vx, vy = chunk.velocity.x, chunk.velocity.y
            chunk.velocity = Vec2(0.0 if abs(vx) < STOP_SPEED else vx,
                                  0.0 if abs(vy) < STOP_SPEED else vy)
