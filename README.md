OrionTaxSync/
├── main.py                 # Executável principal
├── config/
│   ├── __init__.py
│   ├── database.py        # SQLite manager
│   └── encryption.py      # Criptografia de senhas
├── gui/
│   ├── __init__.py
│   ├── login.py           # Tela de login
│   ├── main_window.py     # Janela principal
│   └── settings.py        # Configurações
├── core/
│   ├── __init__.py
│   ├── oracle_client.py   # Cliente Oracle
│   ├── oriontax_client.py # Cliente OrionTax (PostgreSQL)
│   └── scheduler.py       # Agendador de tarefas
├── utils/
│   ├── __init__.py
│   └── logger.py          # Sistema de logs
├── data/
│   └── oriontax.db        # SQLite (criado automaticamente)
├── requirements.txt
└── build.spec             # PyInstaller config