"""Qt 版原版图集/网格绘制；仅消费插值状态，不推进模拟。"""
from math import atan2, degrees

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPolygonF, QPainterPath

from .appearance import unit
from .geometry import Vec2


def strip_mesh(points, radii):
    """身体四段，每段独立四顶点、两个三角形，对应原版 BodyMesh。"""
    vertices, triangles = [], []
    for i in range(len(points) - 1):
        normal = unit(points[i + 1] - points[i])
        normal = Vec2(-normal.y, normal.x)
        offset = len(vertices)
        vertices.extend((points[i] - normal * radii[i], points[i] + normal * radii[i],
                         points[i + 1] - normal * radii[i + 1], points[i + 1] + normal * radii[i + 1]))
        triangles.extend(((offset, offset + 1, offset + 2), (offset + 1, offset + 2, offset + 3)))
    return vertices, triangles


def tail_mesh(root, segments, alpha, root_radius, fatness):
    vertices = []
    previous, radius = root, root_radius
    for i, segment in enumerate(segments):
        point = segment.previous_position.lerp(segment.position, alpha)
        axis = unit(point - previous)
        normal = Vec2(-axis.y, axis.x)
        smooth = (point - previous).length() / 5
        next_radius = segment.radius * segment.stretched * fatness
        width = (radius + next_radius) * .5
        vertices.extend((previous - normal * width + axis * smooth,
                         previous + normal * width + axis * smooth))
        if i == len(segments) - 1:
            vertices.append(point)
        else:
            vertices.extend((point - normal * next_radius - axis * smooth,
                             point + normal * next_radius - axis * smooth))
        previous, radius = point, next_radius
    return vertices, [(i, i + 1, i + 2) for i in range(len(vertices) - 2)]


def ground_body_mesh(chunks, head, tail0, radius):
    """连续肩颈轮廓：共享切线和边缘，避免半节圆补片在抬胸时鼓出。

    仅为侧视桌宠的显示适配；身体最大半径和头部物理连接不变。
    """
    points = [chunks[0].lerp(head, .5), *chunks]
    radii = [5.0, radius * .8125, radius, radius]
    tangents = [unit(points[1] - points[0])]
    tangents.extend(unit(points[i + 1] - points[i - 1]) for i in (1, 2))
    tangents.append(unit(tail0 - points[-2]))
    vertices, triangles = [], []
    for i in range(3):
        a, d = points[i], points[i + 1]
        reach = (d - a).length() / 3
        b, c = a + tangents[i] * reach, d - tangents[i + 1] * reach
        for j in range(7):
            if i and not j:
                continue
            t = j / 6
            u = 1 - t
            point = a*(u**3) + b*(3*u*u*t) + c*(3*u*t*t) + d*(t**3)
            axis = unit((b-a)*(u*u) + (c-b)*(2*u*t) + (d-c)*(t*t))
            normal = Vec2(-axis.y, axis.x)
            width = radii[i] + (radii[i+1]-radii[i]) * t*t*(3-2*t)
            vertices.extend((point-normal*width, point+normal*width))
            n = len(vertices)
            if n > 2:
                triangles.extend(((n-4, n-3, n-2), (n-3, n-2, n-1)))
    return vertices, triangles


class LizardRenderer:
    def __init__(self, atlas):
        self.atlas = atlas
        # 预检所有可能使用的帧，缺图时由窗口明确回退调试视图。
        for depth in range(4):
            for name, variant in zip(('LizardJaw', 'LizardLowerTeeth', 'LizardUpperTeeth', 'LizardHead', 'LizardEyes'), (0, 0, 0, 0, 3)):
                atlas.sprite(f'{name}{depth}.{variant}')
        for frame in range(1, 55):
            atlas.sprite(f'LizardArm_{frame:02}')
        atlas.sprite('Circle20')

    @staticmethod
    def head_view(axis, background):
        """纵深与平面朝向分离：背景固定背视，旋转仅改变屏幕内角度。"""
        if background:
            return 3, 1
        return max(0, min(3, 3 - int(abs(axis.x) * 3.9))), -1 if axis.x >= 0 else 1

    @staticmethod
    def limb_frame(distance, limb_size, hind, background, flip=1.0):
        frame = min(9, max(1, int(distance / (4 * limb_size)) + 1))
        # 腿的折叠形态独立于头部视角；趴墙也按各腿的真实 flip 选帧。
        return frame + 9 * (2 - min(2, int(abs(flip)*3))) + (27 if hind else 0)

    def _sprite(self, painter, name, position, angle=0, scale_x=1, scale_y=1, anchor_y=.5, tint='#ffffff'):
        image = self.atlas.sprite(name, tint)
        painter.save()
        painter.translate(position.x, position.y)
        painter.rotate(angle)
        painter.scale(scale_x, scale_y)
        painter.drawImage(QPointF(-image.width() * .5, -image.height() * (1 - anchor_y)), image)
        painter.restore()

    @staticmethod
    def _mesh(painter, vertices, triangles):
        painter.setPen(Qt.PenStyle.NoPen)
        # 填充色由本帧身体颜色设置。
        for triangle in triangles:
            painter.drawPolygon(QPolygonF([QPointF(vertices[i].x, vertices[i].y) for i in triangle]))

    def draw(self, painter, scene, alpha):
        painter.save()
        # 原始像素贴图采用最近邻，不用平滑过滤模糊眼睛和齿边。
        painter.setRenderHint(painter.RenderHint.SmoothPixmapTransform, False)
        painter.setRenderHint(painter.RenderHint.Antialiasing, False)
        # 图集脚趾可伸过 Limb 抓点数像素；平地裁切避免视觉上插入地板。
        painter.setClipRect(QRectF(0, -10000, scene.world.width, 10000 + scene.world.floor_y), Qt.ClipOperation.IntersectClip)
        appearance, p = scene.appearance, scene.appearance.params
        chunks = [c.previous_position.lerp(c.position, alpha) for c in scene.body.chunks]
        head = appearance.head.previous_position.lerp(appearance.head.position, alpha)
        background = scene.background_mode
        if background and scene.background.attached:
            # 图集像素可超出物理半径；显示层也服从同一活动区域。
            clip = QPainterPath()
            clip.setFillRule(Qt.FillRule.WindingFill)
            for x, y, width, height in scene.world.background_regions():
                clip.addRect(QRectF(x, y, width, height))
            painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        body_color, head_color = appearance.colors.colors(alpha)
        painter.setBrush(QColor(body_color))

        def limbs(side):
            for i, foot in enumerate(scene.feet):
                if foot.side != side:
                    continue
                toe = foot.previous_position.lerp(foot.position, alpha)
                hip = chunks[foot.chunk_index]
                if foot.chunk_index == 0:
                    hip = hip.lerp(chunks[1], .2)
                delta = toe - hip
                flip = appearance.previous_limb_flips[i] + (appearance.limb_flips[i]-appearance.previous_limb_flips[i])*alpha
                frame = self.limb_frame(delta.length(), p.limb_size, i >= 2, background, flip)
                mirror = 1 if flip >= 0 else -1
                self._sprite(painter, f'LizardArm_{frame:02}', toe, degrees(atan2(delta.y, delta.x)),
                             p.limb_size, mirror * p.limb_thickness, tint=body_color)

        limbs(-1)
        # 身体半节插值节点：原版 BodyPosition 的四个位置与显示半径。
        points = [chunks[0].lerp(head, .2)]
        circles = []
        tail0 = appearance.tail[0].previous_position.lerp(appearance.tail[0].position, alpha)
        for j in range(4):
            index = 1 if j < 2 else 2
            point = chunks[index]
            if j % 2 == 0:
                following = chunks[2] if index == 1 else tail0
                axis = unit(unit(point - chunks[index - 1]).lerp(unit(following - point), .35))
                point = point - axis * ((point - chunks[index - 1]).length() * .5)
            points.append(point)
            circles.append(point)
        radii = [5] + [8 * scene.body.breed.body_size * p.fatness] * 4
        if background:
            self._mesh(painter, *tail_mesh(chunks[2], appearance.tail, alpha, radii[-1], p.fatness * p.tail_fatness))
        if background:
            self._mesh(painter, *strip_mesh(points, radii))
        else:
            self._mesh(painter, *tail_mesh(chunks[2], appearance.tail, alpha, radii[-1], p.fatness * p.tail_fatness))
            vertices, _ = ground_body_mesh(chunks, head, tail0, radii[-1])
            # Qt 像素采样下独立三角形可能留下亚像素接缝，统一填充网格外边界。
            outline = vertices[::2] + vertices[1::2][::-1]
            painter.drawPolygon(QPolygonF([QPointF(v.x, v.y) for v in outline]))
        # 平地仅保留尾根封口；肩颈和腹部由共享边缘的连续网格连接。
        caps = list(zip(circles, radii[1:])) if background else [(chunks[2], radii[-1])]
        for point, radius in caps:
            self._sprite(painter, 'Circle20', point, scale_x=radius / 10, scale_y=radius / 10, tint=body_color)
        # 原版一侧腿先于躯干、另一侧后于躯干；允许近身腿段露在背部表面。
        limbs(1)
        axis = unit(head - chunks[0])
        rotation = degrees(atan2(axis.y, axis.x)) + 90
        depth, flip = self.head_view(axis, background)
        position = head.lerp(chunks[0], .2)
        size = p.head_size * p.individual_head_size
        for name, variant in zip(('LizardJaw', 'LizardLowerTeeth', 'LizardUpperTeeth', 'LizardHead', 'LizardEyes'), p.head_graphics):
            tint = '#141414' if name in ('LizardLowerTeeth', 'LizardUpperTeeth', 'LizardEyes') else head_color
            self._sprite(painter, f'{name}{depth}.{variant}', position, rotation, size * flip, size,
                         .75 if name == 'LizardEyes' else .7, tint)
        painter.restore()
