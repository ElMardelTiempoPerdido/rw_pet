# 开发指南

以下命令在项目根目录、已激活 `rw_pet` 的环境中运行。应用启动命令、`run_pet.py`、安装后的 `rw-creature-pet` 入口和 TOML 格式保持不变。

## 目录分工

```text
rw_creature_pet/
  app.py                 CLI 参数与生物/窗口分派
  config.py              AppConfig，读取并组合各部分 TOML 配置
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
    debug_window.py      人偶调试界面
    desktop.py           桌面工作区、DPI、托盘和场景恢复
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

部分工具使用 Pillow 生成 GIF 或图表，可用 `python -m pip install Pillow` 安装；应用运行不因此增加依赖。Oracle 的 `review_oracle_desktop.py --native-click` 会执行真实窗口点击验证，普通回放无需这个参数。`fixtures/cords_before_lengths.py` 仅供线长前后对照，不参与桌宠运行。

## 打包检查

```powershell
python -m pip wheel --no-deps --no-build-isolation . --wheel-dir artifacts/wheels
```

setuptools 自动发现 `rw_creature_pet*` 子包，测试、工具、历史对照与游戏资源不进入应用 wheel。根目录 README 暂作简短入口，完整项目介绍可以独立重新编写。

## 本次目录迁移验证

2026-09-24：全量 179 项测试通过，无失败、错误或跳过，耗时 814.249 秒；日志为 `artifacts/package-layout-tests.txt`。其中保留原有 177 项验收，新增两项包依赖边界检查，共享图集用例从蜥蜴测试移动到 `tests/shared`。

另外完成 wheel 构建、源码目录之外的 wheel 导入与两种仿真启动、CLI 帮助入口，以及文档链接和代码路径检查。对照迁移前后的 109 个类/函数及蜥蜴配置定义，除导入位置外没有逻辑变化；用户 TOML 校验值保持不变。已运行并查看两种生物的真实图集回放，输出仍在 `artifacts`。汇总见 `artifacts/package-layout-validation.json`；本轮没有重新执行原生 Windows 点击穿透检查。
