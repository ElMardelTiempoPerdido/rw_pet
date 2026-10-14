"""共享预设的字段归属；本机设置的持久化仍由 SettingsStore 负责"""
from .fields import FIELD_SCOPES, paths_for, scope_for
from .registry import FieldScope, validate_registry

__all__ = ['FIELD_SCOPES', 'FieldScope', 'paths_for', 'scope_for', 'validate_registry']
