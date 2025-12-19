🚀 OrionTax Sync
OrionTax Sync é uma ferramenta de integração robusta desenvolvida para automatizar a sincronização de dados entre clientes locais e a plataforma OneTax. O sistema realiza a ponte entre bancos de dados Oracle e PostgreSQL (OrionTax), garantindo integridade e segurança através de criptografia.

🛠️ Funcionalidades principais
Sincronização Multi-Banco: Conexão com Oracle (Origem) e PostgreSQL (Destino).

Agendamento: Tarefas automatizadas via scheduler.py.

Segurança: Criptografia de senhas e credenciais sensíveis.

Interface Gráfica (GUI): Telas intuitivas para login, monitoramento e configurações.

Logs Detalhados: Rastreamento de operações e erros para fácil manutenção.

📂 Estrutura do Projeto
Plaintext
OrionTaxSync/
├── main.py                 # Ponto de entrada da aplicação
├── config/                 # Configurações de DB e Criptografia
├── gui/                    # Interface gráfica (PyQt/Tkinter)
├── core/                   # Motores de conexão e agendamento
├── utils/                  # Utilitários e Logging
├── data/                   # Armazenamento local (SQLite)
├── requirements.txt        # Dependências do projeto
└── build.spec              # Configuração de compilação
🔧 Instalação e Configuração
1. Requisitos

Python 3.8+

Cliente Oracle (Instant Client) configurado no sistema.

2. Configurando o ambiente

Bash
# Clone o repositório
git clone https://github.com/seu-usuario/oriontax-sync.git

# Entre na pasta
cd oriontax-sync

# Instale as dependências
pip install -r requirements.txt
📦 Como gerar o Executável (.exe)
O projeto utiliza o PyInstaller para gerar um binário independente. Para criar o executável utilizando as configurações pré-definidas no arquivo spec:

Bash
pyinstaller build.spec
O executável será gerado na pasta dist/.

📝 Notas de Implementação
Banco de Dados Local: O arquivo oriontax.db (SQLite) é criado automaticamente na primeira execução para armazenar configurações locais e estados da aplicação.

Criptografia: Certifique-se de não compartilhar as chaves geradas em config/encryption.py em repositórios públicos.