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

拖拽时按点击区域选择最近的身体轴节点，在此处施加抓取力。Prince 拖拽期间不主动注视鼠标，原先的注视方向平滑回到中性，避免身体持续朝抓取点主动弯折。导航支点仍保留机械臂长度和工作区边界约束；视觉身体会由抓取点逐段带动，未抓取的部分保留惯性和下垂感。松手后平滑恢复到正常体态和活动带，全部身体节点与下摆停稳后允许休眠

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
- `oracle/interaction/drag.py`：按实际身体区域抓取，导航和机械臂边界保持通用约束
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
