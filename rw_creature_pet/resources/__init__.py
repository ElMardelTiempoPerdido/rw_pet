"""资源来源与设置影响登记；读取清单不探测游戏、不改写用户配置"""
from .catalog import Availability, CatalogError, ResourceCatalog, load_catalog

__all__ = ['Availability', 'CatalogError', 'ResourceCatalog', 'load_catalog']
