"""可延迟翻译的用户提示；业务与校验层不依赖 Qt 或当前界面语言。"""


class Message(str):
    def __new__(cls, source, **values):
        obj = super().__new__(cls, source.format(**values))
        obj.source, obj.values = source, values
        return obj


class UserError(ValueError):
    def __init__(self, source, **values):
        super().__init__(Message(source, **values))
