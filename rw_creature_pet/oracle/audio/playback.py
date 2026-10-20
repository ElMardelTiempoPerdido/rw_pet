"""迭代器语音的运行时限制，不改写用户保存的音频偏好"""


def sync_oracle_voice(player, scene, *, paused=False):
    channel = scene.drag_reactions.voice if scene is not None else None
    # 自定义角色尚未接入语音；同时停止当前播放并丢弃待播请求
    blocked = scene is None or not scene.config.character.has_voice
    player.sync(channel, paused=paused or blocked)
