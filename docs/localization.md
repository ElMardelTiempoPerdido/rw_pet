# 界面语言

托盘右键菜单的 **语言/language → 中文 / English** 可以即时切换托盘菜单、设置窗口及行动工具栏，包括提示、校验错误和操作反馈。中文界面目前统一使用简体中文。

首次启动或旧用户配置首次增加此字段时，根据系统的首选**界面语言**选择：简体／繁体中文选中文，其余选英文。地区、时区及备用中文语言不参与判断。选择结果保存到 `%LOCALAPPDATA%\rw_creature_pet\settings.json` 的 `config.ui.language`；后续使用已保存的值，不因系统语言变化而改动。

默认 TOML 中的配置为：

```toml
[ui]
language = 'auto' # auto / zh / en；auto 在加载时解析，用户文件保存确定的 zh 或 en
```

切换只更新文字，不重新创建场景、重置人偶或触发行动。打开的设置窗口保留控件、未保存输入、选中的标签页和滚动位置；后续保存仍使用新语言。切换时若配置写入失败，会恢复先前语言并提示。英文标签允许换行，设置窗口在工作区允许时适度加宽。

## 增加或修改译文

- 中文原文保留在源代码中；英文集中在 `rw_creature_pet/translations/en.ts`，运行时由 Qt 加载编译后的 `en.qm`。
- 设置窗口的 `WidgetTexts` 在首次翻译前登记静态标签、按钮、提示和页签，之后原位刷新；不会登记用户输入值。动态状态使用 `tr(...)`。
- 需要插入数值、路径或嵌套错误时，用 `Message('原文 {name}', name=value)` 保留原文及参数，到界面显示时才翻译。不要先拼接 f-string 或对异常调用 `str()`，否则无法匹配原文或再次翻译。`shared/messages.py` 不依赖 Qt。
- 校验和资源层可以 `raise ValueError(Message(...))`，保持既有异常类型。
- 本轮范围不含开发者调试窗口、命令行帮助及系统返回的原始错误描述。

在 `rw_pet` 环境中运行：

```powershell
# 扫描这三处 UI 和相关校验文件，添加缺少的原文；未翻译时返回非零。
python tools/update_translations.py
# 用 Qt Linguist 或文本编辑器填写 en.ts 的 translation，保留所有 {参数}。
pyside6-linguist rw_creature_pet/translations/en.ts
# 重新检查并生成随程序分发的 en.qm。
python tools/update_translations.py --compile
python tools/update_translations.py --check
python -m unittest tests.test_i18n -v
```

新增相关源文件时，将其加入脚本的 `FILES`。声明式表单中请用完整原文，不拼接半句话；脚本按 AST 提取，忽略注释、文档字符串和 f-string 片段。测试还检查实际设置控件、占位符以及 TS 与 QM 内容的一致性。

`pyproject.toml` 和 `tools/packaging/bell.spec` 已包含翻译资源；打包规格还包含 Qt 自带的中文通用对话框译文。正常运行无需安装 Linguist 或翻译工具，也不需要联网。
