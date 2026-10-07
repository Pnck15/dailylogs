# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['dailylog_notify.py'],
    pathex=[],
    binaries=[],
    datas=[('notify.env', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='DailyLogNotify',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
