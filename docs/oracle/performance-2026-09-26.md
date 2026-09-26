# Oracle 运动性能基线与优化建议

日期：2026-09-26。下面先保留优化前的诊断基线；诊断阶段没有修改运行时代码、配置或安装计算库。后续实施结果见文末“第一轮优化结果”。

## 测量条件

- Windows，i7-9700KF，8 核 / 8 逻辑处理器；RTX 2070 SUPER。
- `rw_pet`：Python 3.11.16、PySide6 6.11.2。NumPy、Numba、Cython、CuPy 尚未安装。
- 用户当前配置：矩阵 7、内圈 4、外圈 2、固定珠 2、卫星 1；共 16 颗。
- 40 Hz 模拟，30 Hz 绘制，物理像素 1 倍。保留当前衣袍、线缆长度和节距、所有配色。
- 配置 SHA256：`7467013eca611b57eb27a80ed461d55318be0d3ab0fc99e4877efd29959b0f32`，测试前后相同。
- 离屏使用真实图集和字形缓存、预乘透明 QImage。加载和预热不计入；分区计时使用轻量包装函数，存在少量计时开销。
- cProfile 另跑，只用于定位调用热点，不能将其放大后的时间当作正常运行时间。

## 真实桌面窗口

自动退出的透明、穿透桌面实例，主屏 DPR 1.5，实际人偶 1 倍。沿上边移动 12.008 秒：

| 指标 | 结果 |
| --- | ---: |
| 本进程 CPU 时间 | 10.281 秒 |
| 换算整机平均 CPU 占比（8 逻辑处理器） | 10.70% |
| 物理更新频率 | 39.89 Hz |
| 绘制频率 | 30.06 Hz |
| 丢弃的模拟时间 | 0 秒 |
| 每次模拟：平均 / P95 | 7.83 / 9.01 ms |
| paintEvent：平均 / P95 | 12.98 / 18.53 ms |

这是短时、特定路径的平均值，不是用户看到的 15% 峰值复现；CPU 时间不包含其他进程或 Windows DWM。计数方式也不完全等同于任务管理器的瞬时显示。

## 离屏分区计时

主屏物理工作区 2560×1540，2400 次连续绕边模拟；覆盖上、右、下边及相邻拐角。另一个 960×600 回放完成四边一圈，1555 次更新。以下分项来自主屏尺寸回放：

| 模拟部分（40 Hz） | 平均 ms / tick |
| --- | ---: |
| 主线缆 | 0.94 |
| 14 条细线缆合计 | 3.50 |
| 衣袍物理 | 1.05 |
| 念珠项链物理 | 0.41 |
| 机械臂物理 | 1.12 |
| 三类珍珠组运动合计 | 0.42 |
| 完整模拟 | 8.41 |

| 绘制部分（30 Hz） | 平均 ms / frame |
| --- | ---: |
| 几何与指令建立（包含下面三项） | 7.17 |
| 其中：机械臂外观 | 3.41 |
| 其中：线缆外观 | 1.73 |
| 其中：身体后层与前层 | 1.38 |
| 已缓存指令在 QPainter 上重放 | 2.81 |
| 珍珠与字形绘制 | 0.51 |
| 头部绘制 | 0.22 |
| 完整绘制（含清空目标图） | 12.49 |

分项有嵌套关系，不可将所有行相加。按 40/30 Hz 加权，离屏工作量约 711 ms / 模拟秒：线缆物理约占 25%，几何与指令建立约 30%，QPainter 指令重放约 12%。这只是计时预算分解，不是独立模块的任务管理器百分比。

人偶停稳、外观休眠后，400 次更新中线缆和衣袍物理均未执行；模拟仍约 0.77 ms，绘制约 4.76 ms。环绕珠、卫星持续运动会继续请求刷新，已休眠的人偶仍每帧重放约 2.76 ms 的绘图指令。缓存目前主要缓存几何和命令，没有完整缓存静止层的最终像素。

## 原版与当前实现的差别

`D:/CODES/CS/rw_src/OracleGraphics.cs` 的 `UbilicalCord`：80 个主线点、14×20 个细线点，当前项目保留了这个数量。原版 `Update` 中相邻约束主要做两个方向的扫描，同时修正位置和速度；当前是带固定端、供线、误差检查的迭代位置求解器，不能将其遍数直接等同于原版扫描次数。

本次移动回放中，细线约 90% 的调用用满 10 遍。当前缓冲区虽已改成标量列表复用，内部循环仍由 Python 执行。原版并未在这里使用 GPU 计算线缆；这些是 C# 数值循环。原版创建网格并移动顶点，而当前渲染还反复建立 Qt 几何对象、记录和重放命令，CPU 开销结构不同。

## 建议顺序

1. **先做 CPU 编译内核对比。** 将线缆积分、约束和误差检查提取成纯数值函数；持续复用连续数组，避免每条小约束都跨 Python / 编译层调用。用 Numba `njit(cache=True)` 验证收益，保留 Python 后端。先保持双精度、遍历顺序、容差和休眠语义，不开启 `fastmath` 或多线程。若面向发行包，更适合评估 Cython 编译扩展，减少终端用户的 JIT 启动负担。
2. **减少绘制端的 Python 工作。** 预计算机械臂截面固定参数、衣袍固定拓扑和颜色；避免缓存的身体命令每次又展开记录到整帧列表。再按测量结果决定是否把机械臂数值几何也编译。此处并非单纯的显卡像素填充瓶颈。
3. **改善静止层与重绘区域。** 静止的人偶 / 线缆可缓存到紧凑的透明图层，保留头部与珍珠独立更新；合并新旧外形包围盒进行局部刷新，验证透明窗口残影与原有遮挡顺序。不要用整屏大图作为所有层的缓存。Windows 原生窗口实际收益需复测。
4. **按剩余热点扩展。** 衣袍、项链求解可以共享数值内核方案。不要先削减珍珠数量；当前珍珠运动约占加权工作量 2.4%，不是主要计算瓶颈。
5. **GPU 渲染作为后续可选后端。** Qt Quick 场景图或 OpenGL 可缓存网格并批量提交。但更换绘图目标不会自动消除 Python 建立几何 / 指令的成本，还要验证透明、穿透、DPI 和像素外观。保留软件回退。

NumPy 能提供数组，但相邻绳段读写有先后依赖，将所有相邻边一次向量化会改变求解顺序；只替换 `hypot` 等小运算也可能增加调用开销。Numba / Cython 更适合保留现有循环结构。

GPU 物理技术上可做，但当前只有几百个节点，每条绳内有顺序依赖，QPainter 还需要 CPU 侧坐标。GPU 调度、同步、结果回传和实现维护成本可能抵消收益，这是基于任务规模的判断，尚未做 GPU 对比实验。更适合先降低 CPU 总工作量，而不是仅把工作拆到更多线程。

不应承诺具体加速倍数：即使线缆物理成本降到零，按此离屏基线也只能去掉约四分之一总工作量，渲染必须一起优化。

## 重跑与资料

```powershell
D:\Anaconda3\envs\rw_pet\python.exe tools/oracle/profile_oracle_current.py
D:\Anaconda3\envs\rw_pet\python.exe tools/oracle/profile_oracle_current.py --desktop-seconds 12
```

第二条会短暂显示可穿透的桌面实例并自动关闭。结果写入 `artifacts/oracle-current-performance*.json`、`oracle-current-performance-profile.txt` 和 `.pstats`；这些为本机诊断产物，不提交游戏素材。

- [Numba: Performance Tips](https://numba.readthedocs.io/en/stable/user/performance-tips.html)
- [Numba: JIT compilation and cache](https://numba.readthedocs.io/en/stable/user/jit.html)
- [Cython: Typed Memoryviews](https://docs.cython.org/en/stable/src/userguide/memoryviews.html)
- [Qt: QPainter performance](https://doc.qt.io/qt-6/qpainter.html#performance)
- [Qt Quick Scene Graph](https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph.html)
- [CuPy: Performance Best Practices](https://docs.cupy.dev/en/stable/user_guide/performance.html)
- [CuPy: host and device arrays](https://docs.cupy.dev/en/stable/user_guide/basic.html)

## 第一轮优化结果

已落实线缆 CPU 编译内核、几何与指令复用、静止位图层和桌面局部刷新。未调整
帧率、绳索节点数 / 长度 / 迭代容差、用户配色、珍珠数量或行为节奏，也未增加 GPU 后端。
`config.toml` 与基线快照逐字节相同。`rw_pet` 已安装 Numba 0.65.1、llvmlite 0.47.0、NumPy 2.4.6；依赖检查通过。

### 实际桌面结果

同一台设备、150% DPI、物理像素 1 倍、相同上边移动脚本，每次约 12 秒，独立于测试进程运行：

| 指标 | 优化前 | 优化后 |
| --- | ---: | ---: |
| 移动时本进程平均整机 CPU 占比 | 10.70% | 6.43% |
| 每次模拟平均耗时 | 7.83 ms | 4.70 ms |
| paintEvent 平均耗时 | 12.98 ms | 9.81 ms |
| paintEvent P95 | 18.53 ms | 14.28 ms |
| 物理频率 / 绘制频率 | 39.89 / 30.06 Hz | 39.94 / 30.01 Hz |
| 丢弃的模拟时间 | 0 | 0 |

移动平均 CPU 下降约 40%。优化后，人偶停稳、环绕珠和卫星继续运动时，平均
整机 CPU 约 0.98%，paintEvent 平均 1.07 ms，其中 renderer 约 0.46 ms。
这是特定路径短测的平均值，不保证所有动作或低配设备都达到相同占比；瞬时长帧仍可能出现。

相同 2560×1540 离屏回放的分项结果（`oracle-optimized-performance.json`）：

| 热点平均耗时 | 优化前 | 优化后 |
| --- | ---: | ---: |
| 线缆物理 / tick | 4.44 ms | 1.62 ms |
| 全部模拟 / tick | 8.41 ms | 5.42 ms |
| 几何与指令建立 / frame | 7.17 ms | 5.17 ms |
| 其中机械臂外观 / frame | 3.41 ms | 2.14 ms |
| 移动完整绘制 / frame | 12.49 ms | 10.04 ms |
| 静止完整绘制 / frame | 4.76 ms | 2.22 ms |

离屏工具仍每次清空整张 QImage，因此没有体现桌面局部刷新的全部收益。静止指令
重放在预热后降为零，转为位图合成；原生桌面结果更接近日常使用方式。

### 一致性与验证

- 与优化前快照同步回放 2800 tick，最大节点偏差约 `1.27e-10` 逻辑像素，休眠时刻一致。
- 7 张抽查移动帧逐像素一致；静止缓存与直接绘制仅有少量颜色通道 `1/255` 的差异。
- 缓存验证包括 0.5 / 1 / 2 / 4 倍、DPR 1 / 1.25 / 1.5 / 2，以及换色、唤醒与重复绘制。
- 局部刷新验证包含四边移动和关闭珍珠组。透明覆盖逐像素一致；0.5 倍、125% DPI
  的 Qt 裁剪路径中，少量渐变 RGB 存在至多 `4/255` 舍入差异，alpha 完全一致。
- Oracle 完整回归覆盖 170 项：初跑 167 项通过；两项旧测试仍假设存在额外单珠，
  已在优化前快照复现并更新为当前珠组 / 实际观察目标；另一项是上述 RGB 舍入断言。
  修正后进行针对性复测，相关用例通过。最后还复测了编译回退与绘制缓存路径。
- 图片：`artifacts/oracle-optimization-comparison.png`，左右分别为优化前 / 后。
- 记录：`oracle-optimization-comparison.json`、`oracle-damage-pixels.json`、
  `oracle-optimization-tests.log`、`oracle-optimization-recheck.log`、`oracle-optimization-final-tests.log`。
- 原生测量：`oracle-optimized-performance-desktop.json`、`oracle-optimized-idle-desktop.json`。

### 使用与回退

默认 `physics_backend = "auto"`，缺少 Numba 时使用同算法的 Python 内核；可在
`[oracle]` 中显式设置 `"python"` 或 `"numba"`。Numba 在场景创建时预热并缓存编译结果，
首次启动可能稍慢。其他设备用 `python -m pip install -e ".[speedups]"` 安装可选依赖。
当前数值内核使用标准库连续双精度数组，避免每轮把 Python 对象转换成 NumPy 数组。
本轮优化当时的静止缓存只用于桌面。后续全身像素化已将其替换为桌面与调试共用的
1 倍逻辑像素局部图层；颜色和外观帧改变时失效，缩放与 DPI 改变直接复用。
因此不再为 4× 放大镜分配四倍宽高的图层。下方记录这项后续改动的测量。

## 后续：全身像素化

在相同原生透明桌面、150% 系统 DPI、1× 物理像素、顶部移动路径下，修改前后
各测量 12 秒，未同时运行其他测试进程：

| 指标 | 加入像素化前 | 加入像素化后 |
| --- | ---: | ---: |
| 平均整机 CPU | 6.66% | 6.21% |
| 平均物理步进 | 4.80 ms | 4.79 ms |
| 平均 paintEvent | 9.90 ms | 9.86 ms |
| paintEvent P95 | 14.71 ms | 14.39 ms |
| 绘制频率 | 30.09 Hz | 29.98 Hz |
| 丢弃的模拟时间 | 0 | 0 |

这次短测未见明显性能退化；小幅差异不能视为稳定加速收益。原始数据为
`artifacts/oracle-pixel-before-desktop.json` 和 `oracle-pixel-after-desktop.json`。
绘制缓存测试额外验证：同一帧的 1×/2×/4× 和不同 DPI 不重新重放身体指令，
眼睛开合不重建休眠的衣袍与线缆图层；局部刷新仍与完整画面的透明覆盖一致。

人偶停稳、环绕珠和卫星继续运动时，12 秒实测平均整机 CPU 为 0.91%，平均
paintEvent 为 1.08 ms（renderer 0.46 ms），30.01 次绘制/秒，无模拟时间丢弃。
数据为 `oracle-pixel-idle-desktop.json`。此次 31 项相关回归通过，涵盖逻辑像素与
DPI、缓存/开合、四边外形范围、衣领袖口遮挡、珍珠独立绘制和透明刷新；没有重跑
全部生物的物理测试。日志为 `oracle-pixel-tests.log` 和 `oracle-pixel-appearance-tests.log`。
用户 `config.toml` 的 SHA256 与修改前一致。

## 后续：独立光环图层

同机、相同珠组及 150% 系统 DPI / 1× 物理像素下，串行执行四个原生透明桌面
12 秒样本。只在内存中切换 `halo_enabled`，不改写配置：

| 场景 | 光环关闭 | 光环开启 |
| --- | ---: | ---: |
| 人偶停稳、珍珠仍运动：平均整机 CPU | 0.78% | 1.40% |
| 同场景平均 paintEvent | 1.04 ms | 2.15 ms |
| 顶部持续移动：平均整机 CPU | 6.47% | 6.78% |
| 同场景平均 paintEvent | 9.90 ms | 10.90 ms |

四次均保持约 40 Hz 模拟、30 Hz 绘制，没有丢弃模拟时间。以上是本机短测，非峰值
或所有设备的保证。开启光环会有持续视觉更新，但身体、衣袍及线缆仍复用休眠缓存；
隐藏光环会停止其状态更新。关闭全部持续视觉活动后仍可停止主动重绘。

原始数据：`artifacts/oracle-halo-{idle,moving}-{off,on}-desktop.json`。
复测命令为 `tools/oracle/profile_oracle_current.py --desktop-seconds 12`，
加 `--desktop-idle` 测人偶停稳，加 `--no-halo` 做对照。

本轮 37 项不同的相关用例通过（日志共 39 次执行，透明刷新两项重复覆盖）：
光环交互/重置/边界、独立随机流、透明度/缓存、四边真实图集外形、缩放与 DPI、
桌面工作区重建、调试控件及暂停、眼睛和珍珠独立绘制。日志为
`oracle-halo-tests.log`、`oracle-halo-regression.log`、`oracle-halo-window-tests.log`。
没有运行全部生物的物理回归；本次不改变其求解或行为逻辑。
