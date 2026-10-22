# prince 特殊角色

角色库附带名为 `prince` 的角色设置，可从设置页或托盘的切换角色菜单选择；它使用独立的 `body_appearance = 'prince'` 类型，默认启动角色仍为 Bell

目前使用无眼睛、无双臂的固定轮廓，共用迭代器导航骨架、机械支架、线缆、珍珠和移动行为；Prince 的胸肩、躯干曲线、头颈跟随和双层下摆使用独立体态

头部使用 `skin/prince/prince_head_petals.png`，一个素材像素对应一个逻辑像素，中心脸盘固定为 Friend 相同的淡黄色 `#E4E1CF`。花瓣与脸盘共用 Friend 的浅曲面投影和深度遮挡，按注视方向转动；不添加眼睛。1x/1.5x/2x 按实际密度投影，3x/4x 沿用现有基础像素档位；奇数素材边长对齐像素锚点，避免正视时花瓣增粗

Prince 的头部转角使用类似 Friend 的两段响应：近段轻微转动，中段放缓，远段逐渐接近上限。`graphics/prince.py` 的 `HEAD_GAZE_*` 常量可调整近段强度、曲线及横向/仰俯上限，默认投影前上限分别为 70°/60°，投影还保留最小侧视厚度。输入是已经平滑并限幅的 Oracle 注视强度，区别于 Friend 按工作区距离归一化的输入；仅调整花冠朝向，不改变头颈质点、身体或其他角色的行为

基础头高为通用的 14 个逻辑像素加上 `characters.py` 中 Prince 的 `neck_extension`。在此基础上，静止弓身将胸肩和头部轻微压低；侧看时胸肩向注视方向前移，上躯干弯曲，衣袍上部跟随胸肩变形。正面不强制偏向屏幕左侧或右侧

身体使用下摆、腰、胸、颈、头五个物理点，腰部跟随通用导航支点，其余点独立响应惯性，通过距离约束逐段传力。相邻段有防反折限制，但整条身体不强制保持直立；绘制使用穿过这些点的平滑曲线，衣袍和双层 PNG 下摆沿曲线变形。截面始终采用单位法线，保持原有肩宽和素材自然宽度

注视时胸、颈和头依次跟随。平视或仰视只保留轻微的躯干弯曲，主要由颈部和头部转向；视线沿身体轴指向更低处时，再从腰部逐渐增加俯身。躯干和颈部采用独立的转角幅度，向下分量连续平滑过渡，避免目标经过等高位置时突然切换姿态。正下方的注视通过正面投影压低胸肩和头部表达，避免突然向左或向右折过去。头部由独立物理点产生滞后，不再限制为相对目标最多 2.5 逻辑像素的偏移

低头响应按「颈部先低下、身体稍后弯曲」分配：身体使用 `low ** 1.3`，颈部和上颈段使用 `1 - (1 - low) ** 2`。一半低头输入对应约 41% 的身体俯身增量和 75% 的颈部增量；平视保持原姿态，深度俯视仍达到各自完整幅度。颈部最大低头增量为 `1.0` 弧度，使侧向俯视时更接近水平；时间上的跟随速度不因这些曲线变化而调整

俯身强度与左右朝向分开：`projected_bend()` 根据俯身角计算各段相对平视姿态的高度损失，横向分量只决定前伸有多少显示为侧移。同样的向下分量在左右和正下方产生相同的额外下沉量，正下方通过纵向透视缩短表达，不再额外套用固定 16%/22% 缩短或随横向分量减弱俯身。投影后的段向量不归一化，身体物理使用投影后的目标长度，避免把纵向缩短重新拉直

拖拽时按点击区域选择最近的身体轴节点，在此处施加抓取力。Prince 拖拽期间不主动注视鼠标，原先的注视方向平滑回到中性，避免身体持续朝抓取点主动弯折。导航支点由仍抓附的触手限制可达距离，并保留工作区边界约束；视觉身体会由抓取点逐段带动，未抓取的部分保留惯性和下垂感。松手后平滑恢复到正常体态和活动带，身体、下摆和触手停稳后允许休眠

导航根据抓取点在目标体态中的位置推导支点，不追逐实际柔性节点的细小惯性偏移。按下时记录导航参考方向，本次抓取的位置换算和导航骨架始终使用该方向，避免下摆的长力臂将转角反馈给支点，造成按住不动时持续绕抓取点摆动。实际五段身体仍独立受力、弯曲；松手或取消时清除参考方向，下次抓取重新记录当前方向，不在按下瞬间强制切换为直立

抓取状态下，相邻身体段增加柔性的角度恢复，腰部较软，胸颈保持连贯；上半身减少额外重力压缩，下摆仍保留明显下垂，避免静止时颈部形成反向折弯

按住鼠标也允许物理收敛休眠：输入和目标体态稳定、所有节点速度足够小时，连续观察 24 个物理帧后保留当前受力姿态并停止积分，不强行拉回直立。鼠标移动、目标体态变化、重力改变或松手会重新唤醒；衣袍和双层下摆仍各自等待停稳后休眠

所有状态在固定 40 Hz 更新，绘制只读插值；同一帧的曲线系数和相同高度的采样结果共用缓存。真实头部位置同步供光环跟随、线缆和命中范围使用；不切换原作的四种姿态，也不改变 Bell 或自定义迭代器的身体物理

可调整的主要常量：

- `motion/prince.py` 的 `WAIST_DEPTH`、`CHEST_DROP`：弯曲起点和静止基础弓身
- `LOOK_BEND`、`LOW_LOOK_BEND`：躯干在平视/仰视时的轻微弯曲，以及向下注视时逐渐叠加的俯身幅度，单位为弧度
- `NECK_LOOK_BEND`、`LOW_NECK_BEND`、`NECK_BEND`：颈部独立的转向幅度、向下注视时叠加的幅度和额外弯曲，单位为弧度
- `BODY_BOW_POWER`、`NECK_BOW_POWER`：身体延后、颈部提前的低头响应曲线指数，分别作用于上述两条曲线
- `CHEST_FOLLOW`、`HEAD_FOLLOW`、`LOW_LOOK_FOLLOW`：胸肩、头部和低头的跟随速度
- `motion/prince_spine.py` 的 `SPRING`、`DAMPING`：各段恢复力度和速度保留系数
- `DRAG_SPRING`、`DRAG_DAMPING`、`DRAG_GRAVITY`：拖动时的姿态恢复、惯性和重力
- `DRAG_GRAVITY_WEIGHTS`：下摆、腰、胸、颈、头各节点的重力权重
- `DRAG_BEND_STIFFNESS`：抓取时腰、胸、颈的相对角度恢复力度，不限制整体朝向
- `HOLD_SETTLE_SPEED`、`HOLD_SETTLE_TICKS`：静止抓取的速度门槛和连续稳定帧数
- `BEND_LIMITS`：腰、胸、颈处的相邻段弯折限度，单位为度，仅用于避免局部反折

## 双层下摆

上半衣袍沿用布料网格，但使用 Prince 的窄肩轮廓，向下逐渐扩展到素材的连接宽度，底部收平。`motion/prince_robe.py` 中的 `CHEST_WIDTH`、`CHEST_HEIGHT` 控制胸部，`SHOULDER_HALF`、`UPPER_LENGTH`、`UPPER_SLACK` 控制上半衣袍的肩宽、长度和活动余量

下半部分按后层 `skin/prince/prince_lower_robe_2.png`、前层 `prince_lower_robe_1.png` 的顺序绘制，保留两张 PNG 的原色、透明像素和共同画布，一个素材像素对应一个逻辑像素。上半衣袍的末段逐渐过渡到前层素材顶部的颜色；连接点取自上半衣袍最后一行，素材顶部略微重叠，避免露出接缝。旧腿部和下腰轮廓不再绘制，镂空处仅显示后层或背景

每层下摆使用独立的 5 列 × 9 行网格，在固定 40 Hz 更新。顶部 `PIN_LENGTH` 范围共同固定在接缝，下方逐渐放开；后层的惯性更大、回摆稍慢，移动和转身时形成视差，静止后收敛并参与休眠。目标发生大幅跳变时重置惯性，避免重置位置时产生长拖尾

连接处使用上半衣袍中央的共同下垂方向，不沿每列的外张斜率继续向两侧延伸；之后沿五点身体轴逐行弯曲，叠加两层各自的惯性。顶部贴合实际接缝，在 `PIN_LENGTH` 处恢复 PNG 原宽，避免静止时下半素材被逐渐撑宽。肩宽调整只改变上半衣袍，不改变下半素材的自然宽度

下摆使用已有的分片 PNG 变形、像素化与外发光流程，纳入绘制清除范围和身体命中范围；透明镂空保持鼠标穿透。下摆回摆独立于上身几何缓存，尾端运动时无需重新生成上半衣袍网格

双层下摆按当前插值姿态合成为一张对齐世界像素网格的局部透明图，画面、外发光和鼠标命中轮廓共用此结果，命中检测不再重复绘制两个网格。缓存只保留最近一次结果；尾端位置、素材、显示像素密度或角色切换时更新，不改变透明镂空的鼠标穿透范围

## 外观和保存

- `oracle.prince_colors` 独立保存皮肤、衣袍、机械支架、珍珠和投影配色
- 设置的外观细节页和调试窗口只提供当前可用的颜色项，不展示自定义体型、贴图或附加外观选项
- 外观/角色导入导出、自动保存、默认值恢复和托盘切换沿用现有流程；Prince 的外观数据不包含 Bell 或自定义迭代器的配色和几何参数
- `presets/startup.py` 的 `default_prince()` 定义初始角色配置；发行角色的初始值由 `presets/profiles/profile-prince-*/profile.json` 及其引用的外观文件提供

## 开发入口

- `oracle/characters.py`：角色能力和配色字段，`has_eyes`、`has_hands`、`has_voice`、`outfits` 分别控制眼睛、双臂、语音与附加外观
- `oracle/graphics/prince.py`：Prince 固定头部和身体绘制入口，不读取 `CustomAppearance`，花冠尺寸和曲面参数在此调整
- `oracle/motion/prince.py`：Prince 专用注视体态、身体轴目标和绘制帧
- `oracle/motion/prince_spine.py`：五点身体物理、距离/防反折约束和曲线采样
- `oracle/interaction/drag.py`：按实际身体区域抓取，Prince 使用触手可达范围，其余迭代器保留机械臂约束
- `oracle/prince_assets.py`：两层衣料的共同画布、连接宽度和接缝颜色
- `oracle/motion/prince_robe.py`、`oracle/graphics/prince_robe.py`：窄肩衣袍轮廓、独立下摆物理和 PNG 网格绘制
- `shared/petal_head.py`：Friend 与 Prince 共用的曲面生成和深度投影，角色各自保留素材和投影缓存
- `oracle/graphics/styles.py`：选择 Bell / 自定义 / Prince 绘制实现
- `oracle/scene.py` 的 `sync_character()` 与外观的 `sync_shape()`：角色切换时清理不适用的动作并重建肢体点

Prince 不生成双臂物理点，不执行眼睛开闭、拖动手势和抬手投影，暂不播放语音；仍可拖动、移动、漂浮、观察及召近珍珠。切回 Bell 或自定义角色后恢复它们各自支持的能力

## 检查

```powershell
python -m unittest tests.oracle.test_prince
python -m unittest tests.oracle.test_prince_posture
python -m unittest tests.oracle.test_prince_robe
python -m unittest tests.oracle.test_prince_drag
python tools/oracle/review_prince.py
python tools/oracle/review_prince_posture.py
python tools/oracle/review_prince_robe.py
python tools/oracle/review_prince_spine.py
python tools/oracle/review_prince_spine.py --lower-drag
python tools/oracle/review_prince_spine.py --gaze-height
python tools/oracle/review_prince_spine.py --bow-projection
```

预览脚本仅将图片输出到 `artifacts/prince`，不读取或修改当前用户角色。`review_prince_spine.py` 输出静态注视姿态、身体轴示意和真实拖拽/恢复流程的 GIF；加上 `--lower-drag` 输出腰部和下摆抓取、长按、再次移动及恢复的并排预览，镜头固定，紫色十字标记鼠标位置；`--gaze-height` 对照静止、仰视、平视和俯视的身体与颈部弯曲；`--bow-projection` 对照相同低头程度在不同横向方向的投影，并生成经过正下方的连续注视 GIF。这些是离屏验证，不替代桌面上的实际拖动观感检查

## 三条触手的轮廓与常规移动

三条触手已接入 Prince 的桌面与调试场景，替换机械臂和线缆的显示与次级运动。配置位于 `rw_creature_pet/skin/prince/tentacles.toml`，由原来的 `tools/oracle/prince_tentacles.toml` 原样移入，桌面和预览共用这一份资源，不读取或写入用户设置、角色文件，也无需提取游戏素材

常规移动时，抓住的末端保持在工作区边缘的原位置，身体前移后逐条收起末端、伸向前方并重新抓住；默认三条触手最多只有一条换点，其余两条继续支撑。三条触手的默认根部均位于胸段中轴沿身体向下 4 个逻辑像素处，不朝停靠边偏移，正面直立时在四条边上均保持居中；弯曲时跟随背部。中段具有阻尼和惯性，停下后收敛休眠，不持续添加随机抖动。跨角时可逐条转移至允许活动的相邻边，限制为单边或连续多边的配置同样生效

实际抓附轨道相对工作区四边向内收 16 个逻辑像素，为末端管宽与囊肿留出显示空间。初始抓点、换点、跨角和拖拽回抓共用此轨道；人偶本体的正常离边距离不随之增加。此设置也用于真实场景的移动预览，静态轮廓预览仍使用 TOML 的画布与原点

极限拖拽松手后，优先返回仍在支撑人偶的触手所在边，并按实际可达位置判定归位完成，避免长触手允许身体越过屏幕中线后误选到无法到达的对边

`points` 保留为静态设计轮廓，不再逐点拉回此轮廓。桌面使用独立的自然长度 `length`、伸出方向 `root_directions` 和抓点偏好 `grip_directions`，仅保留第一个控制点对根部的偏移；若省略这些新字段，对应项才从 `points` 推导。拖拽及松手恢复期间，每条触手的实际弧长最多为自然长度的 120%，不放大管宽或囊肿。最多两条触手可以松开，够不到边缘时保持悬空并收回；至少保留一条抓住边缘，并用它的可达范围限制人偶继续远离屏幕边缘。导航锚点跟随实际可达位置，松手返回仍在支撑人偶的边缘，依次重新抓回，再恢复普通移动的一次一条换点

悬空且没有可达抓点时，只固定根部，末端与其余节点一起受惯性、重力和长度约束影响。远端通过弱追踪力向边缘方向探寻，目标距离在自然长度的 45%～80% 内选择，并以附近边缘距离为上限；不会把末端固定在空中的目标坐标上。每条触手独立随机选择方向、距离、追踪力度、过渡与停留时长，在较有力的试探与放松回摆之间平滑变化，不强制轮流执行，也不逐帧添加随机抖动。松开时从零牵引渐入，保留原有姿态和速度；再次松开继续各自的随机序列，不重复固定开场。拉长的弧长逐渐回到自然长度，保留回摆和弯曲余量；找到可达抓点后仍保持自由末端，通过受力接近墙面，实际触墙后再固定。此探寻只作用于悬空触手，不使已抓附的末端滑动，也不属于声源调查动作

悬空动作的随机参数位于 `oracle/motion/prince_free_search.py` 的 `FreeTipSearch`：`ANGLE` / `REACH` 调整探寻角度和距离范围，`STRENGTH` 调整力度倍率，`RELAX_CHANCE` / `RELAX_REACH` / `RELAX_STRENGTH` 调整放松的概率、距离和力度，`TRANSITION_TICKS` / `HOLD_TICKS` 及其 `RELAX_` 版本调整过渡与停留时长（40 步为 1 秒）。当前试探力度为原追踪力的 65%～100%，放松为 12%～30%，均平滑过渡。基础物理仍位于 `oracle/motion/prince_tentacles.py` 的 `SupportTentacle`：`FREE_TRACK_STIFFNESS` / `FREE_TRACK_FORCE` 调整追踪力度和力的上限，`FREE_LENGTH_RETURN` 调整松开后收回拉伸余量的速度。Python 和 Numba 使用同一自由端求解分支，仍复用坐标缓冲区，Numba 在场景创建时预热

普通悬空回摆中会偶发朝墙探查，借鉴原版 `DaddyTentacle.ExamineSound` 在目标附近更换探查点、通过力推动触手的方式，不接入真实声音。当前参数下，每条触手松开后独立等待约 2.5～10.5 秒，临时朝墙伸出并连续试探附近方向，约 12.5～27.5 秒后缓慢放松；下一次等待约 4.5～15 秒。动作使用独立时钟，可在普通回摆过渡途中插入，内部每 0.3～0.75 秒重新选择附近方向、目标距离和力度，并连续追踪这些参数。目标距离提高到自然长度的 86%～96%，力度为原基础追踪力的 115%～155%。探查权重上升时，牵引平滑扩展到前中段，根部伸出偏好减弱至 20%，使触手能展开而不是把大部分长度耗在重力下垂和折返上；放松时恢复原分布。仍然只改变受力，不固定末端，也不放大自然长度或拖拽上限。实际有可达抓点时优先通过受力回抓

朝墙探查参数位于同文件的 `WallProbe`：`FIRST_WAIT_TICKS` / `WAIT_TICKS` 为首次与后续等待，`DURATION_TICKS` / `RETARGET_TICKS` 为持续时长与换探查点间隔，`ANGLE` / `REACH` / `STRENGTH` 为方向、距离、力度范围，`TARGET_RESPONSE` / `ENTER_RESPONSE` / `EXIT_RESPONSE` 为追踪、进入与退出的响应速度。等待和持续时间均按 40 Hz 计步，各条触手分别计时、使用独立随机流，也不会改写普通回摆的随机序列

悬空后的回抓不再使用固定末端的换点动画：选到可达目标后，保留所有节点位置、速度并暂停随机探查，通过连续牵引让自由末端靠近目标。末端距抓附轨道不超过 2 个逻辑像素、沿轨道距目标不超过 12 像素时，在实际接触的位置固定。目标重新超出可达范围时回到悬空探寻。接近抓点时按需逐步展开拉伸余量，并留出自然长度 2.5% 的弧长余量；触墙后逐步收回，始终遵守拖拽的 120% 上限。仍按原有名额限制回抓数量，至少保留一条支撑；普通行走中主动换点继续使用原动画

受力分布和回抓参数位于 `SupportTentacle`：`EXTEND_TRACK_RAMP` / `EXTEND_TRACK_BASE` 调整前中段牵引分布，`EXTEND_ROOT_RETENTION` 调整伸展时保留的根部偏好；`REGRIP_STRENGTH` / `REGRIP_RESPONSE` 调整回抓力度与接入速度，`REGRIP_CONTACT_DISTANCE` / `REGRIP_CONTACT_SPAN` 调整触墙和沿墙落脚容差，`REGRIP_PRESS` 提供最后几像素的接触压力，`REGRIP_SLACK` 调整回抓弧长余量。`FREE_LENGTH_RETURN` 同时控制余量展开和收回的速度

触手使用局部伸出偏好、屏幕重力、相邻段限长与轻微抗弯形成姿态，不再使用模板回弹、围绕模板的活动范围或静止吸附。相邻段限长由自然总长均分，允许松弛压缩，避免把余量硬撑成小锯齿；实际总长另有硬限制，两端固定时拉到自然长度后展开为直线，再允许整体伸长。自由端则通过逐段限长向内让位，不把整条链强制收拢为直线。抗弯只平滑相邻节点的尖折，不指定整条链的弯曲方向

重力始终朝屏幕下方。四个边缘各自配置屏幕坐标下的根部伸出方向，跨角时平滑混合，方向偏好只作用于靠近根部的前 22%，向外衰减，不指定中后段形状。默认左右边缘镜像水平伸展，上下边缘独立配置，不将右侧造型依次旋转 90°。松弛段接近工作区外侧时保留装饰的显示余量，避免下垂越出屏幕

运动时保留较多惯性，固定抓点不滑动。停下后按速度和约束误差判断休眠，保留当时形成的受力姿态，不恢复指定造型，因此同一位置可以因之前的运动轨迹而留下不同的弯曲

触手保持鼠标穿透，参与原有像素化、实体外发光和绘制范围更新。当前朝墙探查只用于失去抓点的悬空状态；普通移动与漫游中的声源摸索式动作仍留待后续独立处理

在项目根目录、安装了项目依赖的 Python 环境中启动：

```powershell
python tools/oracle/review_prince_tentacles.py
```

窗口每 400ms 检查一次配置文件，保存 TOML 后自动刷新；“打开配置”使用系统关联的编辑器，“重新载入”可以手动刷新，“导出 PNG”默认保存到 `artifacts/prince/prince-tentacles.png`。配置错误时保留上一张有效画面，显示字段或语法错误，并暂时禁用导出；修正并保存后自动恢复

也可不打开窗口，只导出一次：

```powershell
python tools/oracle/review_prince_tentacles.py --output artifacts/prince/prince-tentacles.png
python tools/oracle/review_prince_tentacles.py --config rw_creature_pet/skin/prince/tentacles.toml
```

`--config` 可指向另存的 TOML，用于对比不同方案；`--export-path` 指定窗口中导出按钮的目标路径

配置中的位置、长宽均以 **1x 逻辑像素**为单位。三条触手分别为最长的黑紫渐变、中长的深紫外壳与亮芯、最短的灰紫，固定生成，不使用随机分布

`[motion]` 中的 `body_edge_distance` 设置身体定位点到真实工作区边缘的默认距离，当前为 `106`，原先约为 `82`；启动、重置和拖拽松手归位共用此值。它不是头部或轮廓最近点的间距，也不强制所有自主移动位置保持同一距离。若当前活动带或导航可达范围无法容纳设定值，会收回到允许范围，不越过中央禁区

每条 `[[tentacles]]` 分别设置以下运动参数，修改后重启桌宠，或重新运行动态预览：

```toml
length = 341.947
grip_reach = { top = 0.65, right = 0.65, bottom = 0.65, left = 0.65 }
root_directions = { top = [-0.6, 1], right = [0.5, 1], bottom = [0.2, 1], left = [-0.5, 1] }
grip_directions = { top = [-1, -0.5], right = [0.45, -1], bottom = [1, 0.5], left = [-0.45, -1] }
```

- `length`：自然总长，独立于静态轮廓，不改变管宽、囊肿尺寸或分布比例；范围为 `8～2048`，普通导航仍允许适度伸展到抓点，拖拽及恢复时受 `120%` 上限限制
- `root_directions`：每条边的根部伸出偏好，不是固定的整条曲线
- `grip_directions`：每条边寻找新抓点时的偏好方向；初始抓点和后续换点共用，已经抓住的末端不会随身体滑动
- `grip_reach`：四个边缘各自的抓点偏好距离与自然长度之比，各值范围为 `0～1`；例如长度 `200`、顶部比值 `0.65` 时，在顶部停靠会先从根部沿顶部偏好方向取 `130` 像素外的位置，再投影到允许的抓附轨道。表内须包含 `top/right/bottom/left`，也可继续用 `grip_reach = 0.65` 表示四边共用该值；省略时四边均为 `0.65`。跨角时平滑混合相邻边的偏好位移，移动时仍叠加原有的少量前移量，拖拽时还受可达范围约束

两组方向表都必须填写 `top/right/bottom/left`，分别代表人偶当前所在边。所有向量均使用屏幕坐标 `[x, y]`：右为正 x，下为正 y；例如 `[1, -1]` 总是右上方，不随边缘旋转。向量会归一化，`[1, 1]` 与 `[2, 2]` 效果相同，不能填写 `[0, 0]`。`body_edge_distance` 范围为 `24～1024`

| 字段 | 作用 |
| --- | --- |
| `points` | 从背部到末端的中心线控制点，自动平滑经过各点；相对 `preview.origin`，x 向右、y 向下 |
| `smoothness` | 0～1，控制中心线平滑程度；0 为折线 |
| `widths` | `[沿曲线的比例, 完整宽度]`，各项之间线性插值 |
| `colors` | `[沿曲线的比例, "#RRGGBB"]`，颜色沿曲线长度渐变，不按屏幕高度渐变 |
| `bumps` | 深色囊肿列表 |
| `cores` | 独立的亮芯列表，不必与 `bumps` 一一对应，也不裁剪到外壳内 |
| `core_color` | 此触手亮芯的默认颜色 |
| `enabled` | 是否显示此触手；单个囊肿或内芯也可添加此开关 |

`widths`、`colors` 的比例须严格递增，首项为 0、末项为 1。主体按触手列表顺序从后往前绘制，然后绘制所有深色囊肿，最后绘制所有亮芯；Prince 的身体覆盖在触手整体上方，使根部自然藏在背部

每颗囊肿或内芯使用同一种配置格式，可直接复制一行增加：

```toml
{ s = 0.90, offset = -0.9, width = 5.8, height = 7.7, angle = 16, color = "#7044FF" },
```

- `s`：沿整条曲线的弧长比例，0 为根部、1 为末端；增加中间控制点不会把比例改成“第几个点”
- `offset`：离开中心线的侧向偏移；例如触手朝上时，正值向右、负值向左
- `width`、`height`：分别为横跨触手、沿着触手方向的直径；相等为圆，不相等为椭圆
- `angle`：在上述朝向基础上额外顺时针旋转，单位为度
- `color`：可以省略；深色囊肿使用所在位置的主体渐变色，亮芯使用 `core_color`
- `enabled = false`：保留此项配置但暂时不绘制

让亮芯偏心时，可单独改其 `s`、`offset`，无需修改对应的外壳。囊肿随局部曲线方向定位和旋转，但自身不沿曲线拉伸

`[preview]` 仅控制观察画面：

- `size`：画布逻辑宽高；`origin`：触手共用原点在画布中的位置
- `scale`：1 / 1.5 / 2 / 3 / 4，像素密度遵循桌宠现有规则；3x 以 1x 为基础，4x 默认按 `coarse_pixels_4x` 选择 1x 或 2x 基础
- `magnify`：额外整数观察倍率，不改变像素计算；例如检查 1x 可设 `scale = 1`、`magnify = 4`
- `background`：`"#RRGGBB"` 或 `"transparent"`
- `show_prince`：是否显示人偶；`back_offset`：触手原点相对胸部的位移
- `gaze`：人偶头部方向，x 左负右正，y 低头负、抬头正，范围均为 -1～1

窗口按图像物理像素显示，避免系统缩放额外模糊边缘；画面超过窗口时使用滚动条，不自动缩小图像。该窗口保持静态素材布局预览，不代表物理链停稳后的姿态；桌面进程在首次创建 Prince 时读取配置，修改 TOML 后重启桌宠以应用

另外提供真实场景的常规移动 GIF 导出，包含同边往返、跨角和拖拽三种场景，不会启动桌宠或修改本地角色：

```powershell
python tools/oracle/review_prince_tentacle_motion.py
python tools/oracle/review_prince_tentacle_motion.py --scenario corner
python tools/oracle/review_prince_tentacle_motion.py --scenario drag
python tools/oracle/review_prince_tentacle_motion.py --scenario stretch
python tools/oracle/review_prince_tentacle_motion.py --side top
python tools/oracle/review_prince_tentacle_motion.py --side bottom --scenario drag
```

输出至 `artifacts/prince/tentacles-walk.gif`、`tentacles-corner.gif`、`tentacles-drag.gif`、`tentacles-stretch.gif`，并各保存一张换点中的 PNG。`stretch` 展示拖向远处、达到牵拉上限、两条松开和松手恢复。`--side` 支持 `top/right/bottom/left`，选择对应起始边并调整移动/拖拽方向，非右边的默认文件名追加边名。可用 `--config`、`--scale`、`--output` 选择另存的配置、显示倍率和 GIF 路径；离边距离、自然长度和方向参数均从该配置读取，镜头显示完整工作区。静态轮廓窗口仅预览 `points` 的素材布局，不展示这些运动参数的效果

常规移动参数集中在 `oracle/motion/prince_tentacles.py`：

- `GripRail.EDGE_INSET`：触手抓附轨道距真实工作区边缘的内缩距离，当前为 `16` 逻辑像素，增大可为末端装饰留出更多空间
- `REPLANT_DISTANCE`：身体沿边移动后，理想抓点与原抓点相差多少逻辑像素才启动换点
- `LEAD_DISTANCE`：新抓点沿移动方向的最大提前量
- `REST_TICKS`：一条触手落点后，到下一条开始换点的最短间隔
- `BACK_OUTSET` / `BACK_DOWN`：根部距胸部向边缘、沿身体向下的偏移，当前分别为 `0` / `4`；三条 `points[0]` 均为 `[0, 0]`，因此共用背部中轴上的出发点。与静态预览的 `back_offset` 分开，后者默认也为 `[0, 4]`
- `MAX_DRAG_STRETCH`：拖拽时相对配置自然长度的最大倍率，当前为 `1.20`
- `DRAG_ROOT_MARGIN`：人偶拖拽可达范围预留的余量，容纳下一帧胸部弯曲和根部惯性

`SupportTentacle` 中可微调形态与回摆：

- `GRAVITY`：固定朝屏幕下方的重力，当前为 `.14`，增大会增强下垂倾向
- `ROOT_DIRECTION_FORCE` / `ROOT_DIRECTION_SPAN`：根部伸出偏好的力度和作用长度比例，当前为 `.65` / `.22`，不影响中后段的自由弯曲
- `BEND_STIFFNESS`：局部抗弯，当前为 `.24`，增大会减少尖折，不恢复参考轮廓
- `REST_VELOCITY_RETENTION` / `MOVING_VELOCITY_RETENTION`：静止与运动时的惯性保留，当前为 `.82` / `.90`，越大回摆越明显
- `SETTLE_SPEED` / `SETTLE_TICKS`：休眠的速度门槛与连续稳定帧数，当前为 `.025` / `24`

长度约束和总长校正集中在 `oracle/motion/prince_tentacle_numeric.py`，使用每条触手自己的坐标和直线缓冲区，避免在迭代中反复创建向量及候选点列表。保留原有的 12 轮约束顺序、16 次总长二分以及休眠规则

触手沿用 `oracle.physics_backend`：`auto` 在 Numba 可用时启用加速，不可用时回退到优化后的 Python 内核；`python` 强制使用 Python，`numba` 强制加速并报告不可用错误。也沿用 `RW_PET_NUMERIC_BACKEND` 环境变量覆盖，创建场景时预热编译，运动过程中不增加首次编译开销

触手绘制使用自适应细分，参数位于 `oracle/graphics/prince_tentacles.py`：`TUBE_SPACING = 4` 为平缓段的最大逻辑像素间距，`TUBE_ERROR = 0.12` 为中心线近似误差，`TUBE_SUBDIVISIONS = 8` 让急弯最多细分至原来约 0.5 逻辑像素的精度。颜色与宽度的配置转折点始终保留，囊肿和亮芯仍按原中心线定位

归一化宽度和颜色采样使用有容量上限的缓存，长度轻微变化时复用同一档采样；缓存键包含配置值，预览重新加载修改后的颜色或宽度时会自动更新。运动位置和物理节点不进入此静态缓存，物理精度与更新频率不受绘制细分影响

相关代码为 `oracle/prince_tentacles.py` 的配置与曲线采样、`oracle/motion/prince_tentacles.py` 的常规支撑，以及 `oracle/graphics/prince_tentacles.py` 的渐变网格和分层精灵绘制；检查命令为 `python -m unittest tests.oracle.test_prince_tentacles tests.oracle.test_prince_tentacle_render tests.oracle.test_prince_tentacle_motion tests.oracle.test_prince_tentacle_numeric tests.oracle.test_prince_tentacle_config`
