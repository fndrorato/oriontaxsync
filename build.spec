# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
project_root = os.path.abspath(SPECPATH)

# ✅ Coletar dados do pandas/numpy
datas = [
    ('resources/icone.ico', 'resources'),
]

# ✅ Adicionar dados de pacotes específicos
datas += collect_data_files('pandas')
datas += collect_data_files('numpy')

# ✅ Hidden imports completos
hiddenimports = [
    # Platform
    'platformdirs',
    'pkg_resources',
    'pkg_resources.extern',
    'pkg_resources._vendor',
    'setuptools',
    
    # GUI
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
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
    'psycopg2',
    'psycopg2.extensions',
    'psycopg2._psycopg',
    'sqlite3',
    
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
    
    # Oracle (se necessário)
    # 'oracledb',
    # 'cx_Oracle',
]

# ✅ Coletar todos os submódulos do pandas e numpy
hiddenimports += collect_submodules('pandas')
hiddenimports += collect_submodules('numpy')

a = Analysis(
    ['main.py'],
    pathex=[project_root],
    binaries=[],
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

# ✅ Remover duplicatas
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
    icon='resources/icone.ico' if os.path.exists('resources/icone.ico') else None,
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