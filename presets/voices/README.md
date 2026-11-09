# 自定义语音

在本目录中创建子目录，将 `.wav` 文件直接放在子目录内，例如：

```text
presets/voices/moon/问候.wav
presets/voices/moon/回答.wav
presets/voices/我的角色/01.wav
```

打开设置 - 行为 - 使用的语音，下拉列表会刷新并显示 `[自定义] moon`、`[自定义] 我的角色`。自定义 `moon` 与内置 `moon` 是不同选项，不会混用文件

- 支持 PCM（8/16/24/32 位）及浮点（32/64 位）WAV，文件保留原音量并受桌宠全局语音音量控制
- 一个文件作为一段完整语音，随机选取；不递归读取更深的目录
- 空目录、没有可用 WAV 的目录显示为不可用；单个损坏文件会跳过，不影响其他可用录音
- 修改文件后，重新展开语音下拉列表、重新打开设置或点击“重新检查资源”即可刷新
- 角色只保存 `custom:子目录名`，分享角色时请另外分享对应语音目录；接收方缺少目录时会保留选择并标为不可用
- EXE 版读取可执行文件旁的 `presets/voices`，Python 版读取工程根目录下的同名目录，与启动时的工作目录无关

# Custom voices

Create one subfolder per voice and place WAV files directly inside it. Reopen the voice dropdown to refresh. Entries appear as `[Custom] folder name`, separately from built-in NPC voices. Share the voice folder alongside character profiles; audio files are not embedded in profile exports
