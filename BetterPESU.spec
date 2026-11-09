# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from pathlib import Path

block_cipher = None

here = Path('.').resolve()
datas = [
    (str(here / 'templates'), 'templates'),
    (str(here / 'static'), 'static'),
]

# Include legacy data/courses.json as template seed if present
if (here / 'pesu-notes' / 'data' / 'courses.json').is_file():
    datas.append((str(here / 'pesu-notes' / 'data' / 'courses.json'), 'data'))
elif (here / 'data' / 'courses.json').is_file():
    datas.append((str(here / 'data' / 'courses.json'), 'data'))

hiddenimports = [
    'jinja2',
    'werkzeug',
    'werkzeug.serving',
    'requests',
    'bs4',
    'sqlite3',
    'webview',
    'backend',
    'backend.app',
    'backend.config',
    'backend.db',
    'backend.auth.manager',
    'backend.academic.attendance',
    'backend.academic.grades',
    'backend.academic.planner',
    'backend.academic.provider',
    'backend.jobs.sync_manager',
    'backend.jobs.downloader_engine',
    'backend.jobs.converter_engine',
    'backend.jobs.pdf_merger',
    'pypdf',
    'desktop.launcher',
]

if sys.platform == 'darwin':
    hiddenimports += [
        'objc',
        'WebKit',
        'AppKit',
        'Foundation',
        'Quartz',
    ]

a = Analysis(
    ['app.py'],
    pathex=[str(here)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'IPython'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BetterPESU',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BetterPESU',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Better PESU Acad.app',
        icon=None,
        bundle_identifier='com.betterpesu.desktop',
        info_plist={
            'CFBundleShortVersionString': '2.0.0',
            'CFBundleVersion': '2.0.0',
            'NSHighResolutionCapable': 'True',
            'NSRequiresAquaSystemAppearance': 'False',
        },
    )
