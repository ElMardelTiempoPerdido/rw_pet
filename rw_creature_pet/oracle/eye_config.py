"""自定义迭代器的独立眼睛外观，编号绑定头部，不随视角交换"""
from dataclasses import dataclass
import re

from ..shared.messages import Message

EYE_FIELDS = ('eye_1', 'eye_2')


@dataclass(frozen=True, slots=True)
class EyeAppearance:
    color: str = '#050000'
    visible: bool = True
    default_open: bool = False

    def __post_init__(self):
        if not isinstance(self.color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', self.color):
            raise ValueError('眼睛颜色必须为 #RRGGBB 颜色')
        for name in ('visible', 'default_open'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(Message('眼睛参数 {name} 必须为布尔值', name=name))

    def openness(self, reaction):
        # 现有动画表达临时睁眼意愿；结束后回到各自的默认状态
        return 1. if self.default_open else reaction
