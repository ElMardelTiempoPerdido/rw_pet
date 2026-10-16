"""设置窗口专用的灰阶像素皮肤，不改变桌宠、工具栏或其他 Qt 窗口"""
from functools import lru_cache
from math import floor

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPen, QPolygon
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QProxyStyle, QStyle, QStyleFactory, QWidget

from ...shared.paths import PACKAGE_ROOT

PAPER = QColor('#e9e9e9')
INK = QColor('#707070')
MUTED = QColor('#aaaaaa')
DESTRUCTIVE = QColor('#ad7770')
OUTLINE_WIDTH_PX = 2
RULE_DOT_WIDTH_PX = 2
RULE_DOT_GAP_PX = 4
SETTINGS_FONT_PATH = PACKAGE_ROOT/'fonts/WenQuanYi Bitmap Song 14px.ttf'
NOTE_STYLE = "font-size: 16px;color:#A1A1A1;"


def parameter_group_background(widget):
    """相关部件的轻微深底色分组，供监视者与附加外观共用"""
    palette = widget.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor('#d5d5d5'))
    widget.setPalette(palette)
    widget.setAutoFillBackground(True)


@lru_cache(maxsize=1)
def settings_font_family():
    # 使用程序资源，不依赖工作目录，也不要求用户把字体安装到系统
    font_id = QFontDatabase.addApplicationFont(str(SETTINGS_FONT_PATH))
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise RuntimeError(f'Cannot load settings font: {SETTINGS_FONT_PATH}')
    return families[0]


def settings_font():
    font = QFont(settings_font_family())
    font.setPixelSize(16)
    font.setWeight(QFont.Weight.Normal)
    # 关闭抗锯齿
    # font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
    return font


def _pixel_outline(painter, rect):
    """轴对齐的 UI 边框吸附到物理像素，线宽不随系统 DPI 放大"""
    transform = painter.deviceTransform()
    inverse, _ = transform.inverted()
    scale = abs(transform.m11())
    width = OUTLINE_WIDTH_PX
    bounds = transform.mapRect(QRectF(rect))
    left, top, right, bottom = (floor(value + .5) for value in
                               (bounds.left(), bounds.top(), bounds.right(), bounds.bottom()))
    # 按最终线宽内缩半个描边：奇数宽度落在半像素中心，偶数宽度落在整数中心
    bounds = QRectF(left, top, right-left, bottom-top).adjusted(width/2, width/2, -width/2, -width/2)
    return inverse.mapRect(bounds), width/scale


def pixel_box(painter, rect, *, fill=PAPER, border=INK, radius=4):
    if rect.isEmpty():
        return
    outline, width = _pixel_outline(painter, rect)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(QPen(border, width))
    painter.setBrush(fill)
    painter.drawRoundedRect(outline, radius, radius)
    painter.restore()


def pixel_rule(painter, rect, *, thickness=2):
    """点长、间距、厚度均在设备像素中指定，避免分数 DPI 下交替粗细"""
    transform = painter.deviceTransform()
    inverse, _ = transform.inverted()
    bounds = transform.mapRect(QRectF(rect))
    left, right = (floor(value+.5) for value in (bounds.left(), bounds.right()))
    y = floor(bounds.center().y()-thickness/2+.5)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    for x in range(left, right, RULE_DOT_WIDTH_PX+RULE_DOT_GAP_PX):
        dot = QRectF(x, y, min(RULE_DOT_WIDTH_PX, right-x), thickness)
        painter.fillRect(inverse.mapRect(dot), INK)
    painter.restore()


class PixelRule(QWidget):
    def __init__(self, *, thickness=2):
        super().__init__()
        self.thickness = thickness
        self.setFixedHeight(thickness+1)

    def paintEvent(self, event):
        painter = QPainter(self)
        pixel_rule(painter, self.rect(), thickness=self.thickness)


class PixelRuleThin(PixelRule):
    def __init__(self):
        super().__init__(thickness=2)


class SettingsStyle(QProxyStyle):
    """保留 Qt 的输入与布局行为，只替换可见边框、标记和选中状态"""
    def __init__(self, parent):
        super().__init__(QStyleFactory.create('Fusion'))
        self.setParent(parent)

    @staticmethod
    def inverted(option, widget=None):
        return bool(option.state & QStyle.StateFlag.State_Enabled and (
            option.state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Sunken
                            | QStyle.StateFlag.State_On | QStyle.StateFlag.State_Selected)
            or (widget is not None and widget.property('primary'))))

    @staticmethod
    def button_color(widget):
        return DESTRUCTIVE if widget is not None and widget.property('destructive') else INK

    def drawPrimitive(self, element, option, painter, widget=None):
        pe = QStyle.PrimitiveElement
        if (element in (pe.PE_PanelLineEdit, pe.PE_FrameLineEdit) and widget is not None
                and isinstance(widget.parentWidget(), QAbstractSpinBox)):
            return  # 数字框由 CC_SpinBox 统一画外边框，内部编辑器不再叠一层
        if element in (pe.PE_PanelButtonCommand, pe.PE_PanelLineEdit, pe.PE_FrameLineEdit,
                       pe.PE_FrameTabWidget):
            inverse = element == pe.PE_PanelButtonCommand and self.inverted(option, widget)
            color = self.button_color(widget) if element == pe.PE_PanelButtonCommand else INK
            border = color if option.state & QStyle.StateFlag.State_Enabled else MUTED
            pixel_box(painter, option.rect, fill=color if inverse else PAPER, border=border)
        elif element == pe.PE_IndicatorCheckBox:
            checked = bool(option.state & QStyle.StateFlag.State_On)
            color = INK if option.state & QStyle.StateFlag.State_Enabled else MUTED
            rect = option.rect.adjusted(0, 0, -1, -1)
            pixel_box(painter, rect, fill=color if checked else PAPER, border=color, radius=2)
            if checked:
                painter.save()
                painter.setPen(QPen(PAPER, 2))
                c = rect.center()
                painter.drawPolyline(QPolygon([c+QPoint(-3, 0), c+QPoint(-1, 3), c+QPoint(4, -4)]))
                painter.restore()
        elif element == pe.PE_IndicatorRadioButton:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            color = INK if option.state & QStyle.StateFlag.State_Enabled else MUTED
            outline, width = _pixel_outline(painter, option.rect.adjusted(1, 1, -2, -2))
            painter.setPen(QPen(color, width))
            painter.setBrush(PAPER)
            painter.drawEllipse(outline)
            if option.state & QStyle.StateFlag.State_On:
                painter.setBrush(color)
                painter.drawEllipse(option.rect.adjusted(4, 4, -5, -5))
            painter.restore()
        elif element == pe.PE_FrameFocusRect:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            outline, width = _pixel_outline(painter, option.rect)
            painter.setPen(QPen(INK, width, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(outline)
            painter.restore()
        else:
            super().drawPrimitive(element, option, painter, widget)

    def drawControl(self, element, option, painter, widget=None):
        ce = QStyle.ControlElement
        if element == ce.CE_TabBarTabShape:
            pixel_box(painter, option.rect.adjusted(0, 0, -3, -3),
                      fill=INK if self.inverted(option) else PAPER)
        elif element in (ce.CE_PushButtonLabel, ce.CE_TabBarTabLabel):
            option = type(option)(option)
            foreground = self.button_color(widget) if element == ce.CE_PushButtonLabel else INK
            color = PAPER if self.inverted(option, widget) else foreground
            for role in (QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
                option.palette.setColor(QPalette.ColorGroup.Active, role, color)
                option.palette.setColor(QPalette.ColorGroup.Inactive, role, color)
            super().drawControl(element, option, painter, widget)
        elif element == ce.CE_SizeGrip:
            painter.save()
            pen = QPen(INK, OUTLINE_WIDTH_PX)
            pen.setCosmetic(True)
            painter.setPen(pen)
            r = option.rect
            for offset in (3, 7, 11):
                painter.drawLine(r.right()-offset, r.bottom()-2, r.right()-2, r.bottom()-offset)
            painter.restore()
        else:
            super().drawControl(element, option, painter, widget)

    @staticmethod
    def arrow(painter, rect, *, up=False, color=INK):
        c = rect.center()
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        sign = -1 if up else 1
        painter.drawPolygon(QPolygon([c+QPoint(-3, -sign), c+QPoint(3, -sign), c+QPoint(0, 2*sign)]))
        painter.restore()

    def drawComplexControl(self, control, option, painter, widget=None):
        cc, sc = QStyle.ComplexControl, QStyle.SubControl
        if control in (cc.CC_ComboBox, cc.CC_SpinBox):
            enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
            pixel_box(painter, option.rect, border=INK if enabled else MUTED)
            buttons = ((sc.SC_ComboBoxArrow, False),) if control == cc.CC_ComboBox else (
                (sc.SC_SpinBoxUp, True), (sc.SC_SpinBoxDown, False))
            for part, up in buttons:
                rect = self.subControlRect(control, option, part, widget)
                hover = bool(enabled and option.activeSubControls & part
                             and option.state & QStyle.StateFlag.State_MouseOver)
                if hover:
                    pixel_box(painter, rect.adjusted(1, 1, -1, -1), fill=INK, radius=2)
                self.arrow(painter, rect, up=up, color=PAPER if hover else INK if enabled else MUTED)
        elif control == cc.CC_ScrollBar:
            painter.fillRect(option.rect, PAPER)
            if option.maximum <= option.minimum:
                return
            rect = self.subControlRect(control, option, sc.SC_ScrollBarSlider, widget)
            pixel_box(painter, rect.adjusted(3, 1, -3, -1), fill=INK, radius=3)
            for part, up in ((sc.SC_ScrollBarSubLine, True), (sc.SC_ScrollBarAddLine, False)):
                self.arrow(painter, self.subControlRect(control, option, part, widget), up=up)
        else:
            super().drawComplexControl(control, option, painter, widget)

    def sizeFromContents(self, content, option, size, widget=None):
        result = super().sizeFromContents(content, option, size, widget)
        if content == QStyle.ContentsType.CT_TabBarTab:
            return QSize(result.width()+14, max(34, result.height()+8))
        if content in (QStyle.ContentsType.CT_PushButton, QStyle.ContentsType.CT_ComboBox,
                       QStyle.ContentsType.CT_SpinBox, QStyle.ContentsType.CT_LineEdit):
            result.setHeight(max(30, result.height()))
        return result

    def pixelMetric(self, metric, option=None, widget=None):
        pm = QStyle.PixelMetric
        if metric in (pm.PM_IndicatorWidth, pm.PM_IndicatorHeight,
                      pm.PM_ExclusiveIndicatorWidth, pm.PM_ExclusiveIndicatorHeight):
            return 15
        if metric == pm.PM_CheckBoxLabelSpacing:
            return 10
        if metric == pm.PM_ScrollBarExtent:
            return 14
        return super().pixelMetric(metric, option, widget)


def apply_settings_style(dialog):
    palette = QPalette(dialog.palette())
    for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.Button):
        palette.setColor(role, PAPER)
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(role, INK)
        palette.setColor(QPalette.ColorGroup.Disabled, role, MUTED)
    palette.setColor(QPalette.ColorRole.Highlight, INK)
    palette.setColor(QPalette.ColorRole.HighlightedText, PAPER)
    dialog.setPalette(palette)
    dialog.setFont(settings_font())
    dialog.pixel_style = SettingsStyle(dialog)
    # QWidget 的 style 不像字体/调色板那样继承；同一实例仅用于这个设置窗口
    for combo in dialog.findChildren(QComboBox):
        combo.view().setPalette(palette)
        combo.view().setFont(dialog.font())
    for widget in (dialog, *dialog.findChildren(QWidget)):
        widget.setStyle(dialog.pixel_style)
        widget.setAttribute(Qt.WidgetAttribute.WA_Hover)
