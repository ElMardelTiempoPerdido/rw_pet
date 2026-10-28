"""触须折点的局部曲线过渡，只生成绘制路径，不增加物理节点"""
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath


CORNER_FRACTION = .2  # 参考原版网格每段两端各内收 1/5 的连接范围


def rounded_paths(points):
    """每个物理连接段对应一条路径，共用接头切线并保持端点和原节点包围范围"""
    last = len(points)-1
    if last < 1:
        return []
    incoming = [p if i in (0, last) else p.lerp(points[i-1], CORNER_FRACTION)
                for i, p in enumerate(points)]
    outgoing = [p if i == last else p.lerp(points[i+1], CORNER_FRACTION)
                for i, p in enumerate(points)]
    centers = [p if i in (0, last) else (incoming[i]+p*2+outgoing[i])*.25
               for i, p in enumerate(points)]
    paths = []
    for i in range(last):
        start = QPointF(centers[i].x, centers[i].y)
        end = QPointF(centers[i+1].x, centers[i+1].y)
        path = QPainterPath(start)
        # 将同一条二次曲线在中点拆给相邻两段，沿用每段配色，接头仍连续
        if i > 0:
            control = points[i].lerp(outgoing[i], .5)
            path.quadTo(control.x, control.y, outgoing[i].x, outgoing[i].y)
        path.lineTo(incoming[i+1].x, incoming[i+1].y)
        if i+1 < last:
            control = incoming[i+1].lerp(points[i+1], .5)
            path.quadTo(control.x, control.y, end.x(), end.y())
        paths.append((start, end, path))
    return paths
