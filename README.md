# rainworld desktop pet

开发中：白蜥蜴 / 手势之铃，**未完成**


```powershell
python run_pet.py --creature lizard
python run_pet.py --creature oracle
```

加 `--desktop` 启动桌面模式

默认鼠标穿透，菜单栏右键可以启用接收鼠标输入，此时可以类似mousedrag mod的效果拖动桌宠

需要本机已安装雨世界及观望者DLC。请配置安装目录至 `config.toml` > `game_dir` ，用于从原工程中获取部分贴图与音频以初始化桌宠


## 文档
- [WhiteLizard 使用说明](docs/lizard/README.md)
- [Bell of Gesture 使用说明](docs/oracle/README.md)
- [目录结构 / 依赖 / 测试](docs/development.md)


## 资源与版权说明

- 本项目为RainWorld非官方粉丝作品，项目及其衍生版本均禁止用于任何商业活动
- 原作名称、角色与素材归各自权利人所有；第三方代码及组件保留原有许可
- 本仓库不分发游戏素材。所需资源从使用者本机的正版游戏中读取或提取，仅供本地运行，未经许可勿再次分发；本项目不授予任何原作素材相关权利

## 参考

此桌宠实现参考了以下工程，非常感谢！

- [woutkolkman / MouseDrag](https://github.com/woutkolkman/mousedrag)

- [lingxiaojun / SlugcatPet](https://github.com/lingxiaojun/slugcatpet)
