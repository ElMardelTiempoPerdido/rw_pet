# 开发指南

以下命令在项目根目录、已激活 `rw_pet` 的环境中运行。应用启动命令、`run_pet.py`、安装后的 `rw-creature-pet` 入口和 TOML 格式保持不变。

## 目录分工

```text
rw_creature_pet/
  app.py                 CLI 参数与生物/窗口分派
  config.py              AppConfig，读取并组合各部分 TOML 配置
  settings_store.py      用户 JSON 配置、原子保存、默认 TOML 迁移
  shared/                已被两种生物共用的工具
    geometry.py          Vec2、Bounds
    timing.py            FixedStepper
    atlas.py             本机图集提取、贴图与着色缓存
    desktop.py           透明置顶、鼠标穿透的窗口设置
    paths.py             默认游戏目录
  lizard/                白蜥蜴与基础蜥蜴实现
    config.py            DebugConfig，仍对应 [debug]
    model.py             LizardBreed、身体质点和连接
    physics.py           重力、碰撞、身体约束
    scene.py             FlatWorld、DebugScene，协调仿真
    gait.py              平地步态与转身
    background.py        背景抓附、爬行和目标追踪
    footholds.py         稳定空间抓点
    gaze.py              独立观察控制
    color_effects.py     发光、闪烁与展示色
    appearance.py        头颈、尾巴及外观状态
    render.py            蜥蜴图集绘制
    debug_window.py      蜥蜴调试界面
    desktop.py           工作区地板、边缘巡游和托盘
  oracle/                迭代器人偶实现
    config.py            OracleConfig、OracleColors
    scene.py             人偶、头颈、机械臂、世界及场景协调
    navigation.py        四边路径、曲线与滑动底座
    behavior.py          停留、移动与珍珠观察
    pose.py              自主躯干朝向
    eyes.py              睁闭眼状态
    pearl.py             珍珠牵引、悬浮点与跟随范围
    glyphs.py            原版珍珠字符提取与缓存
    appearance.py        衣袍、四肢和念珠次级运动
    arm_graphics.py      机械臂外观几何
    cords.py             粗线与细线束仿真
    render.py            人偶绘制与分层缓存
    glow.py              实体 alpha 外发光、局部模糊及缓存
    debug_window.py      人偶调试界面
    desktop.py           桌面工作区、DPI、托盘和场景恢复
    settings.py          首次启动 / 托盘共用的用户设置表单
    settings_style.py    设置窗口专用的灰阶像素控件与边框
    assets.py            设置窗口后台准备图集、投影与语音资源
tests/
  shared/                共用工具测试
  lizard/                蜥蜴回归与窗口测试
  oracle/                人偶回归与窗口测试
  test_app_desktop.py    应用入口分派
  test_import_boundaries.py  包依赖边界
tools/
  lizard/                蜥蜴测量与图集回放脚本
  oracle/                人偶测量与图集回放脚本
    fixtures/            历史算法对照所需的源码快照
docs/                    使用说明、实现依据和开发记录
artifacts/               回放图片、动画、数据、测试日志；不提交版本管理
```

源码目录中去掉重复的 `oracle_` / `render_oracle` 前缀，例如绘制器现在位于 `rw_creature_pet.oracle.render`。蜥蜴身体数据位于 `rw_creature_pet.lizard.model`。旧的平铺模块入口已迁移，项目内导入、测试、mock 路径和回放脚本均使用新路径；自写脚本如导入旧模块，也需相应更新。

## 依赖方向

- `shared` 不依赖应用配置或任何生物模块。
- `lizard` 和 `oracle` 不相互导入；共用计时器、几何、图集和透明窗口设置均从 `shared` 获取。
- 仿真场景不依赖 Qt；图集与窗口模块可以依赖 Qt。
- 根目录的 `config.py` 组合两种生物的配置。各生物的纯仿真只读取自己的配置类型；窗口可以接收 `AppConfig`。
- `app.py` 只在选择生物和运行模式后导入对应窗口。

本轮只抽取已有的共用部分，没有增加生物基类、插件注册系统或统一物理层。两种生物的运动约束、渲染及桌面恢复策略继续独立实现。

## 配置

根目录 `config.toml` 保持用户现有内容：`game_dir` 指向游戏目录，`[debug]` 为蜥蜴场景，`[oracle]` 与 `[oracle.colors]` 为人偶设置。此次目录迁移不改字段名、默认参数或读写策略；启动仍不会覆盖配置。默认游戏路径集中在 `shared/paths.py`。

## 测试

```powershell
# 全量回归
python -m unittest discover -s tests -t . -v
# 按生物运行
python -m unittest discover -s tests/lizard -t . -v
python -m unittest discover -s tests/oracle -t . -v
# 共用工具、入口和依赖边界
python -m unittest discover -s tests/shared -t . -v
python -m unittest tests.test_app_desktop tests.test_import_boundaries -v
# 单项示例
python -m unittest tests.oracle.test_pearl_follow -v
```

`-t .` 让子目录测试按 `tests.lizard.*` / `tests.oracle.*` 导入；保留各层 `__init__.py`，否则 unittest 可能漏掉子目录。真实图集测试需要本机游戏，缺少游戏时会明确跳过。Qt 窗口测试使用 offscreen；测试截图仍写入根目录 `artifacts`。

## 回放与性能工具

回放脚本从原来的 `artifacts/*.py` 移到 `tools`，输出仍在 `artifacts`，从而区分可复用代码与生成结果。脚本按文件路径直接运行，会自行定位项目根目录：

```powershell
python tools/lizard/review_flat_stride.py
python tools/lizard/measure_wall_rhythm.py after
python tools/lizard/review_front_led_body.py
python tools/oracle/review_oracle.py
python tools/oracle/review_oracle_pearl_follow.py
python tools/oracle/review_oracle_zoom.py 1.5
```

Pillow 随项目依赖安装，用于可选的实体外发光，也供回放工具生成 GIF 或图表。`review_oracle_glow.py` 导出真实素材在深浅背景的对照与 1× / 1.5× / 2× 的纯绘制耗时，不修改用户设置。Oracle 的 `review_oracle_desktop.py --native-click` 会执行真实窗口点击验证，普通回放无需这个参数。`fixtures/cords_before_lengths.py` 仅供线长前后对照，不参与桌宠运行。

## 打包检查

### Windows 单文件 EXE

在 Windows 的 `rw_pet` 环境中运行：

```powershell
python -m pip install -e ".[speedups,build]"
python tools/packaging/build_bell.py
python tools/packaging/verify_bell.py
```

输出为 `dist/BellPet.exe`，双击直接进入 Bell 桌面模式，首次运行显示设置窗口。EXE 无控制台，内含 Python、Qt、Numba 数值加速、资源提取依赖及根目录 `config.toml` 的当前默认值；构建时不会读取或打包个人 `settings.json`、游戏目录、图集/语音缓存。把这一份 EXE 复制给其他 Windows x64 用户即可，运行时仍需选择其本机 Rain World 安装目录。

调试窗口仅通过命令行进入：`.\dist\BellPet.exe --debug`，或源码入口 `python run_bell.py --debug`。默认沿用已保存设置，`--config config.toml` 可指定调试用 TOML；`--debug` 与 `--desktop` 互斥。托盘双击不再打开调试窗口。

默认启用组件裁剪：移除未使用的 QML/虚拟键盘、PDF 插件、软件 OpenGL 回退、视频 FFmpeg 后端及 Pillow AVIF 编解码器。当前产品使用 QWidget/QPainter、PNG 和本地 WAV，保留原生 Windows 音频、系统输入法、NumPy 和 Numba/LLVM。`--full` 可恢复自动收集的完整依赖，供新增功能时对照。

可选使用 [UPX 官方发行版](https://github.com/upx/upx/releases)（本轮使用 5.2.1 win64）：

```powershell
python tools/packaging/build_bell.py --name BellPet-UPX --upx-dir build/tools/upx-5.2.1-win64
python tools/packaging/verify_bell.py --exe dist/BellPet-UPX.exe --report artifacts/package-size/upx-verification.json
```

UPX 是构建工具，不随桌宠分发。未传 `--upx-dir` 时不启用 UPX；不要对生成后的整个 EXE 再执行 UPX。由 PyInstaller 压缩内部 DLL/PYD，并自动跳过 CFG 二进制和 Qt 插件，规则见 [PyInstaller UPX 文档](https://www.pyinstaller.org/en/stable/usage.html#using-upx)。如果未来加入视频、PDF、AVIF、QML 或 OpenGL 控件，应同步恢复对应依赖并重新验收。

文件图标使用 `rw_creature_pet/ico/bell_icon_16_dark.png` 和 `bell_icon_dark.png` 两个原始分辨率，构建时直接封装到 ICO，原图不改动。托盘图标仍使用其独立的 `bell_icon_16.png`。单文件启动时会将运行依赖解压到系统临时目录，首次准备资源/编译数值内核可能稍慢；设置与提取缓存保存在用户目录，因此无需将 EXE 放在可写目录中。

包内保留离屏自检入口，检查默认配置、设置保存、真实图集/字符/10 段语音提取、Numba、Qt 音频解码与静音播放、桌面初始化、工具栏、调试入口及含外发光的绘制：

```powershell
Start-Process -FilePath .\dist\BellPet.exe -ArgumentList '--self-test', '.\artifacts\frozen-smoke' -WindowStyle Hidden -Wait
Get-Content -Encoding UTF8 .\artifacts\frozen-smoke\report.json
```

自检使用指定输出目录下独立的 `profile`，不改动日常用户配置；首次使用空目录可覆盖冷缓存提取流程。`report.json` 的 `ok` 应为 `true`。`verify_bell.py` 还会检查 PE 图标与依赖，将 EXE 复制到新建的中文路径，并移除子进程 PATH 中的 Conda 路径后执行此自检，结果写入 `artifacts/bell-package-verification.json`。该自检使用离屏 Qt 平台，不能代替朋友设备上的桌面显示、点击穿透和音频试听验收。

音频问题可单独执行 `python tools/packaging/audio_probe.py artifacts/audio-probe --seconds 120 --simulation-seconds 1800`。它只读取当前设置，在独立缓存内准备十段短音频；离屏运行桌面窗口，依次验证未互动、模拟拖动、正常松手后的真实等待和加速自主活动。使用真实 Qt 播放后端并静音，`events.jsonl` 记录请求、文件和播放起止，`report.json` 记录长度与哈希。打包入口对应 `BellPet.exe --audio-probe 输出目录`（需重新构建含该入口的版本）。此检查不模拟 Windows 原生鼠标事件丢失。

`python tools/oracle/reproduce_missing_drag_release.py` 则故意省略松开和失去捕获事件，再发送 `buttons=NoButton` 的移动事件，输出 `artifacts/audio-missing-release.json`。这是拖动状态残留的故障注入用例，不等同于在真实设备上复现了系统丢事件。

2026-09-28：首次未裁剪的 Windows x64 单文件包为 122,720,137 字节（约 117 MiB）。在独立中文目录、仅保留系统 PATH、空用户配置和资源缓存的条件下验证通过；16px / 32px 的 PE 图标内容与两张 `_dark` PNG 完全一致。打包规则显式补齐 libffi、FMOD、Unity 类型树和 archspec CPU 数据，并过滤构建环境 PATH 中与 Windows 系统 ICU 同名但导出不兼容的 DLL。

同日完成组件裁剪和 UPX 实测，两版均通过隔离自检（额外覆盖静音播放和调试窗口）：

| 版本 | 字节 | 体积 | 相对原包减少 |
| --- | ---: | ---: | ---: |
| 原包 | 122,720,137 | 117.04 MiB | — |
| 精简、不使用 UPX | 93,871,025 | 89.52 MiB | 23.51% |
| 精简 + UPX 5.2.1 | 75,166,942 | 71.68 MiB | 38.75% |

常规 `dist/BellPet.exe` 更新为精简、不使用 UPX 的版本；UPX 版单独位于 `dist/BellPet-UPX.exe`。两版都保留 Numba 加速和全部现有桌宠功能，文件 icon 不变。本机这轮冷缓存自检分别耗时 8.84 / 21.92 秒（从包内自检开始计时，含提取、编译、仿真、播放与调试窗口，不代表日常启动时间）；UPX 以额外解压工作换取更小文件。原包保留于 `artifacts/package-size/BellPet-original.exe`，尺寸、裁剪明细与各版本验证报告也位于该目录。

### Python wheel

```powershell
python -m pip wheel --no-deps --no-build-isolation . --wheel-dir artifacts/wheels
```

setuptools 自动发现 `rw_creature_pet*` 子包，测试、工具、历史对照与游戏资源不进入应用 wheel。根目录 README 暂作简短入口，完整项目介绍可以独立重新编写。

## 本次目录迁移验证

2026-09-24：全量 179 项测试通过，无失败、错误或跳过，耗时 814.249 秒；日志为 `artifacts/package-layout-tests.txt`。其中保留原有 177 项验收，新增两项包依赖边界检查，共享图集用例从蜥蜴测试移动到 `tests/shared`。

另外完成 wheel 构建、源码目录之外的 wheel 导入与两种仿真启动、CLI 帮助入口，以及文档链接和代码路径检查。对照迁移前后的 109 个类/函数及蜥蜴配置定义，除导入位置外没有逻辑变化；用户 TOML 校验值保持不变。已运行并查看两种生物的真实图集回放，输出仍在 `artifacts`。汇总见 `artifacts/package-layout-validation.json`；本轮没有重新执行原生 Windows 点击穿透检查。
