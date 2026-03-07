# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for File Revitalizer Local Agent.

Build with:
    cd <repo-root>
    pyinstaller agent/file-revitalizer-agent.spec

Or let the GitHub Actions workflow handle it automatically.
"""

import os

block_cipher = None
agent_dir = os.path.abspath('agent')

a = Analysis(
    [os.path.join(agent_dir, 'cli.py')],
    pathex=[agent_dir],
    binaries=[],
    datas=[],
    hiddenimports=[
        'commands',
        'commands.health',
        'commands.list_devices',
        'commands.scan',
        'commands.upload',
        'commands.execute',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Not needed at runtime — reduce binary size
        'tkinter', '_tkinter', 'unittest', 'pydoc',
        'doctest', 'xmlrpc', 'email', 'html',
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='file-revitalizer-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    console=True,
    icon=None,
)
