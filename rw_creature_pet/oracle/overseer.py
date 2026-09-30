"""Oracle 为监视者提供的边缘与人偶避让范围；调试/桌面共用同一几何定义。"""
from ..shared.geometry import Bounds
from ..overseer.events import SpawnContext


def overseer_bounds(scene):
    w = scene.world
    # 根部从工作区边缘探出，不能继承机械臂轨道的内缩距离。
    # 四角余量由模型/事件沿边限制，不应把整个附着平面向内平移。
    return Bounds(0., 0., w.width, w.height)


def puppet_position(scene):
    # 只读躯干质点，不计算外形或唤醒衣袍/线缆；较大半径覆盖头和四肢。
    return scene.body.chunks[0].position.lerp(scene.body.chunks[1].position, .5)


def spawn_context(scene, mouse):
    points = [p.position for p in scene.appearance.body_points]
    points.extend(p.position for p in scene.body.chunks)
    puppet = Bounds(min(p.x for p in points)-20, min(p.y for p in points)-20,
                    max(p.x for p in points)+20, max(p.y for p in points)+20)
    return SpawnContext(overseer_bounds(scene), scene.config.allowed_edges, mouse, (puppet,),
                        puppet_position(scene))
