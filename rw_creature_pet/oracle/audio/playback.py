"""迭代器语音的运行时限制，不改写用户保存的音频偏好"""
from .voice import VOICE_RESOURCES
from .custom import custom_voice_name, custom_voice


def prepared_voice_error(assets, voice):
    if voice == 'none':
        return ''
    if custom_voice_name(voice) is not None:
        packs = getattr(assets, 'custom_voices', {})
        return (packs[voice] if voice in packs else custom_voice(voice)).error
    report = getattr(assets, 'resources', None)
    status = report.items.get(VOICE_RESOURCES[voice]) if report is not None else None
    return status.detail if status is not None else assets.voice_error


def sync_oracle_voice(player, scene, *, paused=False):
    channel = scene.drag_reactions.voice if scene is not None else None
    # 切换为不使用语音时，同时停止当前播放并丢弃待播请求
    blocked = scene is None or scene.config.voice == 'none'
    player.sync(channel, paused=paused or blocked)
