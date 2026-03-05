# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    collect_dynamic_libs,
)

block_cipher = None
project_root = os.path.abspath(SPECPATH)

# ============================================================
# ÍCONE
# ============================================================
icon_path = os.path.join(project_root, 'resources', 'icone.ico')
if not os.path.exists(icon_path):
    print(f"AVISO: Ícone não encontrado em: {icon_path}")
    icon_path = None
else:
    print(f"✓ Ícone encontrado: {icon_path}")

# ============================================================
# DATAS
# ============================================================
datas = []

if icon_path:
    datas.append((icon_path, 'resources'))

datas += collect_data_files('pandas')
datas += collect_data_files('numpy')

# PyQt5: inclui os plugins Qt (platforms/qwindows.dll, styles, etc.)
# Sem isso ocorre "DLL load failed while importing QtWidgets"
datas += collect_data_files('PyQt5')

# ============================================================
# BINÁRIOS
# ============================================================
# Coleta os DLLs do Qt5 (Qt5Core.dll, Qt5Widgets.dll, etc.)
binaries = collect_dynamic_libs('PyQt5')

# ============================================================
# HIDDEN IMPORTS
# ============================================================
hiddenimports = [
    # Platform
    'platformdirs',
    'pkg_resources',
    'pkg_resources.extern',
    'pkg_resources._vendor',
    'setuptools',

    # GUI — submódulos PyQt5
    'PyQt5',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.QtNetwork',
    'PyQt5.sip',

    # Scheduler
    'apscheduler',
    'apscheduler.schedulers',
    'apscheduler.schedulers.background',
    'apscheduler.triggers',
    'apscheduler.triggers.cron',
    'apscheduler.executors',
    'apscheduler.executors.pool',
    'apscheduler.jobstores',
    'apscheduler.jobstores.memory',

    # Database
    'oracledb',
    'psycopg2',
    'psycopg2.extensions',
    'psycopg2._psycopg',
    'sqlite3',

    # Firebird
    'firebirdsql',
    'firebirdsql.fbcore',
    'firebirdsql.wire',
    'firebirdsql.utils',

    # Data processing
    'pandas',
    'pandas._libs',
    'pandas._libs.tslibs',
    'pandas._libs.tslibs.base',
    'pandas.core',
    'pandas.core.arrays',
    'pandas.core.arrays.string_',
    'numpy',
    'numpy.core',
    'numpy.core._multiarray_umath',
    'numpy.random',
    'numpy.random._common',
    'numpy.random._generator',

    # Security
    'bcrypt',
    '_cffi_backend',
    'cryptography',
    'cryptography.hazmat.primitives',
    'cryptography.hazmat.backends',
    'cryptography.hazmat.backends.openssl',
]

hiddenimports += collect_submodules('PyQt5')
hiddenimports += collect_submodules('pandas')
hiddenimports += collect_submodules('numpy')
hiddenimports += collect_submodules('firebirdsql')

# ============================================================
# ANÁLISE
# ============================================================
a = Analysis(
    ['main.py'],
    pathex=[project_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['.'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'scipy',
        'PIL',
        'tkinter',
        'IPython',
        'jupyter',
        'notebook',
        'sphinx',
        'test',
        'tests',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Remover duplicatas
a.datas = list({tuple(map(str, t)) for t in a.datas})

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
    console=False,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OrionTaxSync',
)
