"""游戏语音准备失败，交由资源层降级处理"""


class VoiceAssetError(RuntimeError):
    pass
