"""外观预设入口，文件操作与完整预设复用同一组件"""
from ...presets.appearance import load_appearance
from ...presets.library import AppearanceLibrary
from .preset_panel import PresetPanel

APPEARANCE_TEXTS = {
    'label': '外观预设', 'import_button': '导入外观…', 'export_button': '导出外观…',
    'hint': '选择预设会填入外观参数，保存后生效；分享时请复制整个预设文件夹',
    'read_error': '无法读取外观库：{error}', 'current': '当前外观（不关联预设）',
    'duplicates': '重复外观「{name}」，使用日期最新的有效版本：\n{paths}',
    'load_error': '无法载入外观：{error}', 'loaded': '已载入外观，点击保存后生效',
    'import_title': '导入外观', 'filter': '外观配置 (*.json)', 'import_error': '导入外观失败：{error}',
    'export_title': '导出外观', 'name': '外观名称', 'default_name': '我的外观',
    'export_error': '导出外观失败：{error}',
}


class AppearancePresetPanel(PresetPanel):
    def __init__(self, draft, apply, *, library=None):
        super().__init__(draft, apply, library=library or AppearanceLibrary(),
                         loader=load_appearance, texts=APPEARANCE_TEXTS)
