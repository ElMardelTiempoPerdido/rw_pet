"""Prince 高跟手抓取的整体校正，保持九段身体长度及真实触手支撑"""
from ...interaction.drag import limited
from ...shared.geometry import Vec2


def constrain_grip(drag):
    """身体轴已完成柔性求解；只平移，不单独拉伸被抓节点"""
    scene = drag.scene
    index, target = drag.prince_grab()
    posture = scene.prince_posture
    upper = scene.body.chunks[0]
    weight = (drag.responsiveness-.5)*2
    shift = (target-posture.points[index].position)*weight
    goal = upper.position+shift
    support = scene.prince_tentacles
    if support is not None and support.guard is not None:
        # 使用本步求解后的胸部，而非上一帧缓存的触手根部
        frame = posture.frame(upper.position, scene.body.direction)
        root = frame.chest+support.outward*support.BACK_OUTSET-frame.chest_direction*support.BACK_DOWN
        local = support.guard.definition.points[0]
        root += support.outward*local.x+Vec2(-support.outward.y, support.outward.x)*local.y
        center = support.guard.grip-(root-upper.position)
        reach = max(1., support.guard.length_limit-support.DRAG_ROOT_MARGIN)
        for _ in range(12):
            goal = drag.outer.clamp(goal)
            goal = center+limited(goal-center, reach)
    else:
        goal = drag.outer.clamp(goal)
    shift = goal-upper.position
    for chunk in scene.body.chunks:
        chunk.position += shift
        # 停止后按实际净位移收敛，不积累导航与抓取校正之间相互抵消的速度
        chunk.velocity = limited(chunk.position-chunk.previous_position, 7.)
    return shift
