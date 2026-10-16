# 共享配置字段归属

所有可持久化的配置叶字段都显式登记为一个归属，不根据它出现在设置面板的哪个页签、是否启用或是否有 GUI 控件推断

权威清单为 [`rw_creature_pet/presets/fields.py`](../rw_creature_pet/presets/fields.py)，当前覆盖 `AppConfig` 的 242 个叶字段：外观 151 个、角色设置 34 个、本机 57 个

## 三种归属

| 归属 | 用途 | 当前范围 |
| --- | --- | --- |
| `appearance` 外观 | 可分享的角色外观 | 主体外观、附加外观、Bell 与自定义配色、自定义尺寸、眼睛、面部 PNG、耳机、内搭、高领、领口与领边、柔性部件及贴图、珍珠播放光晕颜色 |
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
| `oracle.arm_scale` | 本机 | 取决于设备空间与活动带，不随角色设置覆盖 |
| `oracle.outfit_settings.maid` 中的全部 35 个叶字段 | 外观 | 五个附加部件各自的显示、位移、对称复制与调色，随当前角色保存和分享 |
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
- 行为：集中 23 项行动参数，分为移动与漫游、鼠标观察与避让、拖动反应、珍珠互动
- 移动与漫游：通常移动与底座滑动速度、跨边概率、反重力漫游概率、速度和时长
- 鼠标观察与避让：是否躲避鼠标、观察与睁眼概率、鼠标停留半径和时间
- 拖动反应：反应开关、手势与睁眼概率、双手动作及交替动作占比、语音概率、拖动投影概率和冷却
- 珍珠互动：避让矩阵半径、播放动画概率、跟随范围宽高
- 珍珠和投影页保留数量、显示和特效尺寸等参数；鼠标拖动许可、语音开关及音量仍在常规页
- 外观细节：配色与自定义部件，位于角色设置之后；机械臂颜色保留在这里，主体类型由角色或导入外观决定
- 珍珠播放光晕颜色在外观和珍珠页均可修改，两个入口同步编辑同一个字段
- 投影颜色继续保留外观和投影页两个入口；光环、电弧显示开关保留在投影页，归属仍为本机

每页恢复程序默认值按该页的控件范围执行；共享颜色恢复后同步更新另一入口，不改变字段的导出归属

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

未来将写定在代码中的行为常量提为可配置字段时，按相同流程追加登记，不在本轮提前搬动这些常量
