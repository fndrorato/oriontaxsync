"""
Hook personalizado para pandas
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Coletar dados
datas = collect_data_files('pandas')

# Coletar submódulos
hiddenimports = collect_submodules('pandas')