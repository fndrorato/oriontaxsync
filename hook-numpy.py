"""
Hook personalizado para numpy
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Coletar dados
datas = collect_data_files('numpy')

# Coletar submódulos
hiddenimports = collect_submodules('numpy')

# Adicionar imports críticos
hiddenimports += [
    'numpy.core._multiarray_umath',
    'numpy.core._multiarray_tests',
    'numpy.random._common',
    'numpy.random._generator',
    'numpy.random._mt19937',
    'numpy.random._philox',
    'numpy.random._pcg64',
    'numpy.random._sfc64',
    'numpy.random.bit_generator',
]