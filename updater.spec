# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

hiddenimports = []
datas = []
binaries = []
for package in ["requests"]:
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(['updater.py'], pathex=[], binaries=binaries, datas=datas, hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='DailyLogUpdater', debug=False, bootloader_ignore_signals=False, strip=False, upx=True, console=False)
