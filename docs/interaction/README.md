# 鼠标拖拽（第一版：Oracle 人偶）

桌面托盘或 Oracle 调试窗口中勾选 **允许拖动人偶**。默认关闭，保持原有全穿透行为。
如需启动时开启，在 `config.toml` 设置：

```toml
[interaction]
drag_enabled = true
```

## 操作与边界

- 左键按下瞬间命中人偶可见轮廓才抓取；包括头部附件、衣袍、袖子和手脚。
- 光环、机械臂、线缆和珍珠不接收输入，透明空白继续点穿。
- 在其他位置按住鼠标再经过人偶，不会抓取。成功抓取后，鼠标离开轮廓也持续跟随。
- 使用阻尼和限速跟随，保留按下时的偏移。头、衣袍、四肢和线缆继续运动。
- 手动可进入自主活动带外，但人偶仍留在主屏工作区内。底座继续沿边滑动。
- 按机械臂真实末端及前三段最大跨度限制位置。超过可达范围时停在该方向极限，鼠标在外侧多拉的距离不积累成抛出速度。
- 松手后保留有限的实际惯性，平滑返回活动带、收回机械臂，再恢复抓取前的自主开关状态。进行中的观察/漫游结束，恢复后重新选择行为。
- 光环在手动期间随人偶进入中央；珍珠保持在活动带内，跟随人偶对应的边缘位置。恢复后继续原有规则。
- 暂停、关闭拖拽、丢失鼠标捕获会取消抓取；暂停期间冻结，继续后返回。工作区或缩放重建时取消旧抓取，保留自主开关与拖拽开关。
- 调试窗口保留原有空白左键选移动目标、右键观察、中键平移、Shift+左键设置珍珠位置。拖拽和返回期间，新的自主行动指令暂不执行。

## 目录与扩展

`rw_creature_pet/interaction/` 不导入任何生物模块：

- `drag.py`：按下命中、抓取会话、偏移、限速阻尼跟随，不依赖 Qt。
- `hitmap.py`：将目标自身的透明度轮廓转换为命中图和窗口 mask。
- `desktop.py`：局部输入窗口、鼠标捕获与取消；原有全屏绘制窗口仍完全穿透。
- `config.py`：共用交互配置。

Oracle 规则位于 `oracle/drag.py`，人偶专用的轮廓生成位于 `oracle/input.py`。
命中图复用绘制指令，只绘制人偶本体；静止时复用缓存，不为输入重画长线缆。
新增生物或珍珠时，提供自己的命中图和拖拽适配器即可复用输入层。第一版尚未接入蜥蜴或珍珠拖拽。

## Oracle 拖动反应

`oracle/drag_reactions.py` 在抓取成功后启用。手势向现有 `HangingHand` 物理叠加力，
不固定手部位置，不改变身体导航或机械臂约束；关闭反应仍保留自然甩手。

- **悬空扑腾**：双手错开节奏划动，按身体局部方向计算；实际移动较快时稍微加强。
- **短暂抗议**：靠近抓取方向的一只手伸出并挥动，另一只手保持较小的动作。
- 手势约持续 1.4～2.6 秒，之后间隔 0.45～1.35 秒再抽签。正常松手在 0.25 秒内撤去驱动力；取消抓取立即停止施力，保留次级物理收敛。
- 睁眼与语音分别使用独立的随机流和计时，不依附手势触发，也不改变自主观察的低开眼概率。
- 静止抓住时也会间歇反应；未抓住时不产生新事件，松手收敛后恢复原来的休眠机制。暂停不推进计时，尺寸重建丢弃旧动作并保留随机流。

在 `config.toml` 中调整：

```toml
[oracle.drag_reactions]
enabled = true
gesture_probability = 0.90
flutter_probability = 0.60  # 手势触发后扑腾的占比，其余为抗议
eye_open_probability = 0.65
voice_probability = 0.55
```

### 语音播放与准备

桌面和调试窗口通过 `interaction/audio.py` 消费 `VoiceCueChannel`，用 PySide6 自带的
QtMultimedia 异步播放已处理的本地 WAV。第一次实际触发时才创建一个 `QSoundEffect`；
不做在线切分、混音或声音分离，不随绘制重建播放器。

每次成功抓起后先随机等待 0～3 秒，再按 `voice_probability` 独立抽签。
等待期间松手、取消拖动或重置会撤销本次等待；重新抓起重新抽取延时，不会补播。
请求按片段时长预占，之后间隔 1.8～3.8 秒再抽签；
选择时排除上一请求的片段。播放层另外检查真实设备状态，快速反复抓起或仿真掉帧时也不叠音，
忙碌期间的新请求直接丢弃。正常松手让当前台词播完，不再生成新台词；
暂停、关闭拖动、重置、工作区重建、进入调试或退出窗口时立即停止，异步加载也会撤销。
静音期间不排队，重新启用声音不会补播。

```toml
[audio]
enabled = true
volume = 0.70  # 0～1，0 为静音

[oracle]
voice_directory = 'artifacts/oracle-voice-reference/bell-clips'
```

桌面托盘的「语音」子菜单和调试窗口均可即时静音、调音量，并显示加载/播放/错误状态。
这些操作只影响本次运行；永久设置修改 TOML。调试窗口继承打开时桌面的音量和开关，
关闭后返回桌面原设置。仍需开启「允许拖动人偶」才能通过拖动触发；没有添加空闲时随机喊话。

相对音频目录按 TOML 所在目录解析；不传配置文件时按项目根目录解析，也支持绝对路径。
只加载外层 `bell_01.wav`～`bell_05.wav`，不使用 `raw/` 或旧的 `stereo-trial/`。
缺少文件、没有输出设备或加载失败时保持桌宠运行，在语音状态处提示原因，不弹窗、不卡住动作。

片段时间表在 `oracle/voice.py`。本机已准备并试听确认；需要重新生成时使用离线工具：

```powershell
python tools/oracle/prepare_bell_voice.py
# 或指定本机导出的原录音
python tools/oracle/prepare_bell_voice.py --source "完整采访.wav" --output "试听目录"
```

默认读取 `artifacts/oracle-voice-reference/RWTW_ATalkShow.wav`，输出到同目录的 `bell-clips/`。
原始裁剪保留在 `bell-clips/raw/`；外层的同名 WAV 为实际播放版本，保留双声道及采样率。
01～03 不处理；04 的前 1.5 秒应用加权声道抵消，在 1.5～1.7 秒平滑回到原音；
05 沿用已试听的处理：前 0.5 秒完整抵消，在 0.5～0.7 秒平滑回到原音。
只处理上述开头区间，后面的采样不变。附带来源哈希、时间边界和处理参数的 `manifest.json`。
`cut_bell_voice.py` 仍是仅裁剪工具；若单独使用，请将输出指定到 `raw/`，避免覆盖处理候选。

| 文件 | 原录音时间（秒） | 时长（秒） |
| --- | --- | --- |
| bell_01.wav | 6.00～8.50 | 2.50 |
| bell_02.wav | 14.50～19.60 | 5.10 |
| bell_03.wav | 22.23～23.60 | 1.37 |
| bell_04.wav | 24.50～34.80 | 10.30 |
| bell_05.wav | 36.50～42.10 | 5.60 |

第 04 段按试听反馈将结束时间延后 0.3 秒，保留尾音并避开更晚的杂音。
抵消利用主持人与 Bell 不同的左右声道比例；不使用 AI，也不保证彻底消除全部混响。
音频保留在本地忽略目录，未提交到仓库。迁移到其他设备时需自行准备上述五个片段，
或将 `voice_directory` 指向已有片段；启动过程不会重新导出游戏资产。

## 验证入口

```powershell
python -m unittest tests.interaction.test_drag tests.oracle.test_drag
python -m unittest tests.oracle.test_drag_reactions
python -m unittest tests.interaction.test_audio tests.oracle.test_voice_playback
python tools/oracle/review_oracle_drag.py
python tools/oracle/review_oracle_drag_reactions.py
python tools/oracle/review_oracle_drag.py --native
```

普通回放生成 `artifacts/oracle-drag-review.png`。`--native` 会短暂显示 Windows 测试窗口，发送真实鼠标输入验证穿透、捕获、释放和焦点，然后关闭窗口并恢复鼠标位置。

反应回放生成 `artifacts/oracle-drag-reactions.gif` 与 `.png`，并排展示纯惯性、扑腾、抗议；为便于比较，这份回放固定选择手势，正常运行仍按配置随机。
