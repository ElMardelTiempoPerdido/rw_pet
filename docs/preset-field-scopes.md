# 共享预设字段归属

所有可持久化的配置叶字段都显式登记为一个归属，不根据它出现在设置面板的哪个页签、是否启用或是否有 GUI 控件推断

权威清单为 [`rw_creature_pet/presets/fields.py`](../rw_creature_pet/presets/fields.py)，当前覆盖 `AppConfig` 的 207 个叶字段：外观 116 个、完整预设 34 个、本机 57 个

## 三种归属

| 归属 | 用途 | 当前范围 |
| --- | --- | --- |
| `appearance` 外观 | 可分享的角色外观 | 主体外观、附加外观、Bell 与自定义配色、自定义尺寸、眼睛、面部 PNG、耳机、内搭、高领、领口与领边、珍珠播放光晕颜色 |
| `profile` 完整 | 完整预设的行为参数，另外引用一份外观 | 鼠标观察与避让、拖动反应、漂浮和漫游速度与节奏、珍珠数量与行为、投影不透明度、光环大小、电弧数量和拖动投影反应 |
| `local` 本机 | 保存在用户文件中，切换共享预设时保留 | 路径、语言、屏幕与活动边缘、启动位置、显示缩放、机械臂缩放、拖动和自主行动总开关、语音总开关与音量、隐藏线缆、外发光、光环和电弧显示开关、监视者模块、调试场景、性能后端 |

`profile` 不表示把整个用户配置文件导出，它只标记完整预设中的行为部分；一个完整预设最终还需要引用随包携带的外观副本

## 容易混淆的字段

| 字段 | 归属 | 原因 |
| --- | --- | --- |
| `interaction.drag_enabled` | 本机 | 是否允许鼠标拖动属于用户使用习惯 |
| `interaction.hover_radius`、`hover_dwell_seconds`、`hover_probability`、`hover_open_probability`、`hover_avoidance_enabled` | 完整 | 观察和躲避鼠标的方式属于角色行为 |
| `desktop.autonomous` | 本机 | 是否允许自主移动由用户决定 |
| `oracle.drag_reactions` 中的全部 6 个叶字段 | 完整 | 拖动后的动作、睁眼及发声概率属于角色反应，不等于语音总开关 |
| `oracle.base_speed`、`pearl_follow_width`、`pearl_follow_height` | 完整 | 已能通过配置修改的移动与跟随行为，即使目前没有 GUI 也纳入 |
| `oracle.arm_scale` | 本机 | 取决于设备空间与活动带，不随角色预设覆盖 |
| `oracle.pearl_matrix_enabled`、`pearl_orbits_enabled` | 完整 | 珍珠的启用、数量、移动、阅读和播放参数整体属于完整预设 |
| `oracle.pearl_bubble_color` | 外观 | 播放光晕的颜色；本轮保留原存储路径，之后可迁入角色独立配色 |
| `oracle.colors.pearl_glyph`、`oracle.custom_colors.pearl_glyph` | 外观 | 珍珠文字与光环的投影颜色，与入口所在页签无关 |
| `oracle.halo_enabled`、`halo_arcs_enabled` | 本机 | 是否显示光环、电弧属于使用习惯 |
| `oracle.projection_opacity`、`halo_scale`、`halo_arc_max_count`、`drag_projection_probability`、`drag_projection_cooldown_seconds` | 完整 | 投影表现与互动参数 |
| `oracle.glow_enabled`、`glow_color`、`glow_radius`、`glow_opacity` | 本机 | 为适应用户桌面背景的可见性偏好 |
| `oracle.sliding_base`、`pixel_mode`、`physics_backend` | 本机 | 调试或运行方式，不作为角色个性参数 |
| `overseer` 中的全部叶字段，含 `slots[]` | 本机 | 监视者暂作为独立附加模块，不随人偶预设分享 |

机械臂的三种颜色归外观，机械臂缩放归本机；颜色出现在多个 GUI 入口时，仍然只有一个底层字段归属

## 路径与完整性

- 普通路径如 `oracle.custom_appearance.eye_1.color`
- 结构化列表按元素结构登记，如 `overseer.slots[].color`；不按槽位数量重复登记
- 标量列表作为一个字段，如 `oracle.allowed_edges`
- `oracle`、`custom_appearance` 等容器本身不单独计数，每个叶字段只能属于一类
- 未启用的部件、继承来的贴图字段、暂未使用的兼容配色字段也必须登记
- 字段路径从 dataclass 的类型声明检查，不依赖当前配置实例，因此空列表与可选对象不会漏检

归属清单只决定字段的责任范围，**不等同于直接导出全部登记数据**：[外观预设](appearance-presets.md) 已根据主体类型选择对应外观分支，并将 `image_path` 引用复制为包内资源、改写为相对路径；本机绝对贴图路径不能直接分享

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

外观导入导出已接入此登记清单；本机配置仍完整保存并沿用原有升级流程，完整预设的行为参数导入导出尚未接入

未来将写定在代码中的行为常量提为可配置字段时，按相同流程追加登记，不在本轮提前搬动这些常量
