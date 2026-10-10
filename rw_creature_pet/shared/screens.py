"""显示器身份匹配；只读取屏幕对象的元数据，不依赖 Qt 或枚举顺序。"""
import json


def screen_key(screen):
    return json.dumps({field: getattr(screen, field)() for field in
                       ('name', 'manufacturer', 'model', 'serialNumber')},
                      ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def screen_identity(key):
    try:
        value = json.loads(key)
    except (ValueError, TypeError):
        value = None
    if isinstance(value, dict) and all(isinstance(v, str) for v in value.values()):
        return value
    # TOML 也可以直接填写系统屏幕名称；空字符串表示自动选择主屏。
    return {'name': key}


def find_screen(screens, key):
    """查找指定设备；不存在时返回 None，由调用者决定临时回退。"""
    if not key:
        return None
    wanted = screen_identity(key)
    if wanted.get('serialNumber'):
        matches = [s for s in screens if all(getattr(s, field)() == wanted.get(field, '')
                   for field in ('manufacturer', 'model', 'serialNumber'))]
        if len(matches) == 1:
            return matches[0]
        # 同型号屏幕可能上报重复序列号，此时继续用系统名称区分。
        return next((s for s in matches if s.name() == wanted.get('name')), None)
    return next((s for s in screens if s.name() == wanted.get('name')), None)


def preferred_screen(screens, primary, key):
    return (find_screen(screens, key)
            or (primary if primary in screens else next(iter(screens), None)))
