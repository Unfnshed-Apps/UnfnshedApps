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
        'src.config',
        'bridge.settings_controller',
        'src.api_client',
        'src.dxf_loader',
        'src.gcode_generator',
        'src.part_matcher',
        'bridge',
        'bridge.app_controller',
        'bridge.cutting_controller',
        'bridge.damage_controller',
        'bridge.sheet_preview_item',
        'bridge.clickable_preview_item',
        'bridge.models',
        'bridge.models.parts_model',
        'bridge.models.damage_summary_model',
        'shared',
        'shared.config_base',
        'shared.api_client_base',
        'shared.app_controller_base',
        'shared.connection_worker',
        'shared.build_common',
        'ezdxf',
        'shapely',
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
    name='UnfnCNC',
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
    name='UnfnCNC',
)
import sys
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='UnfnCNC.app',
        icon='App Icon/UnfnCNC.icns',
        bundle_identifier='com.unfnshed.unfncnc',
    )
