# 生物 ID 与原版随机参数兼容（待实现）

记录日期：2026-09-08

## 当前决策

先完成 WhiteLizard 桌面平地行走。暂不实现原版随机数兼容；初期使用一组明确的固定个体参数调试，不宣称输入原版 ID 能获得相同个体。待桌宠初步运行后，再实现并验证兼容生成器。

## 兼容目标

在明确的游戏版本和 Unity 版本下，相同有效随机种子生成与原版相同的 WhiteLizard 先天外观和性格。伪装色、健康、驯服关系、位置和后续行为属于运行状态，不由 ID 单独决定。

当前参考源码位于 `D:\CODES\CS\rw_src`，原桌宠参考位于 `D:\CODES\PY\slugcatpet`。准确游戏版本和 Unity 版本尚待核实。

## 已确认的源码事实

- `EntityID.RandomSeed` 默认返回 `number`；存在有效 `altSeed` 时返回替代种子。完整 ID 包含 `spawner` 和 `number`，不同完整 ID 不必对应不同种子。
- `AbstractCreature.Personality` 构造函数保存随机状态，使用 ID 设置种子，生成性格，再恢复状态。
- `LizardGraphics` 构造函数也独立设置同一种子，再调用 `GenerateIvars()`；不能接着性格生成结束后的随机序列继续生成外观。
- 外观包含 `headSize`、`fatness`、`tailLength`、`tailFatness`、`tailColor`。WhiteLizard 的 `tailColor` 固定为 0。
- 头大小先随机生成，再有概率覆盖为 1；被覆盖的抽取仍消耗随机数。WhiteLizard 尾色条件中的短路则不消耗右侧随机数。
- 需要一并对齐 `Custom.ClampedRandomVariation`、`RandomDeviation`、`SCurve`、`PushFromHalf` 等实际调用到的辅助函数。

## 实施方案

1. 确认本机游戏和 Unity 版本，记录参考程序集的哈希。
2. 在实际游戏运行环境内导出指定 ID 的性格和外观参数，作为对照样本；必要时额外采集随机状态和浮点位模式。探针应保存并恢复随机状态。
3. 实现独立的 Python Unity 随机兼容生成器，处理 32 位溢出、有符号转换、种子初始化及 `Random.value` 转换。按实际需要支持其他随机 API。
4. 按原版入口和抽取顺序实现 WhiteLizard 参数生成，不改变条件短路或省略中间抽取。
5. 处理 C# 单精度计算及中间舍入；不能默认 Python 双精度计算后最终转换一次即等价。
6. 分别验证随机状态、单次随机值及最终参数；覆盖多个种子、边界值和分支。位级一致与容差内接近应分别报告。
7. 存档保存 ID、有效种子、生成规则版本和实际参数，避免算法更新改变已有个体。

导出工具仅用于开发验证；完成兼容后，玩家输入 ID 应能离线生成个体。可以后续提供原版个体参数导入作为补充，但当前不开发该入口。

## 外部参考（尚未验证对本机版本的兼容性）

- Unity Random 文档：<https://docs.unity.cn/cn/2023.1/ScriptReference/Random.html>
- Unity C# 原生接口绑定：<https://github.com/Unity-Technologies/UnityCsReference/blob/master/Runtime/Export/Random/Random.bindings.cs>
- C# 近似兼容实现，作者明确指出浮点误差：<https://gist.github.com/macklinb/a00be6b616cbf20fa95e4227575fe50b>
- Rust 实现参考：<https://github.com/Minavoii/unity-random>

Unity 文档说明算法为 Xorshift128，但算法名称不足以保证初始化、浮点映射和全部 API 行为一致。参考实现应经过本机游戏对照验证后才采用；采用代码前检查相应许可。
