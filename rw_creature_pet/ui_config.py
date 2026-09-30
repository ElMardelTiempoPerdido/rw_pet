"""界面偏好；auto 只用于初始化，运行与用户文件中保存确定的语言。"""
from dataclasses import dataclass

from .shared.messages import UserError


def system_language():
    from PySide6.QtCore import QLocale
    languages = QLocale.system().uiLanguages()
    # 只看首选界面语言，不能因备用语言列表含中文就选择中文。
    primary = languages[0].replace('_', '-').lower() if languages else ''
    return 'zh' if primary.split('-')[0] == 'zh' else 'en'


@dataclass(frozen=True, slots=True)
class UiConfig:
    language: str = 'auto'

    def __post_init__(self):
        if self.language not in ('auto', 'zh', 'en'):
            raise UserError('ui.language 必须为 auto、zh 或 en')
        if self.language == 'auto':
            try:
                language = system_language()
            except (RuntimeError, OSError):
                language = 'en'
            object.__setattr__(self, 'language', language)
