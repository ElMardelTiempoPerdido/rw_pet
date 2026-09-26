"""以完好 Moon 为基础的 Bell 外观预览；绘制只读，不推进次级运动。"""
from math import atan2, ceil, cos, degrees, floor, radians, sin
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

from ..shared.geometry import Vec2
from .config import OracleColors
from .scene import unit
from .appearance import HangingHand, perpendicular, rotate
from .arm_graphics import base_outline, base_support_region, detail_scale, ik_bend, make_arm_frame
from .damage import body_bounds
from .raster import local_canvas, painter_density, pixel_density


def point(v):
    return QPointF(v.x, v.y)


def mixed(a, b, t):
    a, b = QColor(a), QColor(b)
    return QColor.fromRgbF(a.redF()*(1-t)+b.redF()*t,
                          a.greenF()*(1-t)+b.greenF()*t,
                          a.blueF()*(1-t)+b.blueF()*t)


def bezier(a, b, c, d, t):
    u = 1-t
    aa, bb, cc, dd = u*u*u, 3*u*u*t, 3*u*t*t, t*t*t
    return Vec2(a.x*aa+b.x*bb+c.x*cc+d.x*dd, a.y*aa+b.y*bb+c.y*cc+d.y*dd)


class PaintCommands:
    """帧内只建立一次 Qt 几何对象，两个视图分别重放；不序列化贴图。"""
    def __init__(self):
        self.commands = []
        self.names = set()

    def __getattr__(self, name):
        commands = self.commands
        self.names.add(name)
        def record(*args):
            commands.append((name, args))
        setattr(self, name, record)
        return record

    def replay(self, painter):
        if isinstance(painter, PaintCommands):
            # 引用已完成的子层，而非每帧重新记录上千条身体绘图指令。
            painter.commands.append((None, self))
            return
        methods = {name: getattr(painter, name) for name in self.names}
        painter.save()
        for name, args in self.commands:
            if name is None:
                args.replay(painter)
            else:
                methods[name](*args)
        painter.restore()


class OracleRenderer:
    SPRITES = ('Circle20', 'pixel', 'haloGlyph-1',
               'MirosLegSmallPart', 'deerEyeB', 'CentipedeSegment', 'JetFishEyeA', 'tinyStar')
    # Bell 的试用外观尺寸，与原版 Moon / Pebbles 的分支取值独立。
    CORD_SEGMENT_SPACING = 12.  # 沿用用户实机校准；节纹长 7.2，间隙约 2.8。
    SLEEVE_ROOT_HALF_WIDTH = 3.
    SLEEVE_CUFF_HALF_WIDTH = 5.
    SLEEVE_ROOT_RISE = HangingHand.SHOULDER_RISE
    SLEEVE_SHOULDER_OUTSET = 3.
    OPEN_EYE_WIDTH = 2.
    OPEN_EYE_HEIGHT = 2.
    HEAD_CROWN_RISE = 1.  # 仅增加头顶空间；椭圆下缘及五官锚点不动。
    FACE_DOT_SIZE = 1.
    FACE_DOT_HALF_SPACING = 4.
    FACE_DOT_Y_OFFSETS = (2., 4.)  # 圆环中心比上方侧点高 2；两侧点相隔 2。
    FOREHEAD_CENTER_Y = -4.
    # 5×5 圆环和中央横径；两根 1×2 竖条与圆环下缘共用第一格。
    FOREHEAD_PIXELS = ('.###.', '#...#', '#####', '#...#', '.###.', '.#.#.')
    PHONE_ROD_TOP = -5.
    PHONE_ROD_BOTTOM = 6.
    PHONE_ROD_INSET = .55
    PHONE_ROD_DEPTH = 1.2
    PHONE_BAR_LENGTH = 1.
    PHONE_BAR_SPACING = 2.
    HEAD_PIXELS = 33
    INNER_NECK_HEAD_GAP = 6.5  # 平领口距头部中心，沿实际颈部方向测量。
    INNER_NECK_HALF = 1.5
    CHEST_TOP_DROP = 1.  # 胸肩上缘降低 1；宽度和下缘保持原来的范围。
    GOWN_NECK_HALF = .38  # 网格 UV 空间；开口略加宽、变浅，使 V 角稍展开。
    GOWN_NECK_DEPTH = .28
    GOWN_TRIM_HALF = .70  # 相对开口的半宽差 .08→.32，深度差 .04→.16。
    GOWN_TRIM_DEPTH = .44

    def __init__(self, atlas=None, colors=OracleColors(), *, glyphs=None):
        self.atlas = atlas
        self.colors = colors
        self.glyphs = glyphs
        self._pearl_palette_key = None
        self._pearl_palette = ()
        self._arm_geometry_key = None
        self._arm_frames = ()
        self._frame_key = None
        self._frame = None
        self._body_key = None
        self._body_pose = ()
        self._body_origin = Vec2()
        self._body_frame = None
        self._body_front_frame = None
        self._head_key = None
        self._head_image = None
        self._head_geometry_key = None
        self._head_frame = None
        self._bead_key = None
        self._bead_images = ()
        self._raster_key = None
        self._raster_image = None
        self._halo_key = None
        self._halo_image = None
        self._gown_colors_key = None
        self._gown_colors = ()
        if atlas is not None:
            for name in self.SPRITES:
                atlas.sprite(name)

    def sprite(self, painter, name, center, width, height, color, rotation=0, mirror=False):
        painter.save()
        painter.translate(center.x, center.y)
        painter.rotate(rotation)
        if mirror:
            painter.scale(-1, 1)
        rect = QRectF(-width / 2, -height / 2, width, height)
        if self.atlas is not None:
            painter.drawImage(rect, self.atlas.sprite(name, color if isinstance(color, str) else color.name()))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            if name in ('pixel', 'MirosLegSmallPart'):
                painter.drawRect(rect)
            elif name == 'LizardScaleA1':
                path = QPainterPath(QPointF(0, -height / 2))
                path.lineTo(width / 2, height / 2)
                path.lineTo(-width / 2, height / 2)
                path.closeSubpath()
                painter.drawPath(path)
            else:
                painter.drawEllipse(rect)
        painter.restore()

    @staticmethod
    def line(painter, a, b, color, width):
        painter.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(point(a), point(b))

    @staticmethod
    def polyline(painter, points, color, width):
        path = QPainterPath(point(points[0]))
        for p in points[1:]:
            path.lineTo(point(p))
        painter.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def part_between(self, painter, name, start, end, width, color, mirror=False):
        v = end-start
        self.sprite(painter, name, start.lerp(end, .5), width, max(.01, v.length()),
                    color, degrees(atan2(v.y, v.x))-90, mirror=mirror)

    @staticmethod
    def polygon(painter, vertices, color):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawPolygon(QPolygonF([point(v) for v in vertices]))

    def arm_frames(self, scene, alpha):
        joints = tuple(j.previous_position.lerp(j.position, alpha) for j in scene.arm.joints)
        lower = scene.body.chunks[1].previous_position.lerp(scene.body.chunks[1].position, alpha)
        key = (joints, lower, scene.config.arm_scale, scene.world.width,
               scene.world.height, scene.world.edge_fraction)
        # 主视图和放大镜共享只读几何，不重复求曲线边界，也不推进转动相位。
        if key != self._arm_geometry_key:
            self._arm_frames = tuple(make_arm_frame(a, b, scene.arm.lengths[i], i,
                                                    scene.config.arm_scale, scene.arm_region)
                for i, (a, b) in enumerate(zip(joints, (*joints[1:], lower))))
            self._arm_geometry_key = key
        return self._arm_frames

    def draw_arm_base(self, painter, scene, base, normal, elbow, front):
        c, scale = self.colors, scene.config.arm_scale
        ds = detail_scale(scale)
        body = mixed(c.joints, c.arm, .8)
        highlight = mixed(c.joints, c.arm_highlight, .8)
        self.polygon(painter, base_outline(base, normal, scale), body)
        tangent = perpendicular(normal)
        origin = base-normal*(10*ds)
        if front:
            self.polygon(painter, base_outline(base, normal, scale, 24, 15, 30), highlight)
            for sign in (-1, 1):
                center = origin+tangent*(17*ds*sign)
                self.sprite(painter, 'Circle20', center, 10*ds, 10*ds, body)
                self.sprite(painter, 'Circle20', center-tangent*ds+normal*ds,
                            9*ds, 9*ds, highlight)
            return
        # 原版底座两侧各有 25/45 比例的折叠支架，连接首段肘部方向。
        target = base.lerp(elbow, .25)
        region = base_support_region(scene.world)
        for sign in (-1, 1):
            anchor = origin+normal*(11*ds)+tangent*(17*ds*sign)
            knee = ik_bend(anchor, target, 25*ds, 45*ds, sign, region)
            self.part_between(painter, 'pixel', anchor, knee, 2*ds, c.joints)
            self.part_between(painter, 'pixel', knee, target, 2*ds, c.joints)
            self.sprite(painter, 'deerEyeB', knee, 5*ds, 5*ds, c.joints)

    def draw_arm(self, painter, scene, alpha):
        c = self.colors
        frames = self.arm_frames(scene, alpha)
        ds = detail_scale(scene.config.arm_scale)
        normal = scene.base_normal(alpha)
        base = frames[0].start
        self.draw_arm_base(painter, scene, base, normal, frames[0].elbow, front=False)
        for index, frame in enumerate(frames):
            a, b, elbow = frame.start, frame.end, frame.elbow
            turns = (scene.appearance.previous_cog_turns[index]
                     + (scene.appearance.cog_turns[index]-scene.appearance.previous_cog_turns[index])*alpha)
            angle = degrees(atan2((elbow-a).y, (elbow-a).x))-90+turns*360
            for spoke in range(3):
                self.sprite(painter, 'pixel', frame.root_circle, (5-index*.5)*ds,
                            (18-index*2)*ds, c.joints, angle+60*spoke)
            self.part_between(painter, 'MirosLegSmallPart', elbow, frame.metal_end,
                              4*(1.5 if index == 0 else 1 if index == 1 else .8)*ds,
                              c.joints, mirror=index % 2 == 0)
            rod_width = (2 if index == 0 else 1)*ds
            self.part_between(painter, 'pixel', elbow, frame.piston, rod_width, c.joints)
            self.part_between(painter, 'pixel', b, frame.piston, rod_width, c.joints)
            self.sprite(painter, 'deerEyeB', frame.piston, 5*ds, 5*ds, c.joints)
            # 肘部圆盘先画，外壳从两边覆盖；主关节圆盘在外壳前。
            diameter = (6-index*1.5)*2*ds
            self.sprite(painter, 'Circle20', elbow, diameter, diameter, c.joints)
            self.sprite(painter, 'deerEyeB', elbow, 5*ds, 5*ds,
                        mixed(c.joints, c.arm_highlight, .5))
            for strip in frame.strips:
                self.polygon(painter, strip.outline(), c.arm)
                self.polygon(painter, strip.outline(.5), c.arm_highlight)
            diameter = (7-index*.5)*2*ds
            self.sprite(painter, 'Circle20', frame.root_circle, diameter, diameter, c.joints)
            self.sprite(painter, 'deerEyeB', frame.root_circle, 5*ds, 5*ds,
                        mixed(c.joints, c.arm_highlight, .5))
        self.draw_arm_base(painter, scene, base, normal, frames[0].elbow, front=True)

    def draw_cords(self, painter, scene, alpha):
        c = self.colors
        appearance = scene.appearance
        main = [p.sample(alpha) for p in appearance.main_cord]
        metal = mixed('#000000', c.joints, .55)
        self.polyline(painter, main, metal, 2.4)
        # 原版双层 CentipedeSegment，桌面节纹取 0.8 比例。按弧长放置，
        # 绳索物理采样密度改变时不会挤成一根实心亮杆。
        distance = self.CORD_SEGMENT_SPACING*.5
        dark = mixed(c.arm, metal, .6)
        bright = mixed(c.arm_highlight, metal, .45)
        for a, b in zip(main, main[1:]):
            delta = b-a
            length = delta.length()
            if length < 1e-9:
                continue
            while distance <= length:
                center = a.lerp(b, distance/length)
                # 节纹长轴是贴图 X 轴，直接对齐切线；减 90° 仅适用于纵向贴图。
                angle = degrees(atan2(delta.y, delta.x))
                self.sprite(painter, 'CentipedeSegment', center, 7.2, 3.6, dark, angle)
                self.sprite(painter, 'CentipedeSegment', center, 5.76, 1.8, bright, angle)
                distance += self.CORD_SEGMENT_SPACING
            distance -= length
        cord_colors = (metal, mixed('#ff0000', metal, .55), mixed('#0000ff', metal, .55))
        for index, cord in enumerate(appearance.small_cords):
            self.polyline(painter, [p.sample(alpha) for p in cord],
                          cord_colors[appearance.cords.colors[index]], 1.)
        self.sprite(painter, 'Circle20', main[-1], 4., 4., dark)
        self.sprite(painter, 'Circle20', main[-1], 2.5, 2.5, bright)

    def ribbon(self, painter, a, b, c, d, start_width, end_width, top_color, bottom_color,
               across=False, side_sign=1):
        points = [bezier(a, b, c, d, i/7) for i in range(8)]
        edges = []
        for i, p in enumerate(points):
            side = perpendicular(unit(points[min(i+1, 7)]-points[max(i-1, 0)])) * side_sign
            half = start_width+(end_width-start_width)*(i/7)**.5
            edges.append((p-side*half, p+side*half))
        if across:
            self.transverse_strip(painter, edges, top_color, bottom_color)
            return
        for i in range(7):
            color = mixed(top_color, bottom_color, max(0., (i-3)/3))
            painter.setBrush(color)
            painter.setPen(QPen(color, .15))
            painter.drawPolygon(QPolygonF([point(p) for p in
                (edges[i][0], edges[i][1], edges[i+1][1], edges[i+1][0])]))

    def transverse_strip(self, painter, edges, dark, bright):
        # 三角形的三个顶点严格落在 0/1 色值上。弯袖子的每一段单独横向
        # 画矩形渐变会让共用顶点出现色差，这里用顶点到对边的投影求梯度。
        def projection(p, a, b):
            v = b-a
            return a+v*(((p-a).x*v.x+(p-a).y*v.y)/max(v.x*v.x+v.y*v.y, 1e-12))
        painter.save()
        outline = [a for a, _ in edges]+[b for _, b in reversed(edges)]
        self.polygon(painter, outline, mixed(dark, bright, .5))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for (a, b), (d, c) in zip(edges, edges[1:]):
            # MakeLongMesh 的三角形顺序：暗/亮/暗，再亮/暗/亮。
            for vertices, start, end in (((a, b, d), projection(b, a, d), b),
                                         ((b, d, c), d, projection(d, b, c))):
                gradient = QLinearGradient(point(start), point(end))
                gradient.setColorAt(0, QColor(dark))
                gradient.setColorAt(1, QColor(bright))
                painter.setBrush(gradient)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPolygon(QPolygonF([point(v) for v in vertices]))
        painter.restore()

    def sleeve_edges(self, shoulder, end, direction, sign):
        """原版七段袖根/段间延伸构造，截面沿 Bell 的袖宽平滑展开。"""
        outward = perpendicular(direction)*sign
        # 原版向外伸 5；Bell 收到 3，让肩部转折靠近衣袍，形成较缓的溜肩。
        a = shoulder+outward*self.SLEEVE_SHOULDER_OUTSET
        b = end+unit(shoulder-end)*3+direction
        previous = shoulder-outward*2
        edges = []
        for i in range(7):
            t = i/6
            center = bezier(shoulder, a, b, end, t)
            tangent = unit(center-previous, outward)
            normal = perpendicular(tangent)*(-sign)
            half = (self.SLEEVE_ROOT_HALF_WIDTH
                    + (self.SLEEVE_CUFF_HALF_WIDTH-self.SLEEVE_ROOT_HALF_WIDTH)*t*t*(3-2*t))
            back = center-tangent*((center-previous).length()*.3)
            edges.extend(((back-normal*half, back+normal*half),
                          (center-normal*half, center+normal*half)))
            previous = center
        return edges

    @staticmethod
    def strip_path(edges):
        path = QPainterPath()
        path.addPolygon(QPolygonF([point(a) for a, _ in edges]
                                  + [point(b) for _, b in reversed(edges)]))
        path.closeSubpath()
        return path

    def draw_hand(self, painter, end):
        # 图集恢复了透明留白：10×10 画布中实际有色部分约 4×4。
        # 按原生画布尺寸绘制，避免整张再缩成 4×4 后只剩 1.6×1.6。
        width = height = 4.
        if self.atlas is not None:
            texture = self.atlas.sprite('haloGlyph-1')
            width, height = texture.width(), texture.height()
        self.sprite(painter, 'haloGlyph-1', end, width, height, self.colors.skin)

    def draw_limbs(self, painter, scene, alpha, upper, lower, direction, hands):
        c = self.colors
        side = perpendicular(direction)
        points = scene.appearance.hands if hands else scene.appearance.feet
        for sign, p in zip((-1, 1), points):
            end = p.sample(alpha)
            if hands:
                # 沿身体轴抬高袖根，倾斜时仍与衣领保持同样的相对位置。
                shoulder = upper+side*(sign*HangingHand.SHOULDER_HALF)+direction*self.SLEEVE_ROOT_RISE
                self.draw_hand(painter, end)
                # 对应 Gown.Color(0.4) / Color(0)，从现有衣袍配色取色。
                # 原版顺序是先手掌再袖子，袖口自然覆盖靠手腕的一部分。
                self.transverse_strip(painter, self.sleeve_edges(shoulder, end, direction, sign),
                                      mixed(c.robe_top, c.robe_bottom, .4**2), c.robe_top)
            else:
                knee = lower.lerp(end, .5)+side*(4*sign)
                self.ribbon(painter, lower, lower.lerp(knee, .9), end.lerp(knee, .9),
                            end, 3.5, 1.6, c.skin, c.skin)
                self.sprite(painter, 'haloGlyph-1', end, 4, 4, c.skin,
                            degrees(atan2(direction.x, -direction.y)))

    @staticmethod
    def gown_point(cloth, n, u, v):
        """与衣袍三角形相同的重心插值，让领边随布料变形。"""
        if not 0 <= u <= 1:
            # 只为跨到袖根的领端沿布料边缘方向外推；实际覆盖范围稍后
            # 由衣袍/袖根轮廓裁剪。先取合法采样点，避免负索引读到另一行。
            edge = 0. if u < 0 else 1.
            inside = 1/(n-1) if u < 0 else 1-1/(n-1)
            a = OracleRenderer.gown_point(cloth, n, edge, v)
            b = OracleRenderer.gown_point(cloth, n, inside, v)
            return a+(a-b)*(abs(u-edge)*(n-1))
        x, y = u*(n-1), v*(n-1)
        ix, iy = min(n-2, int(x)), min(n-2, int(y))
        fx, fy = x-ix, y-iy
        a, b = cloth[iy*n+ix:iy*n+ix+2]
        d, e = cloth[(iy+1)*n+ix:(iy+1)*n+ix+2]
        return (a*(1-fx)+b*(fx-fy)+e*fy if fy <= fx
                else a*(1-fy)+e*fx+d*(fy-fx))

    @staticmethod
    @lru_cache(maxsize=32)
    def neck_uv(n, half, depth, clip_to_gown):
        # 领口顶部沿原有网格边；V 的两边在网格边界/对角线处分段。
        # 不重建物理网格，也不使用固定在屏幕上的三角形遮盖。
        if clip_to_gown:
            corners = [(max(0., .5-half), 0.), (min(1., .5+half), 0.)]
            if half > .5:
                corners.append((1., depth*(1-.5/half)))
            corners.append((.5, depth))
            if half > .5:
                corners.append((0., depth*(1-.5/half)))
        else:
            corners = [(.5-half, 0.), (.5+half, 0.), (.5, depth)]
        uv = [corners[0]]
        for a, b in zip(corners, corners[1:]+corners[:1]):
            cuts = {1.}
            for start, end in ((a[0], b[0]), (a[1], b[1]), (a[0]-a[1], b[0]-b[1])):
                if abs(end-start) > 1e-9:
                    cuts.update(t for i in range(-(n-1), n)
                                if 0 < (t := (i/(n-1)-start)/(end-start)) < 1)
            uv.extend((a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t) for t in sorted(cuts))
        return tuple(uv)

    def neck_opening(self, cloth, n, half, depth, *, clip_to_gown=True):
        uv = self.neck_uv(n, half, depth, clip_to_gown)
        path = QPainterPath()
        path.addPolygon(QPolygonF([point(self.gown_point(cloth, n, u, v)) for u, v in uv]))
        path.closeSubpath()
        return path

    def draw_inner_robe(self, painter, upper, lower, direction, head):
        # 内搭直接使用身体原有的胸肩/躯干贴图和颈部线段，不另造固定轮廓。
        # 领口距头部保持固定距离，随真实头颈伸缩、偏转，并保持平直截面。
        c = self.colors
        rotation = degrees(atan2(direction.x, -direction.y))
        self.sprite(painter, 'Circle20', lower, 12, 12, c.inner_robe, rotation)
        self.sprite(painter, 'Circle20', upper-direction*(self.CHEST_TOP_DROP*.5),
                    12, 16-self.CHEST_TOP_DROP, c.inner_robe, rotation)
        self.line(painter, upper, head, c.inner_robe, 2*self.INNER_NECK_HALF)
        neck = unit(head-upper, direction)
        side = perpendicular(neck)
        collar = head-neck*self.INNER_NECK_HEAD_GAP
        coverage = QPainterPath()
        coverage.addPolygon(QPolygonF([point(p) for p in (
            collar-side*24, collar+side*24,
            collar+side*24+neck*50, collar-side*24+neck*50)]))
        coverage.closeSubpath()
        painter.save()
        painter.setClipPath(coverage, Qt.ClipOperation.IntersectClip)
        # 只在领口以上画皮肤，避免颈部抗锯齿边缘透出底层肤色细线。
        self.line(painter, upper, head, c.skin, 2*self.INNER_NECK_HALF)
        painter.restore()

    def draw_gown(self, painter, scene, alpha):
        c, n = self.colors, scene.appearance.CLOTH_DIVS
        color_key = (c.robe_top, c.robe_bottom, n)
        if color_key != self._gown_colors_key:
            self._gown_colors = tuple(mixed(c.robe_top, c.robe_bottom, (y/(n-1))**2) for y in range(n))
            self._gown_colors_key = color_key
        cloth = [p.sample(alpha) for p in scene.appearance.cloth]
        vertices = [point(p) for p in cloth]
        painter.save()
        # 外轮廓单独抗锯齿。内部三角形关闭边缘抗锯齿，避免重复混合透出
        # 背景，造成静止时也能看到整片三角形接缝的伪“网格纹理”。
        outline = (cloth[:n] + [cloth[y*n+n-1] for y in range(1, n)]
                   + list(reversed(cloth[(n-1)*n:(n-1)*n+n-1])))
        outline += [cloth[y*n] for y in range(n-2, 0, -1)]
        outer = QPainterPath()
        outer.addPolygon(QPolygonF([point(p) for p in outline]))
        outer.closeSubpath()
        opening = self.neck_opening(cloth, n, self.GOWN_NECK_HALF, self.GOWN_NECK_DEPTH)
        trim = self.neck_opening(cloth, n, self.GOWN_TRIM_HALF, self.GOWN_TRIM_DEPTH,
                                 clip_to_gown=False)
        # 同时裁掉轮廓底色和内部网格，内搭才会从真实开口露出。
        painter.setClipPath(outer.subtracted(opening), Qt.ClipOperation.IntersectClip)
        gradient = QLinearGradient(point(cloth[n//2]), point(cloth[-n+n//2]))
        gradient.setColorAt(0, QColor(c.robe_top))
        gradient.setColorAt(1, QColor(c.robe_bottom))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([point(p) for p in outline]))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for y in range(n-1):
            top, bottom = self._gown_colors[y:y+2]
            for x in range(n-1):
                a, b = cloth[y*n+x:y*n+x+2]
                d, e = cloth[(y+1)*n+x:(y+1)*n+x+2]
                gradient = QLinearGradient(point(a.lerp(b, .5)), point(d.lerp(e, .5)))
                gradient.setColorAt(0, top)
                gradient.setColorAt(1, bottom)
                painter.setBrush(gradient)
                painter.setPen(Qt.PenStyle.NoPen)
                i, j = y*n+x, (y+1)*n+x
                painter.drawPolygon(QPolygonF([vertices[i], vertices[i+1], vertices[j+1]]))
                painter.drawPolygon(QPolygonF([vertices[i], vertices[j+1], vertices[j]]))
        painter.restore()
        return opening, trim.subtracted(opening), outer

    def draw_collar(self, painter, scene, alpha, upper, direction, trim, gown):
        # 领边最后覆盖袖根；允许跨越衣袍边缘，但不能新增肩部外轮廓。
        coverage = gown
        side = perpendicular(direction)
        for sign, hand in zip((-1, 1), scene.appearance.hands):
            shoulder = upper+side*(sign*HangingHand.SHOULDER_HALF)+direction*self.SLEEVE_ROOT_RISE
            edges = self.sleeve_edges(shoulder, hand.sample(alpha), direction, sign)
            # 每个采样点有两个截面；前六个截面覆盖袖子曲线最靠肩的 1/3。
            coverage = coverage.united(self.strip_path(edges[:6]))
        painter.save()
        painter.setClipPath(coverage, Qt.ClipOperation.IntersectClip)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.colors.collar_trim))
        painter.drawPath(trim)
        painter.restore()

    def bead_images(self):
        if self._bead_key != self.colors.beads:
            base = QColor(self.colors.beads)
            small = QImage(2, 2, QImage.Format.Format_ARGB32_Premultiplied)
            small.fill(base)
            small.setPixelColor(1, 0, QColor('#ffffff'))
            large = QImage(3, 3, QImage.Format.Format_ARGB32_Premultiplied)
            large.fill(Qt.GlobalColor.transparent)
            for x, y in ((1, 0), (0, 1), (2, 1), (1, 2)):
                large.setPixelColor(x, y, base)
            large.setPixelColor(1, 1, mixed(self.colors.beads, '#163c42', .55))
            self._bead_key, self._bead_images = self.colors.beads, (small, large)
        return self._bead_images

    def draw_necklace(self, painter, scene, alpha):
        # 单独一层，只读插值；项链摆动不使整片衣袍/袖子缓存失效。
        positions = [p.sample(alpha) for p in scene.appearance.necklace]
        painter.save()
        # 隐藏承重细绳，保留短链物理及珠子之间的距离约束。
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        images = self.bead_images()
        beads = positions[1:-1]
        for i, center in enumerate(beads):
            # 两侧各为方珠/十字珠/方珠；移除正中央十字珠后仍左右对称。
            image = images[min(i, len(beads)-1-i) % 2]
            size = image.width()
            # 珠子固定朝向，保持右上高光和十字轮廓，不追随绳段切线旋转。
            painter.drawImage(QRectF(center.x-size/2, center.y-size/2, size, size), image)
        painter.restore()

    def draw_head(self, painter, head, upper, direction, look, openness=0., *, pixelated=False,
                  raster_scale=1.):
        head_direction = unit(head-upper, direction)
        side_axis = perpendicular(head_direction)
        gx = max(-1., min(1., look.x*side_axis.x+look.y*side_axis.y))
        gy = max(-1., min(1., look.x*head_direction.x+look.y*head_direction.y))
        angle = degrees(atan2(head_direction.x, -head_direction.y))
        # 消除世界坐标相减的浮点尾差，避免纯平移跨过恰好落在像素边界
        # 的栅格判定。精度远小于可见角度，不按帧保存或推进朝向状态。
        gx, gy, angle = round(gx, 6), round(gy, 6), round(angle, 5)
        openness = max(0., min(1., openness))
        density = pixel_density('adaptive', raster_scale)
        geometry_key = (gx, gy, openness, self.colors)
        if geometry_key != self._head_geometry_key:
            commands = PaintCommands()
            self.draw_head_parts(commands, gx, gy, openness)
            self._head_geometry_key, self._head_frame = geometry_key, commands
        key = (geometry_key, angle, density)
        if key != self._head_key:
            # 在当前显示精度下完成投影、倾斜和遮挡。几何与倍率分离，
            # 世界平移不重建小图；旋转也只重放已有的面部矢量图形。
            pixels = ceil(self.HEAD_PIXELS*density)
            image = QImage(pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            local = QPainter(image)
            try:
                local.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                local.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
                local.translate(pixels/2, pixels/2)
                local.scale(density, density)
                local.rotate(angle)
                self._head_frame.replay(local)
            finally:
                local.end()
            self._head_key, self._head_image = key, image
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        size = self._head_image.width()/density
        x, y = head.x-size/2, head.y-size/2
        if pixelated:
            # 与躯干图层使用同一世界像素网格；只对最终图像落点取整。
            x, y = floor(x*density+.5)/density, floor(y*density+.5)/density
        painter.drawImage(QRectF(x, y, size, size), self._head_image)
        painter.restore()

    def phone_segments(self, sign, gx, gy):
        """耳侧浅深度刚性架：返回投影后的直杆和两根向内的短横杆。"""
        top, bottom = self.PHONE_ROD_TOP, self.PHONE_ROD_BOTTOM
        yaw, pitch = radians(gx*35), radians(gy*20)
        ear = Vec2(sign*(7-2*abs(gx)), 0)
        def project(y, inward=0.):
            t = (y-top)/(bottom-top)
            # 竖杆微向内倾，同时底端稍靠前；偏航后两侧倾角不同。
            x = sign*(.25-self.PHONE_ROD_INSET*t-inward)
            z = self.PHONE_ROD_DEPTH*(t-.5)
            depth = -x*sin(yaw)+z*cos(yaw)
            return ear+Vec2(x*cos(yaw)+z*sin(yaw), y*cos(pitch)-depth*sin(pitch))
        # 横杆在局部平面垂直于竖杆，而非投影后硬画成屏幕水平线。
        height = bottom-top
        rise = (self.PHONE_ROD_INSET*self.PHONE_BAR_LENGTH*height
                / (height*height+self.PHONE_ROD_INSET**2+self.PHONE_ROD_DEPTH**2))
        segments = [(project(top), project(bottom))]
        for y in (bottom-self.PHONE_BAR_SPACING, bottom):
            segments.append((project(y), project(y-rise, self.PHONE_BAR_LENGTH)))
        return segments

    def draw_head_parts(self, painter, gx, gy, openness=0.):
        c = self.colors
        head_rect = QRectF(-50/9, -50/11-self.HEAD_CROWN_RISE,
                          100/9, 100/11+self.HEAD_CROWN_RISE)
        def phone(sign):
            ear = Vec2(sign*(7-2*abs(gx)), 0)
            painter.setPen(QPen(QColor(c.head_shell), 1., Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.SquareCap))
            for start, end in self.phone_segments(sign, gx, gy):
                painter.drawLine(point(start), point(end))
            w = 3.5+1.5*abs(gx)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.head_shell))
            painter.drawEllipse(QRectF(ear.x-w/2, ear.y-2.75, w, 5.5))
            painter.setBrush(QColor(c.head_highlight))
            painter.drawEllipse(QRectF(ear.x-w*.4, ear.y-2.2, w*.8, 4.4))
            painter.setBrush(QColor(c.joints))
            painter.drawRect(QRectF(ear.x+sign*.5-.325, ear.y+.3-1.4, .65, 2.8))
        # 原版 PhoneSprite 的近侧与转头方向相反；否则转头一侧的耳壳
        # 会盖掉已经向该侧移动的眼睛，而背后的附件反倒浮在脸上。
        near = -1 if gx >= 0 else 1
        phone(-near)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.skin))
        painter.drawEllipse(head_rect)
        painter.drawEllipse(QRectF(gx*2-10/3, 1.8-10/3, 20/3, 20/3))
        painter.setBrush(QColor(c.eyes))
        for sign in (-1, 1):
            # Bell 双眼相对原版沿面部局部向下平移 1，随头部一起旋转。
            eye = Vec2(max(-5., min(5., gx*3+2.5*sign)), 2-gy*3)
            # 原版 InverseLerp：正面及轻微侧视保留宽 2，超过半侧视后
            # 对应一眼逐渐缩至 1。闭眼高 1，完全睁眼高 2；保持二值像素轮廓。
            foreshortening = max(0., min(1., (sign*gx-.5)*2))
            width = self.OPEN_EYE_WIDTH-foreshortening
            height = 1+(self.OPEN_EYE_HEIGHT-1)*openness
            painter.drawRect(QRectF(eye.x-width/2, eye.y-height/2, width, height))
        mark = Vec2(gx*2.5, self.FOREHEAD_CENTER_Y-gy*1.5)
        # Bell 两侧的小标记与额头图案共享面部坐标和透视，不增加物理节点。
        # 大幅侧视时让标记自然隐入头部轮廓，避免像附件一样突出脸侧。
        face = QPainterPath()
        face.addEllipse(head_rect)
        painter.save()
        painter.setClipPath(face, Qt.ClipOperation.IntersectClip)
        sx, sy = 1-abs(gx)*.25, 1-max(0., gy)*.75
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.third_eye))
        for row, cells in enumerate(self.FOREHEAD_PIXELS):
            for column, cell in enumerate(cells):
                if cell == '#':
                    painter.drawRect(QRectF(mark.x+(column-2.5)*sx,
                                            mark.y+(row-2.5)*sy, sx, sy))
        for sign in (-1, 1):
            for down in self.FACE_DOT_Y_OFFSETS:
                dot = mark+Vec2(sign*self.FACE_DOT_HALF_SPACING*sx, down*sy)
                width, height = self.FACE_DOT_SIZE*sx, self.FACE_DOT_SIZE*sy
                painter.drawRect(QRectF(dot.x-width/2, dot.y-height/2, width, height))
        painter.restore()
        phone(near)

    def draw(self, painter: QPainter, scene, alpha=1., skeleton=False, *, cords=True, pixelated=True,
             raster_scale=None):
        density = painter_density(painter, scene.config.pixel_mode, raster_scale)
        self.draw_halo(painter, scene, alpha, raster_scale=density)
        # 珍珠独立于昂贵的人偶/线缆帧缓存；人偶休眠时珠子仍能独自运动。
        self.draw_pearl(painter, scene, alpha)
        app = scene.appearance
        eye_alpha = alpha
        if app.sleeping:
            alpha = 1.
        key = (app, app.revision, alpha, self.colors, self.atlas, cords)
        if key != self._frame_key:
            commands = PaintCommands()
            self.draw_geometry(commands, scene, alpha, cords=cords, cache_body=True, pearl=False,
                               include_head=False, halo=False)
            self._frame_key, self._frame = key, commands
        # 几何帧与显示倍率无关；倍率只影响局部光栅缓存。放大镜可指定
        # 主视图的 raster_scale，查看主视图已有的像素而不是重新细分。
        # 非像素路径仅供几何缓存的回归对照；正常入口默认启用像素绘制。
        if pixelated:
            self.draw_pixel_layer(painter, scene, density)
        else:
            self._frame.replay(painter)
        # 开合只刷新头部小图；身体休眠时不重建衣袍、机械臂或长线缆指令。
        self.draw_scene_head(painter, scene, alpha, eye_alpha, pixelated=pixelated,
                             raster_scale=density)
        if skeleton:
            self.draw_skeleton(painter, scene, alpha)

    def draw_pixel_layer(self, painter, scene, density=1.):
        """按显示精度绘制局部透明画布，保留硬像素边缘。"""
        key = (self._frame_key, density)
        if key != self._raster_key:
            # 包含真实线缆节点，不能用活动带裁掉自然下垂的线束。
            image, target = local_canvas(body_bounds(scene), density)
            local = QPainter(image)
            try:
                local.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                local.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
                local.scale(density, density)
                local.translate(-target.x(), -target.y())
                self._frame.replay(local)
            finally:
                local.end()
            self._raster_image = image
            self._raster_target = target
            self._raster_key = key
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(self._raster_target, self._raster_image)
        painter.restore()

    def draw_pearl(self, painter, scene, alpha):
        glyph_color = None
        if self.glyphs is not None and scene.config.projection_opacity > 0:
            color = QColor(self.colors.pearl_glyph)
            color.setAlphaF(scene.config.projection_opacity)
            # alpha 随颜色进入现有字形缓存；不改变画笔或珍珠本体的不透明度。
            glyph_color = color.name(QColor.NameFormat.HexArgb)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        if scene.pearl_matrix is not None:
            for p, glyph_id, slot in scene.pearl_matrix.samples(alpha):
                self.draw_pearl_at(painter, p, glyph_id, glyph_color, slot)
        if scene.pearl_orbits is not None:
            for p, glyph_id, slot in scene.pearl_orbits.samples(alpha):
                self.draw_pearl_at(painter, p, glyph_id, glyph_color, slot)
        for p, glyph_id, slot in scene.fixed_pearls.samples(alpha):
            self.draw_pearl_at(painter, p, glyph_id, glyph_color, slot)
        painter.restore()

    def draw_halo(self, painter, scene, alpha, *, raster_scale=None):
        if not scene.halo_visible:
            return
        halo = scene.halo
        density = painter_density(painter, scene.config.pixel_mode, raster_scale)
        # 光环自己动画；不进入身体/衣袍/线缆帧键。位移和透明度也不使
        # 局部图案失效，重复主视图与放大镜仅合成同一张小图。
        key = (halo, halo.revision, alpha, self.colors.pearl_glyph, density)
        if key != self._halo_key:
            scale, push, detail_scale = halo.geometry_at(alpha)
            # 预留范围可很大，实际只栅格化当前外形，避免小光环也清空最大画布。
            radius = int((5.5+push)*10*scale+5*detail_scale+3)
            pixels = ceil(radius*density)
            image = QImage(pixels*2+1, pixels*2+1, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            local = QPainter(image)
            try:
                local.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                local.translate(pixels, pixels)
                local.scale(density, density)
                local.setPen(Qt.PenStyle.NoPen)
                local.setBrush(QColor(self.colors.pearl_glyph))
                for index in range(2):
                    r = (3+index+push)*10*scale
                    white = halo.white_at(alpha) if index == 0 else 0.
                    inner = max(0., r-3*detail_scale)*(1-white)
                    # VectorCircle 的 alpha 编码环宽；真实投影透明度在整层合成时应用。
                    # 奇偶填充留下透明空洞，不能用背景色覆盖，以兼容透明桌面。
                    path = QPainterPath()
                    path.setFillRule(Qt.FillRule.OddEvenFill)
                    path.addEllipse(QPointF(), r, r)
                    if inner > 0:
                        path.addEllipse(QPointF(), inner, inner)
                    local.drawPath(path)
                for index, (ring, row) in enumerate(zip(halo.rings, halo.bits)):
                    r = (3.5+index+push)*10*scale
                    angle = ring.previous+(ring.angle-ring.previous)*alpha
                    for i, bit in enumerate(row):
                        fill = bit.fill_at(alpha)
                        if fill <= 0:
                            continue
                        theta = radians(angle+i*360/len(row))
                        dx, dy = sin(theta), -cos(theta)
                        # 原版矩形宽 4、长 8*Fill，长轴沿半径；先在局部
                        # 光环画布栅格化，再整体按投影透明度合成，交点不加深。
                        half = fill*4*detail_scale
                        width = 2*detail_scale
                        near, far = r-half, r+half
                        local.drawPolygon(QPolygonF([
                            QPointF(dx*near-dy*width, dy*near+dx*width),
                            QPointF(dx*near+dy*width, dy*near-dx*width),
                            QPointF(dx*far+dy*width, dy*far-dx*width),
                            QPointF(dx*far-dy*width, dy*far+dx*width)]))
            finally:
                local.end()
            self._halo_key, self._halo_image = key, image
        center = halo.center_at(alpha)
        image = self._halo_image
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.setOpacity(painter.opacity()*scene.config.projection_opacity)
        painter.drawImage(QRectF(floor(center.x*density-image.width()/2+.5)/density,
                                floor(center.y*density-image.height()/2+.5)/density,
                                image.width()/density, image.height()/density), image)
        painter.restore()

    def pearl_palette(self):
        if self._pearl_palette_key != self.colors:
            colors = (self.colors.pearl_primary, self.colors.pearl, self.colors.pearl_secondary)
            palette = []
            for value in colors:
                color = QColor(value)
                # DataPearl 无闪烁/无暗度时的高光：Lerp(珠体色 * 1.3, 白, .5)。
                highlight = QColor.fromRgbF(*(min(1., channel*.65+.5) for channel in
                                               (color.redF(), color.greenF(), color.blueF())))
                palette.append((value, highlight.name()))
            self._pearl_palette = tuple(palette)
            self._pearl_palette_key = self.colors
        return self._pearl_palette

    def draw_pearl_at(self, painter, p, glyph_id, glyph_color, color_slot):
        if glyph_color is not None:
            # 原版标签左下角锚在珠心。Qt 的 y 向下，15px 单元上移一格高度。
            glyph = self.glyphs.sprite(glyph_id, glyph_color)
            painter.drawImage(QPointF(round(p.x), round(p.y)-15), glyph)
        color, highlight = self.pearl_palette()[color_slot]
        self.sprite(painter, 'JetFishEyeA', p, 6, 6, color)
        self.sprite(painter, 'tinyStar', p+Vec2(-.5, -1.5), 3, 3, highlight)

    def draw_scene_head(self, painter, scene, alpha, eye_alpha=None, *, pixelated=False, raster_scale=None):
        app = scene.appearance
        upper, lower = [p.previous_position.lerp(p.position, alpha) for p in scene.body.chunks]
        sway = app.previous_sway+(app.sway-app.previous_sway)*alpha
        direction = rotate(unit(upper-lower), sway)
        look = scene.previous_look_direction.lerp(scene.look_direction, alpha)
        self.draw_head(painter, app.head.sample(alpha), upper, direction, look,
                       scene.eyes.sample(alpha if eye_alpha is None else eye_alpha), pixelated=pixelated,
                       raster_scale=painter_density(painter, scene.config.pixel_mode, raster_scale))

    def draw_geometry(self, painter, scene, alpha=1., *, cords=True, cache_body=False, pearl=True,
                      include_head=True, halo=True, arm=True):
        if halo:
            self.draw_halo(painter, scene, alpha)
        if pearl:
            self.draw_pearl(painter, scene, alpha)
        app = scene.appearance
        upper, lower = [p.previous_position.lerp(p.position, alpha) for p in scene.body.chunks]
        sway = app.previous_sway+(app.sway-app.previous_sway)*alpha
        direction = rotate(unit(upper-lower), sway)
        lower = upper-direction*9
        head = app.head.sample(alpha)
        if arm:
            self.draw_arm(painter, scene, alpha)
        if cords:
            self.draw_cords(painter, scene, alpha)
        look = scene.previous_look_direction.lerp(scene.look_direction, alpha)
        if cache_body:
            # 匀速平移时不重建衣袍/袖子网格。只容忍 0.001 的亚像素变化；
            # 参考姿态不跟随容差更新，累计形变仍使缓存失效。
            pose = [direction.x, direction.y, look.x, look.y]
            for p in (app.head, *app.hands, *app.feet, *app.cloth):
                v = p.sample(alpha)
                pose.extend((v.x-upper.x, v.y-upper.y))
            key = (app, self.colors, self.atlas)
            if (key != self._body_key or len(pose) != len(self._body_pose)
                    or any(abs(a-b) > .001 for a, b in zip(pose, self._body_pose))):
                self._body_frame = PaintCommands()
                self.draw_body(self._body_frame, scene, alpha, upper, lower, direction, head, look)
                self._body_front_frame = PaintCommands()
                self.draw_body_front(self._body_front_frame, scene, alpha, upper, lower, direction, head, look,
                                     include_head=False)
                self._body_key, self._body_pose, self._body_origin = key, pose, upper
            offset = upper-self._body_origin
            painter.save()
            painter.translate(offset.x, offset.y)
            self._body_frame.replay(painter)
            painter.restore()
            self.draw_necklace(painter, scene, alpha)
            painter.save()
            painter.translate(offset.x, offset.y)
            self._body_front_frame.replay(painter)
            painter.restore()
        else:
            self.draw_body(painter, scene, alpha, upper, lower, direction, head, look)
            self.draw_necklace(painter, scene, alpha)
            self.draw_body_front(painter, scene, alpha, upper, lower, direction, head, look, include_head=False)
        if include_head:
            self.draw_head(painter, head, upper, direction, look, scene.eyes.sample(alpha),
                           raster_scale=painter_density(painter, scene.config.pixel_mode))

    def draw_body(self, painter, scene, alpha, upper, lower, direction, head, look):
        self.draw_inner_robe(painter, upper, lower, direction, head)
        self.draw_limbs(painter, scene, alpha, upper, lower, direction, hands=False)
        opening, trim, gown = self.draw_gown(painter, scene, alpha)
        # 袖根也是外衣的一部分，不能填回已经挖出的领口。下方手腕仍保留
        # 手掌先画、袖口后盖的原有结构；项链随后覆盖上胸衣料。
        sleeves = QPainterPath()
        sleeves.addRect(QRectF(upper.x-30, upper.y-30, 60, 60))
        painter.save()
        painter.setClipPath(sleeves.subtracted(opening), Qt.ClipOperation.IntersectClip)
        self.draw_limbs(painter, scene, alpha, upper, lower, direction, hands=True)
        painter.restore()
        self.draw_collar(painter, scene, alpha, upper, direction, trim, gown)

    def draw_body_front(self, painter, scene, alpha, upper, lower, direction, head, look, *, include_head=True):
        # 手掌仍在念珠前；只重放袖口外的可见部分，避免再次把手腕盖到袖子上。
        side = perpendicular(direction)
        for sign, hand in zip((-1, 1), scene.appearance.hands):
            end = hand.sample(alpha)
            shoulder = upper+side*(sign*HangingHand.SHOULDER_HALF)+direction*self.SLEEVE_ROOT_RISE
            edges = self.sleeve_edges(shoulder, end, direction, sign)
            sleeve = self.strip_path(edges)
            palm = QPainterPath()
            palm.addRect(QRectF(end.x-6, end.y-6, 12, 12))
            painter.save()
            painter.setClipPath(palm.subtracted(sleeve), Qt.ClipOperation.IntersectClip)
            self.draw_hand(painter, end)
            painter.restore()
        if include_head:
            self.draw_head(painter, head, upper, direction, look, scene.eyes.sample(alpha))

    def draw_skeleton(self, painter, scene, alpha):
        pen = QPen(QColor('#8befcc'), 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        nodes = [p.previous_position.lerp(p.position, alpha) for p in scene.body.chunks]
        painter.drawLine(point(nodes[0]), point(nodes[1]))
        for c, position in zip(scene.body.chunks, nodes):
            painter.drawEllipse(point(position), c.radius, c.radius)
        head = scene.appearance.head.sample(alpha)
        painter.drawLine(point(nodes[0]), point(head))
        painter.drawEllipse(point(head), 5, 5)
        for p in scene.appearance.hands+scene.appearance.feet:
            painter.drawEllipse(point(p.sample(alpha)), 2, 2)
        for j in scene.arm.joints:
            painter.drawEllipse(point(j.previous_position.lerp(j.position, alpha)), 4, 4)
