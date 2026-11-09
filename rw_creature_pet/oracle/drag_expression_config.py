"""独立于拖动动作风格的表情候选，只保存用户可配置的概率和权重"""
from dataclasses import dataclass

from .behavior_config import validate_number
from .eye_config import EYE_KINDS

# 固定睁眼/闭眼只作为拖动覆盖，不扩展常规外观的眼形选项
EXPRESSION_OPTIONS = EYE_KINDS[1:] + (('fixed_open', '· ·'), ('fixed_closed', '- -'))
EXPRESSION_KINDS = tuple(kind for kind, _ in EXPRESSION_OPTIONS)


@dataclass(frozen=True, slots=True)
class ExpressionChoice:
    enabled: bool = False
    weight: int = 1
    large_only: bool = False

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.large_only) is not bool:
            raise ValueError('表情启用与大幅拖动限制必须为布尔值')
        if type(self.weight) is not int or not 0 <= self.weight <= 1000:
            raise ValueError('表情权重必须是 0～1000 的整数')


@dataclass(frozen=True, slots=True)
class DragExpressionConfig:
    probability: float = .5
    squeezed: ExpressionChoice = ExpressionChoice()
    slant_in: ExpressionChoice = ExpressionChoice()
    slant_out: ExpressionChoice = ExpressionChoice()
    round: ExpressionChoice = ExpressionChoice()
    chevron_up: ExpressionChoice = ExpressionChoice()
    chevron_down: ExpressionChoice = ExpressionChoice()
    fixed_open: ExpressionChoice = ExpressionChoice()
    fixed_closed: ExpressionChoice = ExpressionChoice()

    def __post_init__(self):
        validate_number('oracle.drag_expressions.probability', self.probability, 0., 1.)
        if any(not isinstance(getattr(self, kind), ExpressionChoice) for kind in EXPRESSION_KINDS):
            raise ValueError('拖动表情候选配置无效')

    @property
    def available(self):
        return self.probability > 0 and any(getattr(self, kind).enabled and getattr(self, kind).weight > 0
                                          for kind in EXPRESSION_KINDS)

    @classmethod
    def from_mapping(cls, data):
        if not isinstance(data, dict) or set(data)-{'probability', *EXPRESSION_KINDS}:
            raise ValueError('拖动表情配置无效')
        values = dict(data)
        for kind in EXPRESSION_KINDS:
            choice = values.get(kind, {})
            if not isinstance(choice, dict):
                raise ValueError('拖动表情候选配置无效')
            values[kind] = ExpressionChoice(**choice)
        return cls(**values)
