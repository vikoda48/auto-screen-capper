# -*- mode: python ; coding: utf-8 -*-
"""
字幕自动截屏工具 —— PyInstaller 打包配置

打包命令：
    pyinstaller subtitle_capper.spec

产物位于 dist/ 目录下：
- 单文件模式（onefile=True）：dist/字幕自动截屏工具.exe
- 目录模式（onefile=False）：dist/字幕自动截屏工具/字幕自动截屏工具.exe

切换模式只需修改下方 EXE() 里的 console 与 onefile 参数。
"""

import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Pillow 在不同版本下子模块的加载是动态的，显式收集避免运行时 ImportError
hiddenimports = []
hiddenimports += collect_submodules('PIL')
hiddenimports += [
    'tkinter',
    'tkinter.ttk',
    'tkinter.filedialog',
    'tkinter.messagebox',
    'PIL.ImageGrab',
    'PIL.ImageTk',
    'PIL.ImageChops',
]

a = Analysis(
    ['run_subtitle_capper.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除项目里无关的模块，减小体积
        'requests', 'dotenv', 'telegram', 'database', 'analysis',
        'api', 'bot', 'services', 'polymarket', 'numpy', 'pandas',
        'matplotlib', 'PyQt5', 'PySide2', 'PySide6',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='字幕自动截屏工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # 启用 UPX 压缩可显著减小体积；如未安装 UPX 会自动跳过
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,    # GUI 程序：不弹出黑色控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='subtitle_capper.ico',  # 如有图标可取消注释
)
