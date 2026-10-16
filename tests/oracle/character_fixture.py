"""非启动测试用独立角色库，让传入配置成为该测试角色的初始值"""
from unittest.mock import patch

from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID, prepare_character


def isolate_characters(case, directory):
    case.enterContext(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                           return_value=directory/'characters'))

    def prepare(config, store):
        state = store.load_preset_state()
        if state.get('active') not in state.get('entries', {}):
            ProfileLibrary().export(config, '测试角色', preset_id=BELL_PROFILE_ID)
        result = prepare_character(config, store)
        # 此处验证参数 UI；首次选择、原始旧值和告知窗口另有专门用例
        result.notice = False
        return result

    case.enterContext(patch('rw_creature_pet.oracle.ui.settings.prepare_character', side_effect=prepare))
