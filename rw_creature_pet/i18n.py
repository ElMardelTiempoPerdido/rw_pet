"""Qt 翻译及现有控件的原位文字刷新，不重建窗口或业务对象。"""
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QObject, QTranslator, Signal
from PySide6.QtWidgets import (QAbstractButton, QApplication, QLabel, QLineEdit, QSpinBox,
                               QDoubleSpinBox, QTabBar, QTabWidget, QToolButton, QWidget)

from .shared.messages import Message


TRANSLATIONS = Path(__file__).with_name('translations')


def tr(message, **values):
    if isinstance(message, BaseException):
        message = message.args[0] if len(message.args) == 1 else str(message)
    if isinstance(message, Message):
        source, values = message.source, message.values
    else:
        source = str(message)
    translated = QCoreApplication.translate('BellPet', source)
    return translated.format(**{key: tr(value) if isinstance(value, (Message, BaseException)) else value
                                for key, value in values.items()}) if values else translated


class LanguageManager(QObject):
    changed = Signal()

    def __init__(self, app):
        super().__init__(app)
        self.language = 'zh'
        self.translator = self.qt_translator = None

    def set_language(self, language):
        if language not in ('zh', 'en'):
            raise ValueError('unsupported UI language')
        if language == self.language and self.qt_translator is not None:
            return
        app = QApplication.instance()
        translator = QTranslator(self)
        if language == 'en' and not translator.load(str(TRANSLATIONS/'en.qm')):
            translator.deleteLater()
            raise RuntimeError('English translation file is missing or invalid: en.qm')
        for old in (self.translator, self.qt_translator):
            if old is not None:
                app.removeTranslator(old)
                old.deleteLater()
        self.language = language
        self.translator = translator
        self.qt_translator = QTranslator(self)
        if language == 'en':
            app.installTranslator(translator)
        else:
            paths = (TRANSLATIONS, Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)))
            for path in paths:
                if self.qt_translator.load(str(path/'qtbase_zh_CN.qm')):
                    app.installTranslator(self.qt_translator)
                    break
        self.changed.emit()


def language_manager():
    app = QApplication.instance()
    if not hasattr(app, '_pet_language_manager'):
        app._pet_language_manager = LanguageManager(app)
    return app._pet_language_manager


class WidgetTexts:
    """在首次翻译前登记静态文字；不登记输入值、颜色按钮值或动态状态。"""
    def __init__(self, root, *, exclude=()):
        self.bindings = []
        for widget in [root, *root.findChildren(QWidget)]:
            if widget in exclude:
                continue
            if isinstance(widget, QToolButton) and isinstance(widget.parentWidget(), QTabBar):
                continue  # Qt 自带的标签栏滚动按钮由 qtbase 翻译，不能按 BellPet 原文覆盖。
            properties = [('toolTip', 'setToolTip'), ('accessibleName', 'setAccessibleName')]
            if widget is root:
                properties.append(('windowTitle', 'setWindowTitle'))
            if isinstance(widget, (QLabel, QAbstractButton)):
                properties.append(('text', 'setText'))
            if isinstance(widget, QLineEdit):
                properties.append(('placeholderText', 'setPlaceholderText'))
            if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                properties.append(('suffix', 'setSuffix'))
            for getter, setter in properties:
                source = getattr(widget, getter)()
                if any('\u4e00' <= char <= '\u9fff' for char in source):
                    self.bindings.append((getattr(widget, setter), source))
            if isinstance(widget, QTabWidget):
                for index in range(widget.count()):
                    self.bindings.append((lambda text, w=widget, i=index: w.setTabText(i, text), widget.tabText(index)))

    def retranslate(self):
        for setter, source in self.bindings:
            setter(tr(source))
