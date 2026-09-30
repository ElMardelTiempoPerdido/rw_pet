"""仅收集程序依赖、默认配置和自绘图标；不包含任何游戏素材或用户缓存。"""
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, get_package_paths
from PySide6.QtCore import QLibraryInfo

root = Path(SPECPATH).parents[1]
full = os.environ.get('RW_PET_BUNDLE_FULL') == '1'
use_upx = os.environ.get('RW_PET_BUNDLE_UPX') == '1'
name = os.environ.get('RW_PET_BUNDLE_NAME', 'BellPet')
_, fmod_root = get_package_paths('fmod_toolkit')
datas = [(str(root/'config.toml'), '.'),
         (str(root/'rw_creature_pet/ico'), 'rw_creature_pet/ico'),
         (str(root/'rw_creature_pet/translations/en.qm'), 'rw_creature_pet/translations'),
         (str(Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))/'qtbase_zh_CN.qm'),
          'rw_creature_pet/translations')]
datas += collect_data_files('UnityPy')
datas += collect_data_files('archspec', includes=['json/cpu/*.json'])
binaries = [(str(Path(fmod_root)/'libfmod/Windows/x64/fmod.dll'),
             'fmod_toolkit/libfmod/Windows/x64')]
# Conda 的 _ctypes 依赖位于 Library/bin，不保证能从打包进程 PATH 找到。
ffi = Path(sys.prefix)/'Library/bin/ffi.dll'
if ffi.is_file():
    binaries.append((str(ffi), '.'))

excludes = ['IPython', 'scipy', 'matplotlib', 'tkinter', 'pytest', 'numba.np.ufunc.tbbpool']
if not full:
    # 应用使用 QWidget + QPainter + WAV；未使用视频控件、QML 或 AVIF。
    excludes += ['PySide6.QtMultimediaWidgets', 'PySide6.QtQml', 'PySide6.QtQuick',
                 'PIL.AvifImagePlugin', 'PIL._avif']
a = Analysis(
    [str(root/'tools/packaging/bell_entry.py')],
    pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=['UnityPy.resources'],
    hookspath=[], runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
# PySide6 的 Qt6Core 使用 Windows 自带的无版本后缀 ICU 导出。
# 构建环境 PATH（例如 Conda / Poppler）的同名库可能只有带版本后缀的
# 导出。仅移除这类错误的 ICU 及其数据 DLL，让 Qt 使用系统库。
import pefile
incompatible_icu = set()
for target, source, _ in a.binaries:
    if target.lower() == 'icuuc.dll':
        with pefile.PE(source) as library:
            exports = {symbol.name for symbol in library.DIRECTORY_ENTRY_EXPORT.symbols}
            if b'ucnv_open' not in exports:
                incompatible_icu.add(target.lower())
                incompatible_icu.update(item.dll.decode().lower() for item in library.DIRECTORY_ENTRY_IMPORT
                                        if item.dll.lower().startswith(b'icudt'))
a.binaries = [entry for entry in a.binaries if entry[0].lower() not in incompatible_icu]
if not full:
    # 自动收集的 Qt 插件会拉入其可选依赖。仅裁掉当前产品不走的分支；
    # 保留原生 Windows 音频、系统输入法、qwindows / qoffscreen 和 QtSvg。
    unused_qt = {'opengl32sw.dll', 'qt6pdf.dll', 'qpdf.dll', 'qtvirtualkeyboardplugin.dll',
                 'qt6virtualkeyboard.dll', 'ffmpegmediaplugin.dll', 'qt6multimediawidgets.dll'}
    unused_prefixes = ('qt6qml', 'qt6quick', 'avcodec-', 'avformat-', 'avutil-', 'swscale-', 'swresample-')
    a.binaries = [entry for entry in a.binaries if not (
        entry[0].replace('\\', '/').startswith('PySide6/') and
        (Path(entry[0]).name.lower() in unused_qt or Path(entry[0]).name.lower().startswith(unused_prefixes)))]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name=name, debug=False, bootloader_ignore_signals=False,
    strip=False, upx=use_upx, console=False,
    upx_exclude=['python3.dll', '_uuid.pyd'],  # 太小、不可压缩；保留原文件。
    icon=str(root/'build/packaging/bell-dark.ico'),
)
