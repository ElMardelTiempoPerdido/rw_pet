# 拖动反应与珍珠互动参数

入口为 **设置 > 行为 > 拖动反应 / 珍珠互动**，新增字段分别位于 `[oracle.drag_reactions]` 和 `[oracle.reading]`

这些都是角色行为参数，随角色自动保存、导入和“导出分享此角色”一起处理；旧角色没有填写的新字段使用默认值，不覆盖旧字段的自行修改

可通过风格组合快速选择行动表现；勾选所属维度的“显示高级参数”后可调整下表中的全部参数

## 拖动反应

下表时间单位为秒，最短和最长允许相等；动作仍按 40 Hz 推进，实际时机按仿真帧取整，暂停不计时

| 字段 | 默认值 | 作用 |
| --- | --- | --- |
| `gesture_delay_min/max_seconds` | 0.15～1.5 | 抓起后第一次手势尝试的等待 |
| `gesture_interval_min/max_seconds` | 0.45～1.35 | 一组手势结束后，或抽签未触发后，等待下一次尝试 |
| `gesture_duration_min/max_seconds` | 1.4～2.6 | 每组手势持续时间，包含平滑起落 |
| `gesture_speed` | 1 | 三种手势的速度倍率，允许 0.25～3 |
| `gesture_min/max_amplitude` | 0.25～1 | 在安全扇形内选择抬手幅度，偏向小幅度；两手保留轻微差异 |
| `flutter_sync_probability` | 0.35 | 随机扑腾中同起同落的倾向，不改变固定交替动作的选择比例 |
| `eye_delay_min/max_seconds` | 0～0 | 首次睁眼尝试的延迟 |
| `eye_interval_min/max_seconds` | 0.9～2 | 睁眼保持结束后或未抽中后，再次尝试的等待 |
| `eye_duration_min/max_seconds` | 1.5～3 | 睁眼成功后的保持时间 |
| `voice_delay_min/max_seconds` | 0～3 | 首次语音尝试的延迟 |
| `voice_interval_min/max_seconds` | 1.8～3.8 | 按本次语音片段时长加此等待，安排下一次尝试；未抽中时只等待 |
| `projection_delay_min/max_seconds` | 0.15～1.5 | 抓起后投影自己的首次等待，只累计双手空闲时间 |
| `projection_interval_min/max_seconds` | 0.45～1.35 | 两次投影尝试的空闲等待 |
| `projection_duration_min/max_seconds` | 8.25～8.25 | 本次投影显示时间 |
| `projection_frame_seconds` | 0.375 | 两张扫描图交替的间隔 |
| `projection_lift_delay_seconds` | 0.35 | 投影显示后抬手指图的延迟，超过显示时长则不抬手 |
| `projection_move_min/max_seconds` | 0.65～1.6 | 投影小幅挪动的间隔 |

既有触发概率、单手/双手选择、交替动作占比与投影冷却继续使用原路径；投影的概率和冷却仍为 `oracle.drag_projection_probability`、`oracle.drag_projection_cooldown_seconds`

- 手势、眼睛、语音、投影有各自的等待和随机流，调快手势不会加快语音或睁眼
- 投影与摆手共享手臂，仍只能在摆手与收势结束后开始，不会同时争抢双手
- 松手、取消、停用反应时清除待触发事件和语音请求，不补播；正常松手允许现有手势平滑放下
- 手臂的肩外扇形、长度、驱动力上限不开放为风格参数，速度与幅度调高也不能绕过这些约束
- 语音和投影资源缺失时，仅相应参数不可用；禁用状态不清空用户值

## 珍珠互动

| 字段 | 默认值 | 作用 |
| --- | --- | --- |
| `start_probability` | 0.25 | 普通停留后读珠的概率，沿用既有参数 |
| `interval_min/max_seconds` | 0～0 | 一轮正常阅读的珍珠归位后，下一次自主阅读前的最小等待；到期仍须等行为选择 |
| `drift_probability` | 1 | 漫游期间每次读珠尝试的概率；0 时不为读珠中断连续路线 |
| `drift_delay_min/max_seconds` | 12～24 | 进入漫游后第一次读珠尝试前的等待 |
| `drift_interval_min/max_seconds` | 20～40 | 漫游期间一轮阅读结束或未抽中阅读后的等待 |
| `avoidance_probability` | 0.35 | 躲避鼠标的侧倾停稳后，选择原地读珠的概率 |
| `notice_min/max_seconds` | 0.9～1.5 | 注意到珠子后、接近或召近之前的准备时间 |
| `observe_min/max_seconds` | 40～60 | 人偶与珠子到位后的普通阅读时间 |
| `playback_min/max_seconds` | 90～120 | 矩阵珠触发播放动画后替代普通阅读的时间，不播放音频 |
| `eye_open_probability` | 0.1 | 每轮阅读只抽一次，不改变拖动、窗口和鼠标观察的睁眼概率 |
| `matrix_probability` | 0.5 | 同时存在矩阵珠和固定珠时，选择矩阵珠的比例 |
| `approach_weight / recall_weight / orbit_weight` | 35 / 35 / 30 | 固定珠的靠近、召近与局部绕珠观察权重，至少一项大于 0 |
| `observe_distance` | 50 | 靠近/绕珠观察的期望距离，允许 32～150 逻辑像素 |
| `recall_distance` | 38 | 召近阅读的期望距离，允许 30～150 逻辑像素 |

普通、漫游和侧倾停稳后的自主阅读共用读珠间隔；手动观察可以立即执行，中断阅读后也会安排间隔

矩阵珠始终抽取一颗召近，归位保留原槽位、颜色和字形；只有矩阵珠或只有固定珠时，自动使用存在的种类，不因比例设为 0 或 1 而失去所有目标；环绕珠和卫星珠不进入此选珠池

固定珠才按观察方式权重选择动作；关闭自主移动时仍可原地召珠，靠近路线不可行时也退回召近。距离是期望值，活动带、机械臂与身体避让优先；找不到安全的阅读点会结束本轮并送回，不能为了满足配置穿过禁区

## 保存与验证

范围字段会验证最小值不大于最大值、数值有限、权重不同时为 0。单项恢复默认值若与另一端冲突，会在状态栏提示并保留草稿；可以先恢复另一端，再恢复当前项

新增专项用例位于 `tests/oracle/test_reaction_reading_config.py` 与 `tests/oracle/test_reaction_reading_settings.py`，覆盖参数校验、角色分享往返、四反应计时/取消、手臂限位、原地召珠、选珠、归位和界面依赖。既有拖动、投影、眼睛、矩阵、珍珠播放和设置布局回归继续覆盖原有行为

2026-10-29 最终三组针对性测试共 130 项通过，日志为 `artifacts/behavior-final-reactions.log`、`artifacts/behavior-final-autonomy.log` 和 `artifacts/behavior-config-sharing-tests.log`；另有矩阵/珍珠播放等 40 项回归与独立界面审查通过

中文 800×760 离屏预览已检查滚动、折叠及双列控件；未进行原生桌面鼠标操作验收或重新打包 EXE。扩展运行中的默认配色测试仍有上轮已确认的基线失败，本轮不改动该部分

## 风格选择与高级参数

设置 > 行为沿用四个分组，提供日常活动、漫游节奏、鼠标关注、鼠标躲避、拖动反应、阅读习惯、珍珠互动方式七个选择器

每个维度可以选择风格，也可以开启“显示高级参数”手动调整。开关只管理展示，全部原有字段仍然可用；手动修改即将所属维度标为自定义，不做数值反向匹配

选择结果和参数版本随角色保存与分享，旧配置不自动选择风格或覆盖数值。风格库后续改名或调值不会自动改动已保存角色，重新选择才应用更新

风格定义、字段归属与本地覆盖的维护说明见[行为风格配置](../../presets/behavior_styles/README.md)
