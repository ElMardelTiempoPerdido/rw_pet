# rainworld desktop pet

开发中：白蜥蜴 / 手势之铃，**未完成，可能存在各种bug和性能问题**

如果您希望直接获取桌宠游玩，请直接下载release中的压缩包（需要将exe和presets解压至同一目录下），勿下载source code.zip

---

默认鼠标穿透，从系统托盘右键菜单可以启用接收鼠标输入，此时可使用类似mousedrag mod的效果拖动桌宠

此桌宠运行需要本机已安装雨世界本体，并在设置或 config.toml 中配置游戏目录，用于读取部分游戏资源

（如果您有downpour或watcher dlc，将有部分依赖dlc资源的扩展选项可用

---

以调试方式启动：

```powershell
# 白坨
python run_pet.py --creature lizard
# 手势之铃
python run_pet.py --creature oracle
```

导出发布配图（在安装了项目依赖的 Python 3.11+ 环境中运行）：

```powershell
python tools/oracle/export_preset_previews.py
```

脚本读取 `presets/profiles` 中所有角色当前保存的配置，以 **1× 原始像素、正面平视、透明背景** 横向绘制在同一张 PNG 上；普通角色按衣袍底部最低处对齐，腿部和柔性部件允许向下伸出，Prince 保持按完整角色底部对齐。珍珠行自动下移至所有部件下方，三颗珍珠从左到右依次为 **彩珍珠辅色、彩珍珠主色、普通珍珠色**。保留角色默认眼形与开闭状态、服装和附件，隐藏机械臂、支架、线缆、光环与外发光，不绘制名称。

输出目录为 `artifacts/preset-previews`，文件名形如 `presets_front_1x_20261109_150533_266764.png`，每次新建文件，不覆盖旧图。不修改角色、历史或本机设置；同 ID 的重复版本按角色库规则选择最新有效版本，损坏配置会报错。

可用 `--profiles-dir`、`--output-dir`、`--game-dir` 指定角色库、输出目录和游戏目录；默认路径以工程目录为基准，游戏目录读取工程的 `config.toml`。脚本离屏运行，无需启动桌宠。

---

修改设置面板中的文本后，需要重新编译以生效：

```
python tools/update_translations.py --check --compile
```

## 资源与版权说明

- 本项目为雨世界非官方粉丝作品，项目及其衍生版本均禁止用于任何商业活动
- 原作名称、角色与素材归各自权利人所有；第三方代码及组件保留原有许可
- 本仓库不分发游戏素材，所需资源从使用者本机的正版游戏中读取或提取，仅供本地运行，未经许可勿再次分发；本项目不授予任何原作素材相关权利

## 参考

此桌宠实现过程中参考了以下工程，非常感谢！

- 鼠标拖动mod [woutkolkman / MouseDrag](https://github.com/woutkolkman/mousedrag)
- 蛞蝓猫桌宠 [lingxiaojun / SlugcatPet](https://github.com/lingxiaojun/slugcatpet)

---


In development: White Lizard / Bell of Gesture. 

**This project is unfinished and may have bugs and performance issues.**

To launch in debug mode:

```powershell
# White Lizard
python run_pet.py --creature lizard
# Bell
python run_pet.py --creature oracle
```

Mouse clicks pass through the pet by default. Right-click the system tray icon to enable mouse input, allowing you to drag the pet similarly to the MouseDrag mod.

A local installation of the Rain World base game is required. Set its directory in Settings or config.toml to load the original textures. Neither Downpour nor The Watcher is required to start the pet. Bell's voice requires the corresponding Watcher audio or local voice clips; missing optional resources only mark the related settings as unavailable. Use "Recheck resources" in Settings after restoring the files.

### Assets and Copyright

- This is an unofficial Rain World fan project. Commercial use of this project and any derivative versions is prohibited.
- The original game's names, characters, and assets belong to their respective rights holders. Third-party code and components retain their original licenses.
- This repository does not distribute game assets. Required resources are read or extracted from the user's legally obtained local copy of the game for local use only. Do not redistribute them without permission. This project grants no rights to the original game's assets.

### References

The following projects were used as references while developing this desktop pet. Many thanks to their authors!

- Mouse dragging mod: [woutkolkman / MouseDrag](https://github.com/woutkolkman/mousedrag)
- Slugcat desktop pet: [lingxiaojun / SlugcatPet](https://github.com/lingxiaojun/slugcatpet)
