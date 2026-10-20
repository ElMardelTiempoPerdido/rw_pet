"""附加外观的锚点、所属部位和合法层级，配置与绘制共用，不依赖 Qt"""
from enum import StrEnum


class Anchor(StrEnum):
    HEAD_CROWN = 'head_crown'
    BODY_COLLAR = 'body_collar'
    GOWN_COLLAR = 'gown_collar'

    @property
    def region(self):
        return 'head' if self == Anchor.HEAD_CROWN else 'body'


class Slot(StrEnum):
    BEHIND_HEAD = 'behind_head'
    FRONT_HEAD = 'front_head'
    BEFORE_SLEEVES = 'before_sleeves'
    AFTER_SLEEVES = 'after_sleeves'
    AFTER_CAPE = 'after_cape'
    FRONT = 'front'


def allowed_slots(anchor):
    if Anchor(anchor).region == 'head':
        return (Slot.BEHIND_HEAD, Slot.FRONT_HEAD)
    return (Slot.BEFORE_SLEEVES, Slot.AFTER_SLEEVES, Slot.AFTER_CAPE, Slot.FRONT)


def resolved_slot(anchor, slot):
    """跨部位时采用新部位的前侧默认层，同部位保留原层级"""
    anchor, slot = Anchor(anchor), Slot(slot)
    if slot in allowed_slots(anchor):
        return slot
    return Slot.FRONT_HEAD if anchor.region == 'head' else Slot.AFTER_SLEEVES


# 内置素材的初始位置；角色只保存自己的修改，不修改此表
MAID_PLACEMENTS = {
    'head': (Anchor.HEAD_CROWN, Slot.BEHIND_HEAD),
    'lace': (Anchor.BODY_COLLAR, Slot.AFTER_SLEEVES),
    'apron': (Anchor.GOWN_COLLAR, Slot.BEFORE_SLEEVES),
    'ribbon_up': (Anchor.HEAD_CROWN, Slot.FRONT_HEAD),
    'ribbon_down': (Anchor.GOWN_COLLAR, Slot.FRONT),
}
