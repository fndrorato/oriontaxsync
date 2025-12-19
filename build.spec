# -*- mode: python ; coding: utf-8 -*-

import os
from PyQt5 import QtCore

block_cipher = None

project_root = os.path.abspath(SPECPATH)

# Recursos adicionais
datas = [
    ('resources/icone.ico', 'resources'),
]

hiddenimports = [
    # 🔥 FIX DEFINITIVO pkg_resources / platformdirs
    'platformdirs',
    'pkg_resources',
    'pkg_resources.extern',
    'pkg_resources._vendor',
    'setuptools',

    # GUI
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',

    # Scheduler
    'apscheduler.schedulers.background',
    'apscheduler.triggers.cron',

    # Banco / dados
    'psycopg2',
    'psycopg2.extensions',
    'sqlalchemy',
    'pandas',
    'numpy',

    # Segurança
    'bcrypt',
]


a = Analysis(
    ['main.py'],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'scipy',
        'PIL',
        'tkinter',
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
    [],
    exclude_binaries=True,
    name='OrionTaxSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 🚫 sem console
    icon='resources/icone.ico',  # ✅ ÍCONE
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='OrionTaxSync',
)
