"""设置窗口专用的灰阶像素皮肤，不改变桌宠、工具栏或其他 Qt 窗口。"""
import os
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPen, QPolygon
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QProxyStyle, QStyle, QStyleFactory, QWidget


PAPER = QColor('#e9e9e9')
INK = QColor('#707070')
MUTED = QColor('#aaaaaa')


@lru_cache(maxsize=2)
def pixel_font_family(language='zh'):
    # 使用系统宋体的点阵字形，不把 Windows 字体复制进发行包。
    filename, fallback = ('tahoma.ttf', 'Tahoma') if language == 'en' else ('simsun.ttc', 'SimSun')
    font_path = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'/filename
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            return families[0]
    return fallback


def pixel_font(language='zh'):
    font = QFont(pixel_font_family(language))
    font.setPixelSize(14)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.PreferBitmap)
    return font


def pixel_box(painter, rect, *, fill=PAPER, border=INK, radius=4):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(QPen(border, 1))
    painter.setBrush(fill)
    painter.drawRoundedRect(QRectF(rect).adjusted(.5, .5, -.5, -.5), radius, radius)
    painter.restore()


class PixelRule(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(3)

    def paintEvent(self, event):
        painter = QPainter(self)
        for x in range(0, self.width(), 6):
            painter.fillRect(x, 1, 2, 2, INK)


class PixelRuleThin(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(2)

    def paintEvent(self, event):
        painter = QPainter(self)
        for x in range(0, self.width(), 6):
            painter.fillRect(x, 1, 2, 2, INK)


class SettingsStyle(QProxyStyle):
    """保留 Qt 的输入与布局行为，只替换可见边框、标记和选中状态。"""
    def __init__(self, parent):
        super().__init__(QStyleFactory.create('Fusion'))
        self.setParent(parent)

    @staticmethod
    def inverted(option, widget=None):
        return bool(option.state & QStyle.StateFlag.State_Enabled and (
            option.state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Sunken
                            | QStyle.StateFlag.State_On | QStyle.StateFlag.State_Selected)
            or (widget is not None and widget.property('primary'))))

    def drawPrimitive(self, element, option, painter, widget=None):
        pe = QStyle.PrimitiveElement
        if (element in (pe.PE_PanelLineEdit, pe.PE_FrameLineEdit) and widget is not None
                and isinstance(widget.parentWidget(), QAbstractSpinBox)):
            return  # 数字框由 CC_SpinBox 统一画外边框，内部编辑器不再叠一层。
        if element in (pe.PE_PanelButtonCommand, pe.PE_PanelLineEdit, pe.PE_FrameLineEdit,
                       pe.PE_FrameTabWidget):
            inverse = element == pe.PE_PanelButtonCommand and self.inverted(option, widget)
            border = INK if option.state & QStyle.StateFlag.State_Enabled else MUTED
            pixel_box(painter, option.rect, fill=INK if inverse else PAPER, border=border)
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
            painter.setPen(QPen(color, 1))
            painter.setBrush(PAPER)
            painter.drawEllipse(option.rect.adjusted(1, 1, -2, -2))
            if option.state & QStyle.StateFlag.State_On:
                painter.setBrush(color)
                painter.drawEllipse(option.rect.adjusted(4, 4, -5, -5))
            painter.restore()
        elif element == pe.PE_FrameFocusRect:
            painter.save()
            painter.setPen(QPen(INK, 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(option.rect.adjusted(0, 0, -1, -1))
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
            color = PAPER if self.inverted(option, widget) else INK
            for role in (QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
                option.palette.setColor(QPalette.ColorGroup.Active, role, color)
                option.palette.setColor(QPalette.ColorGroup.Inactive, role, color)
            super().drawControl(element, option, painter, widget)
        elif element == ce.CE_SizeGrip:
            painter.save()
            painter.setPen(INK)
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
    dialog.setFont(pixel_font())
    dialog.pixel_style = SettingsStyle(dialog)
    # QWidget 的 style 不像字体/调色板那样继承；同一实例仅用于这个设置窗口。
    for combo in dialog.findChildren(QComboBox):
        combo.view().setPalette(palette)
        combo.view().setFont(dialog.font())
    for widget in (dialog, *dialog.findChildren(QWidget)):
        widget.setStyle(dialog.pixel_style)
        widget.setAttribute(Qt.WidgetAttribute.WA_Hover)
