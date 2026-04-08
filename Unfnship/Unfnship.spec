# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('qml', 'qml'),
        ('../shared', 'shared'),
    ],
    hiddenimports=[
        'shared',
        'shared.config_base',
        'shared.api_client_base',
        'shared.connection_worker',
        'shared.app_controller_base',
        'requests',
        'PySide6.QtQuick',
        'PySide6.QtGui',
        'PySide6.QtQml',
        'src.config',
        'src.api_client',
        'bridge',
        'bridge.app_controller',
        'bridge.shipping_controller',
        'bridge.models',
        'bridge.models.orders_model',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Unfnship',
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
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Unfnship',
)
import sys
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Unfnship.app',
        bundle_identifier='com.unfnshed.unfnship',
    )
