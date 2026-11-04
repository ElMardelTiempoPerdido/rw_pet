"""从本地 Hunter Expansion 读取 Sig 对话，不复制或加载模组程序"""
from ...shared.game_mods import installed_mod_paths
from .chat_assets import wav_info
from .errors import VoiceAssetError
from .voice import SIG_VOICE_CLIPS


HUNTER_EXPANSION_ID = 'Quaeledy.hunterexpansion'
HUNTER_EXPANSION_WORKSHOP_ID = '3186608452'


def prepare_sig_voice(game_dir):
    """五段对话全部可读即有效；无可用副本时返回错误，不回退到历史缓存"""
    try:
        roots = installed_mod_paths(game_dir, HUNTER_EXPANSION_ID, HUNTER_EXPANSION_WORKSHOP_ID)
        if not roots:
            return {}, '未找到猎手拓展本地语音，请安装 Hunter Expansion 后重新检查资源'
        errors = []
        for root in roots:
            paths = {}
            try:
                for clip in SIG_VOICE_CLIPS:
                    relative = f'soundeffects/{clip.asset_name}.wav'
                    # 游戏的 newest 资源覆盖根目录，未覆盖的文件继续使用根目录
                    path = root/'newest'/relative
                    if not path.is_file():
                        path = root/relative
                    try:
                        wav_info(path.read_bytes())
                    except (OSError, VoiceAssetError) as exc:
                        raise VoiceAssetError(f'{path}：{exc}') from exc
                    paths[clip.clip_id] = path
                return paths, ''
            except VoiceAssetError as exc:
                errors.append(str(exc))
        return {}, '猎手拓展语音文件缺失或损坏：'+' / '.join(errors)
    except (OSError, ValueError) as exc:
        return {}, f'检查猎手拓展语音失败：{exc}'
