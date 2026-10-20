# 共享配置字段归属

所有可持久化的配置叶字段都显式登记为一个归属，不根据它出现在设置面板的哪个页签、是否启用或是否有 GUI 控件推断

权威清单为 [`rw_creature_pet/presets/fields.py`](../rw_creature_pet/presets/fields.py)，当前覆盖 `AppConfig` 的 380 个叶字段：外观 226 个、角色设置 97 个、本机 57 个

## 三种归属

| 归属 | 用途 | 当前范围 |
| --- | --- | --- |
| `appearance` 外观 | 可分享的角色外观 | 主体外观、附加外观、Bell 与自定义配色、自定义尺寸、眼睛、面部 PNG、耳机、内搭、高领、领口与领边、斗篷、柔性部件及贴图、珍珠播放光晕颜色 |
| `profile` 行为 | 角色设置的行为参数，另外引用一份外观 | 鼠标观察与避让、拖动反应、漂浮和漫游速度与节奏、珍珠数量与行为、投影不透明度、光环大小、电弧数量和拖动投影反应 |
| `local` 本机 | 保存在用户文件中，切换共享配置时保留 | 路径、语言、屏幕与活动边缘、启动位置、显示缩放、机械臂缩放、拖动和自主行动总开关、语音总开关与音量、隐藏线缆、外发光、光环和电弧显示开关、监视者模块、调试场景、性能后端 |

`profile` 不表示把整个用户配置文件导出，它只标记角色设置中的行为部分；[角色设置](profile-presets.md) 另外引用随包携带的外观副本

## 容易混淆的字段

| 字段 | 归属 | 原因 |
| --- | --- | --- |
| `interaction.drag_enabled` | 本机 | 是否允许鼠标拖动属于用户使用习惯 |
| `interaction.hover_radius`、`hover_dwell_seconds`、`hover_probability`、`hover_open_probability`、`hover_avoidance_enabled` | 行为 | 观察和躲避鼠标的方式属于角色行为 |
| `desktop.autonomous` | 本机 | 是否允许自主移动由用户决定 |
| `oracle.drag_reactions` 中的全部 6 个叶字段 | 行为 | 拖动后的动作、睁眼及发声概率属于角色反应，不等于语音总开关 |
| `oracle.base_speed`、`pearl_follow_width`、`pearl_follow_height` | 行为 | 底座滑动速度与珍珠跟随范围，在行为页调整 |
| `oracle.daily_activity` 的全部 14 个叶字段 | 行为 | 日常停留、移动距离、活动权重、冥想、跨边节奏和移动侧倾 |
| `oracle.reading.start_probability` | 行为 | 普通停留后启动读珠的概率，独立于日常活动权重 |
| `oracle.drift` 的全部 24 个叶字段 | 行为 | 漫游的冷却、等待、停顿分布、连续漂浮、距离和速度浮动 |
| `oracle.mouse_avoidance` 的全部 24 个叶字段 | 行为 | 人偶专用的躲避延迟、距离、侧倾与移动风格；通用关注参数保留在 `interaction` |
| `oracle.arm_scale` | 本机 | 取决于设备空间与活动带，不随角色设置覆盖 |
| `oracle.outfit_settings.maid` 中的全部 45 个叶字段 | 外观 | 五个附加部件各自的显示、锚点、层级、位移、对称复制与调色，随当前角色保存和分享 |
| `oracle.custom_appearance.cape` 中的全部 13 个叶字段 | 外观 | 单个斗篷槽位的开关、长度、配色、独立领口及底边彩边 |
| `oracle.custom_appearance.clothing_decal_1/2/3` 中的全部 18 个叶字段 | 外观 | 三个固有服装 PNG 槽位的开关、部位、图片引用和 XY 偏移，不随附加外观切换清空 |
| `oracle.pearl_matrix_enabled`、`pearl_orbits_enabled` | 行为 | 珍珠的启用、数量、移动、阅读和播放参数整体属于角色设置 |
| `oracle.pearl_bubble_color` | 外观 | 播放光晕的颜色；本轮保留原存储路径，之后可迁入角色独立配色 |
| `oracle.colors.pearl_glyph`、`oracle.custom_colors.pearl_glyph` | 外观 | 珍珠文字与光环的投影颜色，与入口所在页签无关 |
| `oracle.halo_enabled`、`halo_arcs_enabled` | 本机 | 是否显示光环、电弧属于使用习惯 |
| `oracle.projection_opacity`、`halo_scale`、`halo_arc_max_count`、`drag_projection_probability`、`drag_projection_cooldown_seconds` | 行为 | 投影表现与互动参数 |
| `oracle.glow_enabled`、`glow_color`、`glow_radius`、`glow_opacity` | 本机 | 为适应用户桌面背景的可见性偏好 |
| `oracle.sliding_base`、`pixel_mode`、`physics_backend` | 本机 | 调试或运行方式，不作为角色个性参数 |
| `overseer` 中的全部叶字段，含 `slots[]` | 本机 | 监视者暂作为独立附加模块，不随角色设置分享 |

机械臂的三种颜色归外观，机械臂缩放归本机；颜色出现在多个 GUI 入口时，仍然只有一个底层字段归属

## 设置页签

界面顺序为：常规、屏幕、行为、珍珠、投影、监视者、角色设置、外观细节

- 屏幕：显示器、活动边缘、启动位置、活动带宽度、机械臂缩放
- 行为：集中 86 项行动参数，分为移动与漫游、鼠标观察与避让、拖动反应、珍珠互动
- 移动与漫游：通常移动与底座滑动速度、跨边概率、反重力漫游概率、速度和时长，以及日常活动时长、距离、权重和侧倾
- 鼠标观察与避让：是否躲避鼠标、观察与睁眼概率、鼠标停留半径和时间，以及人偶专用躲避风格
- 拖动反应：反应开关、手势与睁眼概率、双手动作及交替动作占比、语音概率、拖动投影概率和冷却
- 珍珠互动：停留后读珠概率、避让矩阵半径、播放动画概率、跟随范围宽高
- 珍珠和投影页保留数量、显示和特效尺寸等参数；鼠标拖动许可、语音开关及音量仍在常规页
- 外观细节：配色与自定义部件，位于角色设置之后；机械臂颜色保留在这里，主体类型由角色或导入外观决定
- 珍珠播放光晕颜色在外观和珍珠页均可修改，两个入口同步编辑同一个字段
- 投影颜色继续保留外观和投影页两个入口；光环、电弧显示开关保留在投影页，归属仍为本机

每页恢复程序默认值按该页的控件范围执行；共享颜色恢复后同步更新另一入口，不改变字段的导出归属

## 日常活动参数

首批参数定义在 `oracle/behavior_config.py`，沿用旧有字段路径，只将原来的固定常量追加到 `oracle.daily_activity`；普通停留后的读珠启动概率属于 `oracle.reading`，后续阅读参数继续归入此维度

| 参数 | 默认值 | 生效方式 |
| --- | --- | --- |
| `idle_min_seconds` / `idle_max_seconds` | 3 / 6 秒 | 启动或活动结束后，身体停稳才开始计时 |
| `long_idle_min_seconds` / `long_idle_max_seconds` | 7.5 / 18 秒 | 选择继续停留或没有可行路线时，随机等待 |
| `move_min_distance` / `move_max_distance` | 60 / 160 逻辑像素 | 同边移动的计划距离，实际落点还受活动带、可达范围与珍珠避让限制 |
| `idle_weight` / `move_weight` / `meditate_weight` | 28 / 35 / 12 | 三者比较相对权重，无需合计为 100；允许单项为 0，但不能全部为 0 |
| `meditate_min_seconds` / `meditate_max_seconds` | 30 / 60 秒 | 身体和视线停稳后的冥想时间 |
| `cross_edge_cooldown_seconds` | 60 秒 | 普通移动和漫游共用；完成或中断跨边后冷却，仍只允许相邻边 |
| `cross_edge_check_seconds` | 20 秒 | 漫游选下一段路线时，尝试跨边的最短间隔 |
| `move_lean_degrees` | 20 度 | 通常移动时随横向速度变化的侧倾幅度，不限制鼠标躲避和失重姿态 |
| `oracle.reading.start_probability` | 0.25 | 普通停留后的读珠概率，排除跨边、漫游分支后生效；本批不改变漫游和鼠标避让期间的读珠规则 |

默认活动份额仍是冥想 12%、停留 28%、移动 35%、读珠 25%，以上为排除跨边与漫游后的份额；修改读珠概率会等比缩放前三项份额，而修改三项权重不会影响读珠份额

时间在场景创建时转换为 40 Hz 的逻辑帧数，不增加逐帧随机采样；停稳休眠、边界检查和移动许可规则保持原样

这些字段随角色保存、分享、导入和恢复默认值。旧角色包或个人快照缺失字段时补代码默认值，不继承切换前的角色参数；用户设置文件只补缺失字段，保留已有的数值、0 和精度

前三批仍使用现有完整参数界面，后续再加入风格选择和仅影响展示的“显示高级参数”，不依据参数数值反推风格名称

## 漫游节奏参数

新增字段位于 `oracle.drift`，定义在 `oracle/drift_config.py`；原有 `oracle.drift_speed`、`antigravity_probability`、`antigravity_duration_seconds` 路径继续使用。跨边概率、冷却与尝试间隔仍归日常活动，漫游读珠间隔留给后续阅读维度

| 参数 | 默认值 | 生效方式 |
| --- | --- | --- |
| `cooldown_seconds` / `duration_variation` | 120 秒 / 0.1 | 再次自主漫游的冷却；本轮总时长在基准时长上下浮动 10% |
| `entry_min_seconds` / `entry_max_seconds` | 2.5 / 5 秒 | 入场后第一次移动前等待 |
| `resume_min_seconds` / `resume_max_seconds` | 0.5 / 3 秒 | 观察、跨边或鼠标躲避结束后接续移动的等待 |
| `short_pause_min_seconds` / `short_pause_max_seconds` | 0.35 / 1.2 秒 | 短暂停顿范围 |
| `normal_pause_min_seconds` / `normal_pause_max_seconds` | 1.8 / 5.5 秒 | 普通停顿范围 |
| `long_pause_min_seconds` / `long_pause_max_seconds` | 7 / 14 秒 | 长歇范围 |
| `short_pause_weight` / `normal_pause_weight` / `long_pause_weight` | 50 / 35 / 15 | 停顿档位的相对权重，不能全部为 0 |
| `bout_min_seconds` / `bout_max_seconds` | 4 / 10 秒 | 通常连续漂浮的目标时长 |
| `long_bout_min_seconds` / `long_bout_max_seconds` / `long_bout_probability` | 12 / 24 秒 / 0.35 | 长段连续漂浮范围及选择概率 |
| `move_min_distance` / `move_max_distance` | 60 / 100 逻辑像素 | 漫游每段沿当前边的计划距离 |
| `speed_min_factor` / `speed_max_factor` | 0.8 / 1.2 | 每段速度相对 `drift_speed` 的随机倍率 |

停顿与连续漂浮都在决策点抽取，不逐帧重新抽签。连续漂浮会等当前路线抵达可停点，因而时长不是硬截断；读珠和总漫游到期仍可优先接管。默认继续避免连续长歇，只启用长歇时允许重复；是否抽到长歇按档位判断，允许自定义时间范围重叠

## 鼠标关注与躲避参数

通用关注仍由 `interaction.hover_radius`、`hover_dwell_seconds`、`hover_probability`、`hover_open_probability` 控制，不改变一轮停留只抽签一次的规则。进入关注范围、等待并成功开始注视后，才有机会触发躲避

人偶专用参数位于 `oracle.mouse_avoidance`，定义在 `oracle/mouse_avoidance_config.py`；`interaction.hover_avoidance_enabled` 继续作为原有总开关，关闭时保留全部参数值

| 参数 | 默认值 | 生效方式 |
| --- | --- | --- |
| `delay_min_seconds` / `delay_max_seconds` / `probability` | 1 / 6 秒 / 0.95 | 鼠标靠近后的额外延迟及躲避触发概率 |
| `enter_distance` / `exit_distance` | 55 / 85 逻辑像素 | 距身体轮廓的进入与退出距离；退出至少比进入大 20 |
| `leave_grace_seconds` / `pointer_lag_seconds` | 1.5 / 0.35 秒 | 离开宽限与侧倾跟随鼠标的滞后；宽限 0 表示离开后立即回正 |
| `retry_min_seconds` / `retry_max_seconds` | 0.1 / 0.3 秒 | 持续躲避中的重试间隔，下限不得低于 0.05 秒 |
| `impatience_min_seconds` / `impatience_max_seconds` / `move_probability` | 1 / 1.5 秒 / 0.85 | 不耐烦阈值及后续移动概率；鼠标越近积累越快 |
| `move_min_distance` / `move_max_distance` | 18 / 32 逻辑像素 | 普通躲避或漫游中漂开的计划距离 |
| `speed_min` / `speed_max` | 1.8 / 3.6 逻辑像素/帧 | 每次移动独立抽速，逻辑帧率固定 40 Hz |
| `lean_move_probability` / `lean_move_min_distance` / `lean_move_max_distance` | 0.95 / 16 / 80 逻辑像素 | 上半身侧倾明显变化时，伴随移动的机会与计划距离 |
| `lean_min_degrees` / `lean_max_degrees` / `lean_sample_power` | 30 / 60 度 / 2 | 每轮抽取倾角幅度；指数 1 为均匀，大于 1 偏向小倾角 |
| `lean_speed` / `move_angle_jitter` | 90 度/秒 / 22 度 | 侧倾目标的最大变化速度，以及远离鼠标方向两侧的随机偏角 |

进入距离仍最多取关注半径的一半，实际退出同时检查当前身体和回正后的身体，避免自身躲远就立即回正。漫游期间只漂开，不追加倾角；关闭自主移动仍禁止躲避位移，但可注视与侧倾。`move_probability` 只控制不耐烦后的尝试，不改变下半身和漫游分支开始时的首次漂开

矩阵避让安全距离、有限候选重试、抓取优先级、身体支点、臂长及边缘活动带约束保留在实现中，不能通过这些性格参数关闭。已有个人配置只补缺失值，旧角色包缺失的新参数使用代码默认值，不从当前角色继承

## 路径与完整性

- 普通路径如 `oracle.custom_appearance.eye_1.color`
- 结构化列表按元素结构登记，如 `overseer.slots[].color`；不按槽位数量重复登记
- 标量列表作为一个字段，如 `oracle.allowed_edges`
- `oracle`、`custom_appearance` 等容器本身不单独计数，每个叶字段只能属于一类
- 未启用的部件、继承来的贴图字段、暂未使用的兼容配色字段也必须登记
- 字段路径从 dataclass 的类型声明检查，不依赖当前配置实例，因此空列表与可选对象不会漏检

归属清单只决定字段的责任范围，**不等同于直接导出全部登记数据**：[外观配置](appearance-presets.md) 已根据主体类型选择对应外观分支，并将 `image_path` 引用复制为包内资源、改写为相对路径；本机绝对贴图路径不能直接分享

Bell 和自定义配色都完成归属登记，包含当前自定义分支中保留但不使用的 `eyes`、`beads`、`third_eye`；双眼实际配置位于 `custom_appearance.eye_1` 和 `eye_2`

## 新增或迁移字段

1. 在对应配置 dataclass 中添加字段和数值校验
2. 在 `presets/fields.py` 对应清单中显式登记字段名与归属
3. 若字段改名、删除或改换存储位置，同步更新登记路径和配置迁移
4. 若引入新的配置结构类型，补充 `presets/registry.py` 的类型遍历与测试，不使用未知字段默认归属
5. 运行 `python -m unittest tests.test_preset_fields tests.test_settings_store`

导入登记模块时会检查未登记字段、过期路径和无效归属，构建清单时还会拒绝重复登记，报错包含具体字段路径

```python
from rw_creature_pet.presets import FieldScope, paths_for, scope_for

scope_for('oracle.outfit')  # FieldScope.APPEARANCE
paths_for(FieldScope.PROFILE)  # 全部行为字段的稳定排序路径
```

外观和角色设置的导入导出均已接入此登记清单；本机配置仍完整保存并沿用原有升级流程

后续将其他行为常量提为可配置字段时，按相同流程追加登记，并保留原有默认值和字段路径
