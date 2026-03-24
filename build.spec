# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
project_root = os.path.abspath(SPECPATH)

# ============================================================
# SITE-PACKAGES
# Usa sysconfig para localizar o site-packages correto,
# funcionando tanto com venv local quanto com Python de sistema
# (ex: GitHub Actions onde não há venv).
# ============================================================
import sysconfig

venv_site_packages = sysconfig.get_paths()['purelib']
if venv_site_packages not in sys.path:
    sys.path.insert(0, venv_site_packages)
print(f"✓ site-packages: {venv_site_packages}")

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

try:
    datas += collect_data_files('pandas')
except Exception as e:
    print(f"AVISO: collect_data_files('pandas') falhou: {e}")

try:
    datas += collect_data_files('numpy')
except Exception as e:
    print(f"AVISO: collect_data_files('numpy') falhou: {e}")

# PyQt5: inclui os plugins Qt necessários (platforms/qwindows.dll, styles, etc.)
# IMPORTANTE: sem isso o Qt não consegue criar janelas no Windows
try:
    datas += collect_data_files('PyQt5')
except Exception as e:
    print(f"AVISO: collect_data_files('PyQt5') falhou: {e}")

# ============================================================
# BINÁRIOS
# Não usamos collect_dynamic_libs(PyQt5) porque os hooks embutidos
# do pyinstaller-hooks-contrib já coletam os DLLs do Qt5 automaticamente.
# Misturar os dois métodos pode causar conflitos e corrupção.
# ============================================================
binaries = []

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

    # GUI
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
    'passlib',
    'passlib.handlers',
    'passlib.handlers.des_crypt',
    'passlib.utils',
    'passlib.utils.binary',
    'passlib.utils.decor',

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
    'cryptography.x509',
    'cryptography.x509.base',
    'cryptography.x509.extensions',
    'cryptography.x509.general_name',
    'cryptography.x509.name',
    'cryptography.x509.oid',
    'cryptography.hazmat',
    'cryptography.hazmat.primitives',
    'cryptography.hazmat.primitives.asymmetric',
    'cryptography.hazmat.primitives.ciphers',
    'cryptography.hazmat.primitives.hashes',
    'cryptography.hazmat.primitives.serialization',
    'cryptography.hazmat.backends',
    'cryptography.hazmat.backends.openssl',
    'cryptography.hazmat.backends.openssl.backend',
    'cryptography.hazmat.bindings',
    'cryptography.hazmat.bindings.openssl',
]

hiddenimports += collect_submodules('cryptography')
hiddenimports += collect_submodules('PyQt5')
hiddenimports += collect_submodules('pandas')
hiddenimports += collect_submodules('numpy')
hiddenimports += collect_submodules('firebirdsql')
hiddenimports += collect_submodules('passlib')

# ============================================================
# ANÁLISE
# ============================================================
_pathex = [project_root]
if venv_site_packages:
    _pathex.append(venv_site_packages)

a = Analysis(
    ['main.py'],
    pathex=_pathex,
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
    # UPX DESATIVADO — comprime DLLs do Qt e pode corrompê-las,
    # causando "DLL load failed" e "No module named PyQt5"
    upx=False,
    console=False,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='OrionTaxSync',
)
