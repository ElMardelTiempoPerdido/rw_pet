# rainworld desktop pet

开发中：白蜥蜴 / 手势之铃，**未完成，可能存在各种bug和性能问题**

如果您希望以调试方式启动：

```powershell
# 白坨
python run_pet.py --creature lizard
# 手势之铃
python run_pet.py --creature oracle
```


默认鼠标穿透，从系统托盘右键菜单可以启用接收鼠标输入，此时可使用类似mousedrag mod的效果拖动桌宠

需要本机已安装雨世界及观望者DLC，该目录用于从原工程中获取部分贴图与音频以初始化桌宠


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

A local installation of Rain World and The Watcher DLC is required. The project uses your game installation directory to load or extract the textures and audio needed to initialize the pet.

### Assets and Copyright

- This is an unofficial Rain World fan project. Commercial use of this project and any derivative versions is prohibited.
- The original game's names, characters, and assets belong to their respective rights holders. Third-party code and components retain their original licenses.
- This repository does not distribute game assets. Required resources are read or extracted from the user's legally obtained local copy of the game for local use only. Do not redistribute them without permission. This project grants no rights to the original game's assets.

### References

The following projects were used as references while developing this desktop pet. Many thanks to their authors!

- Mouse dragging mod: [woutkolkman / MouseDrag](https://github.com/woutkolkman/mousedrag)
- Slugcat desktop pet: [lingxiaojun / SlugcatPet](https://github.com/lingxiaojun/slugcatpet)
