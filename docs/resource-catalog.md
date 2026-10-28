# 资源归属与设置影响

当前清单是开发者维护的声明文件，不保存用户偏好，不属于角色预设

- 主清单：`rw_creature_pet/resources/catalog.toml`
- 读取、引用校验、反向查询：`rw_creature_pet/resources/catalog.py`
- 只读检查入口：`python -m tools.maintenance.audit_resources --check-package`
- 完整机器可读映射：同一命令增加 `--json`
- 回归检查：`python -m unittest tests.test_resource_catalog`

本轮完成来源、加载条件、缺失影响与设置映射，尚未把检测结果接入设置面板的“不可用”标注，也没有改写现有资源加载流程或用户配置

## 文件结构

| 表 | 责任 |
| --- | --- |
| `format_version` | 清单结构版本，当前为 1 |
| `required` | 正常桌宠启动的必要资源 ID，当前只有 `main_atlas`；调试几何降级仍由启动入口处理 |
| `origins.<id>` | 内容来源分类：游戏本体、Downpour、Watcher、随包或用户素材 |
| `resources.<id>` | 资源组、原始来源、交付方式、现有加载器、校验要求、缺失影响、缓存与候选来源 |
| `resources.<id>.sources` | 当前实际获取位置，`root=game/package/setting` 分别以游戏根目录、Python 包根目录、实际配置字段解释 `paths` |
| `features.<id>` | 功能所需资源 ID；`sprites` 登记该功能使用的主图集帧；无额外素材的计算效果可写空数组 |
| `settings.<id>` | 关联的真实配置叶路径、功能 ID、影响方式、可选的下拉选项值 |

所有 ID 稳定且独立于显示名称。`paths` 不接受目录通配符；`overseer.slots[].appearance` 中的 `[]` 是配置结构中每个槽位的字段，不是文件匹配。来源候选如何选取以现有加载器为准，不能把一个 `sources.paths` 数组一律解释为“全部存在”或“任一存在即可”

内容来源与当前交付位置是不同维度。例如曲线的 `origins=["watcher"]` 记录原曲来源，但 `delivery="bundled"` 且 `sources.root="package"`，所以它运行时无需 Watcher。Prince 和朋友？形态当前使用包内素材，也不能根据角色题材要求安装 DLC

`loader` 是定位代码的说明，不是可执行的导入表达式。清单不会自动调用加载器、访问游戏、创建缓存或修改角色文件

## 已引用资源与影响

| 资源 ID | 原始来源 / 当前交付 | 功能与设置影响 |
| --- | --- | --- |
| `main_atlas` | 游戏本体 `resources.assets` 中的 `rainWorld` 图像与帧映射 | 白蜥蜴、通用人偶、机械臂、线缆、珍珠和普通监视者外观；正常启动必要 |
| `pearl_glyphs` | 同一容器内的 `glyphs`，提取遮罩缓存 | 珍珠字符及其颜色；不影响珍珠数量、布局和普通阅读 |
| `scan_images` | 本体 `illustrations/aiimg3a.png`、`aiimg3b.png` | 拖动扫描投影概率、冷却；两帧都必需 |
| `bell_voice` | Watcher 的 `RWTW_ATalkShow`，或用户指定的已处理 Bell 片段 | `oracle.voice=bell`；语音开关、音量、拖动语音概率是关联项，不直接固定为 Watcher 开关 |
| `pearl_playback_curve` | Watcher 曲目 Soft Gesture 的预生成数据，已随包分发 | 播放动画概率、气泡大小及颜色；无需游戏音乐，不播放原曲 |
| `prince_visuals` | 随包的头部及前后衣袍 PNG | `oracle.body_appearance=prince` |
| `prince_layout` | 随包 `skin/prince/tentacles.toml` | Prince 触须布局及物理参数 |
| `friend_head` | 随包 `skin/friend/friend_head_2x.png` | `overseer.slots[].appearance=friend`，不影响普通形态 |
| `maid_images` | 随包五部件 × 三档密度，共 15 张 PNG | 女仆套装及各部件；按实际使用的部件、密度检查 |
| `custom_images` | 当前角色引用的 11 个 PNG 槽位 | 面部、额头、耳机、服装贴图、柔性部件；逐角色、逐槽处理 |
| `ui_font` | 随包像素字体 | 当前字体加载失败会抛错，可能阻止打开设置；不是 DLC 问题 |
| `ui_icons` | 随包程序、托盘图标 | 界面显示，无 DLC 行为限制 |
| `ui_translations` | 随包英文 QM | 界面语言；Qt 中文对话框翻译另由 PySide6/发行包提供 |

主图集中的具体帧名已按蜥蜴、人偶、珍珠、监视者分组登记。`LizardBubble6` 由珍珠播放效果使用；`haloGlyph-1` 用在手脚，不代表程序光环需要该帧

光环、电弧、Bell 额头标记、念珠项链、身体/衣袍网格和多数运动是程序计算效果，没有额外的 DLC 文件需求。共享主图集仍按正常启动要求检查，不需要把每个计算效果重复登记为游戏素材

目前没有单独从 Downpour 读取的运行时资源。保留 `downpour` 来源 ID，尚未为其虚构依赖项。Pebbles、Moon、Sig/猎手拓展与自定义语音库属于后续实现，不登记为已存在的可选语音；当前代码中的 `VOICE_CLIPS` 仍只有 `bell` 和 `none`

## 设置影响规则

`effect="unavailable"` 表示资源结果可用于后续标注此控件或指定选项不可用；`effect="related"` 只供反查和提示，不能据此禁用整个控件

- `option="bell"` 只影响“使用的语音”中的 bell；`none` 无需资源，角色名称不参与判断
- `mode="all"` 表示所有关联功能都要具备资源
- `mode="any"` 表示任一关联功能可用时控件仍有意义；投影不透明度关联字符、扫描、播放气泡和光环，缺一张扫描图不能禁用整项
- 拖动互动总开关包含摆手、睁眼、语音和扫描；素材缺失不应关闭其余身体反应
- 游戏目录和贴图路径在缺失时必须保持可编辑，以便用户修复
- 套装和自定义 PNG 是聚合资源组，只登记关联；未来 UI 必须按实际部件或角色槽位返回状态，不能用一个聚合布尔值禁用所有部件
- 套装支持、眼睛/手部能力、用户开关和当前行为条件属于另一层判断，清单不会替代 `characters.py` 的能力定义

读取接口示例：

```python
from rw_creature_pet.resources import Availability, load_catalog

catalog = load_catalog()
# 此字典应由真实加载器的结果生成，不是读取 DLC 文件夹后猜测
states = {"bell_voice": Availability.UNAVAILABLE}
catalog.setting_state("voice_bell", states)  # UNAVAILABLE
catalog.setting_state("voice_none", states)  # AVAILABLE
catalog.impacts_for("bell_voice")           # 反查相关设置及影响方式
catalog.bindings_for("oracle.voice", option="bell")
```

缺少检测结果返回 `UNKNOWN`，不能解释为缺资源；`related` 的设置状态也返回 `UNKNOWN`，提醒调用方需要按上下文细分。`feature_state` 只回答正常运行基础上的额外资源条件，调用方应先独立检查 `required_state`。这些接口不执行探测，也不检测播放器设备、角色能力或选项是否已开启

## 加载细节与后续接入边界

Bell 自动流程优先使用完整的独立 WAV，再尝试共用音效 AssetBundle 中指定的条目。零字节占位 WAV、共用包存在、Watcher 目录存在，都不等于 Bell 音频可用。显式 `voice_directory` 除旧版兼容路径外，缺文件时不会自动回退游戏目录；当前只验证预期的十个文件存在，解码错误仍可能发生在实际播放阶段

当前 `prepare_oracle_assets` 仍会准备 Bell 素材，即使角色选择了 `none`。本轮只登记事实；后续资源状态接入时可以再按所选语音决定是否准备，不能把该优化视为已经完成

语音缺失、投影缺失和字形缺失已有各自的局部错误处理。包内 Prince、套装和字体等资源损坏并不都具备统一降级，本清单的 `missing` 记录当前差异，后续统一状态层需要适配这些入口

资源归属本轮依据当前加载器、已采用素材与本机游戏内容整理。当前设备安装了 DLC，未以“仅安装本体”的干净环境实际启动验收；原反编译路径 `D:/CODES/CS/rw/_src` 当前不在本机，未重新对照那份源码。这里不把内容分类当作 Steam 购买状态检测

## 维护与发行

新增资源时先登记资源与现有加载器，再登记功能与真实设置路径。增加某语音时新增功能及对应 `oracle.voice` 选项绑定，并更新共用语音控制的关联；不要按角色名判断可选声音

`audit_resources` 会校验字段、ID、跨表引用、路径格式及配置字段是否存在；`--check-package` 额外检查随包文件齐全，输出只代表文件存在，不代表游戏资源已成功解码。测试还对照当前渲染器的 sprite 调用、PNG 槽位、套装密度和语音选项，避免清单随代码变动失效

TOML 已加入 setuptools 包数据和 PyInstaller 数据清单，读取模块也加入冻结导入。发行包只携带这份文字清单和已有随包素材，不复制游戏音频、主图集、游戏安装路径或用户缓存。本轮不重新生成 EXE
