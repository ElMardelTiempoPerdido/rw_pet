# 发行打包与覆盖更新

使用 `rw_pet` 环境，在工程根目录执行：

```powershell
python tools/packaging/build_bell.py
```

构建会检查并编译译文、生成 EXE，然后整理发行目录和 ZIP：

```text
dist/
  BellPet.exe
  release.zip
  release/
    BellPet.exe
    release.json
    presets/profiles/
      固定角色目录/
        original/
          profile.json
          appearance/
```

发布 `release.zip`。首次使用解压整个发行包，EXE 与 presets 保持相邻。后续更新将包内文件合并复制到原安装目录并覆盖同名文件，保留已有角色目录；不要先删除整个 presets 目录

发行角色的根 `profile.json`、当前 `appearance`、`character.json` 和历史不进入更新包。新用户首次启动时从 `original` 创建当前副本；旧用户保留当前设置，新的 `original` 成为恢复默认值的来源。旧 settings 中的角色记录由启动迁移处理

## 固定发行清单

`presets/release.json` 记录发行角色的 ID 和固定目录名，当前包含九个角色。日常使用生成的恢复角色、自建角色和重复副本不自动加入发布包

同一角色后续发布保持 ID 与清单中的目录名不变。新增独立角色时，为它登记新的 ID 和目录名

旧源预设没有 `original` 时，将其完整快照转换为发行默认；已有工作目录时只采用其 `original`，避免将开发者日常个人调整顺带发布。此过程只写入发行暂存目录，不改写源预设

## 发布本次调整后的角色

先在设置中使用“导出分享此角色”生成 ZIP，再把它作为明确的发行替换源：

```powershell
python tools/packaging/build_bell.py --overrides exports/Bell.zip
# 也可指定包含多个角色 ZIP 的目录
python tools/packaging/build_bell.py --overrides exports
```

替换包通过角色 ID 匹配清单，仍写入原来的固定目录名。未登记的角色或同一 ID 的多个替换包会报错，避免按日期猜测应发布哪一版

已有当前版本 EXE 时，可单独重新整理预设发行包：

```powershell
python tools/packaging/release.py --exe dist/BellPet.exe --overrides exports --output dist/release
```

重复生成时只替换通过校验的发行目录，上一份保存在同级 `release.previous-*`；普通已有目录会被拒绝。默认 ZIP 为输出目录名加 `.zip`

## 验证

整理流程会重读所有角色及引用图片，并检查发行目录只包含 EXE、发行清单和明确引用的 `original` 文件；临时文件、用户当前设置及额外缓存均不能通过检查

```powershell
python -m unittest tests.test_profile_lifecycle tests.test_profile_sharing tests.test_release_package
python tools/packaging/verify_bell.py --exe dist/release/BellPet.exe --release dist/release.zip
```

指定 `--release` 时，先验证实际 ZIP 的文件范围、角色资源及 EXE 一致性，再从解压后的发行包启动；不指定时只验证独立 EXE

包内自检使用独立目录与用户配置，覆盖界面、资源准备、角色 ZIP 导入导出、模拟和语言切换；不会写入正在使用的真实 settings。完整升级、分享与备份操作及验证范围见 [角色升级与分享](profile-upgrade-sharing.md)
