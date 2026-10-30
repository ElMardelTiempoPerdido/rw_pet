# rainworld desktop pet

开发中：白蜥蜴 / 手势之铃，**未完成，可能存在各种bug和性能问题**

**如果您希望直接获取桌宠游玩，请下载 Release 中的发行 ZIP，将 EXE 与 presets 一起解压，而非下载 source code.zip**

已有用户的覆盖升级、角色分享和备份方法见 [角色升级与分享](docs/profile-upgrade-sharing.md)

---

默认鼠标穿透，从系统托盘右键菜单可以启用接收鼠标输入，此时可使用类似mousedrag mod的效果拖动桌宠

需要本机已安装雨世界本体，并在设置或 config.toml 中配置游戏目录，用于读取原版贴图。Downpour 和 Watcher 均非启动必需；Bell 语音需要对应的 Watcher 音频或本地语音片段，资源缺失时只将相关设置标为“不可用”，不阻止桌宠运行。补齐素材后可在设置中点击“重新检查资源”

---

以调试方式启动：

```powershell
# 白坨
python run_pet.py --creature lizard
# 手势之铃
python run_pet.py --creature oracle
```

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
