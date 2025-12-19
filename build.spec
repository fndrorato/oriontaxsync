# -*- mode: python ; coding: utf-8 -*-

import os
import sys

block_cipher = None

# Raiz do projeto (onde está o main.py)
project_root = os.path.abspath(SPECPATH)

# ======================================================
# DADOS ADICIONAIS (copiados para dentro do executável)
# ======================================================
datas = [
    # Banco SQLite (vai junto no build)
    ('data/oriontax.db', 'data'),

    # Se futuramente tiver arquivos fixos:
    # ('config', 'config'),
    ('resources', 'resources'),
]

# ======================================================
# BINÁRIOS EXTERNOS (DLLs, Oracle Client, etc)
# ======================================================
binaries = [
    # Exemplo se empacotar Oracle Instant Client:
    # ('instantclient_23_3/*', 'instantclient_23_3'),
]

# ======================================================
# IMPORTS OCULTOS (CRÍTICO)
# ======================================================
hiddenimports = [
    # ===== PyQt =====
    'PyQt5',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',

    # ===== Scheduler =====
    'apscheduler',
    'apscheduler.schedulers.background',
    'apscheduler.triggers.cron',

    # ===== Banco =====
    'sqlite3',
    'psycopg2',
    'psycopg2.extensions',
    'psycopg2.extras',
    'sqlalchemy',

    # ===== Oracle =====
    'oracledb',

    # ===== Data =====
    'pandas',
    'numpy',

    # ===== Segurança =====
    'bcrypt',
    'cryptography',
]

# ======================================================
# ANALYSIS
# ======================================================
a = Analysis(
    ['main.py'],
    pathex=[project_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'PIL',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ======================================================
# PYZ
# ======================================================
pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

# ======================================================
# EXECUTÁVEL (GUI – SEM CONSOLE)
# ======================================================
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

    # 🔴 ESSENCIAL: não mostrar console
    console=False,

    # icon='resources/oriontax.ico',  # se quiser ícone
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ======================================================
# COLETA FINAL
# ======================================================
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
