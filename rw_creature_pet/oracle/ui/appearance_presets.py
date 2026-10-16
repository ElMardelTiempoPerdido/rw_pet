"""外观入口，文件操作与角色设置复用同一组件"""
from ...presets.appearance import load_appearance
from ...presets.library import AppearanceLibrary
from .preset_panel import PresetPanel
from .preset_dialogs import AppearanceImportDialog

APPEARANCE_TEXTS = {
    'label': '外观配置', 'import_button': '导入外观到当前角色设置…', 'export_button': '导出当前角色的外观…',
    'hint': '*导入的外观数据将复制保存到当前角色设置中，即后续调整外观细节不会修改外观源文件',
    'read_error': '无法读取外观库：{error}', 'current': '当前外观（不关联文件）',
    'duplicates': '重复外观「{name}」，最新有效版本列在第一项：\n{paths}',
    'load_error': '无法载入外观：{error}', 'loaded': '已载入外观',
    'import_title': '导入外观', 'filter': '外观配置 (*.json)', 'import_error': '导入外观失败：{error}',
    'export_title': '导出外观', 'name': '外观名称', 'default_name': '我的外观',
    'export_error': '导出外观失败：{error}',
}


class AppearancePresetPanel(PresetPanel):
    def __init__(self, draft, apply, *, library=None):
        super().__init__(draft, apply, library=library or AppearanceLibrary(),
                         loader=load_appearance, texts=APPEARANCE_TEXTS, inline_selection=False)
        self.directory_button.hide()

    def choose_import(self):
        return AppearanceImportDialog(self).exec()
