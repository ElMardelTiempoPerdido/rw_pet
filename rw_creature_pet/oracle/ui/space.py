"""桌面和设置共用的屏幕空间说明"""
from PySide6.QtWidgets import QApplication

from ...i18n import tr
from ...shared.screens import preferred_screen
from ..space import SpaceAssessment


def selected_screen(selection):
    app = QApplication.instance()
    return preferred_screen(app.screens(), app.primaryScreen(), selection)


def screen_space(screen, scale, arm, fraction, edges):
    try:
        rect = screen.availableGeometry() if screen is not None else None
        dpr = screen.devicePixelRatio() if screen is not None else 1.
    except RuntimeError:
        return None
    if rect is None or rect.isEmpty():
        return None
    return SpaceAssessment(rect.width()*dpr/scale, rect.height()*dpr/scale, arm, fraction, edges)


def space_description(info, scale):
    text = tr('当前 {scale:g}× 对应约 {width:.0f} × {height:.0f} 逻辑像素',
              scale=scale, width=info.width, height=info.height)
    if not info.baseline_fits:
        text += '\n'+tr('此空间不适合机械臂 75% 与活动带 20% 的组合')
    text += '\n'+tr('当前组合可用' if info.valid else '当前组合空间不足，无法按所选倍率应用')
    recommendation = info.recommendation
    if recommendation is not None:
        arm, band = recommendation
        text += tr('；建议机械臂 {arm:g}%，活动带 {band:g}%', arm=round(arm*100, 2), band=round(band*100, 1))
    else:
        text += tr('；建议降低显示倍率以留出活动余量')
    return text
