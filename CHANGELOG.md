# Changelog — OrionTax Sync

---

## [1.0.2] — 2026-04-09

### Adicionado

#### Heartbeat — Monitoramento Remoto de Saúde
- Novo serviço `core/heartbeat.py` (`HeartbeatService`) que envia métricas do sistema periodicamente ao servidor OrionTax (PostgreSQL).
- Métricas coletadas a cada ciclo: CPU, memória RAM, disco, memória do processo, hostname, usuário do SO, IP local, versão do SO, uptime da aplicação, registros processados no dia, erros nas últimas 24h, último erro registrado e conteúdo do log das últimas 12h.
- Dados gravados em duas tabelas no PostgreSQL:
  - `cliente_monitor` — UPSERT com o estado atual do cliente (preserva `primeiro_heartbeat`).
  - `cliente_monitor_historico` — INSERT a cada ciclo para histórico e geração de gráficos.
- O campo `cliente_id` utiliza o CNPJ do cliente cadastrado no sistema.
- O campo `logs_ultimas_12h` envia o conteúdo do arquivo de log das últimas 12 horas, filtrando linha a linha pelo timestamp. Linhas de continuação (tracebacks) são incluídas automaticamente.
- Status calculado dinamicamente: `error` se houve falha na última 1 hora, `running` caso contrário.
- Intervalo de envio configurável pela interface (mínimo: 1 minuto, máximo: 1440 minutos). Padrão: 5 minutos.
- Novo `QGroupBox` "Heartbeat" na aba Configurações com botão "⚙️ Configurar Heartbeat".
- Ao salvar o novo intervalo, o job é reiniciado imediatamente no APScheduler sem precisar reiniciar o app.
- Versão da aplicação centralizada em `version.py` (`APP_VERSION`) e enviada no campo `versao_app` a cada heartbeat.

#### Logging em arquivo
- Corrigido o `setup_logging()` em `main.py`: o `basicConfig` duplicado impedia o `FileHandler` de ser registrado, fazendo o arquivo `logs/oriontax_YYYYMMDD.log` ficar em branco. Agora os handlers são configurados diretamente no root logger, garantindo gravação em disco.

### Corrigido

#### Fuso horário na aba de Logs
- Os timestamps na tabela de logs eram exibidos em UTC, aparecendo 3 horas à frente do horário local (Brasil UTC-3). Corrigido em `main_window.py`: o valor lido do SQLite agora é convertido de UTC para o horário local da máquina antes de exibir.

#### Criptografia entre máquinas
- `config/encryption.py` — `decrypt()` agora captura `InvalidToken` e retorna `''` em vez de lançar exceção.
- `config/database.py` — `get_oracle_config()` e `get_oriontax_config()` retornam `None` quando a senha não pode ser descriptografada (ex: banco gerado em outra máquina ou hostname alterado), registrando um aviso claro no log em vez de quebrar silenciosamente.
- **Ação necessária após atualização:** Entre em Configurações → Oracle/Firebird e OrionTax e re-salve as credenciais para re-criptografá-las com a chave da máquina atual.

#### Status do heartbeat
- O campo `status` ficava como `error` o dia inteiro após qualquer falha pontual (ex: Oracle indisponível no agendamento). Ajustado para considerar apenas erros da **última 1 hora**, refletindo com mais precisão o estado atual do sistema.

#### Tamanho de campos no PostgreSQL
- `so_versao` truncado a 50 caracteres para respeitar o `VARCHAR(50)` da tabela (o valor completo no macOS/Linux pode ultrapassar esse limite).
- `hostname` limitado a 255 e `usuario_so` a 100 caracteres.

---

## [1.0.1] — anterior

- Suporte a Firebird 2.5 além de Oracle.
- Zero-padding para campos `CST_CBS_IBS` e `CCLASSTRIB` ao inserir no Oracle/Firebird.
- Correções no build (PyInstaller / jaraco.text).

---

## [1.0.0] — lançamento inicial

- Sincronização bidirecional Oracle ↔ OrionTax (PostgreSQL).
- Interface gráfica PyQt5 com system tray.
- Agendamento automático via APScheduler.
- Gerenciamento de múltiplos clientes por CNPJ.
- Criptografia de senhas com Fernet.
- Logs de execução com histórico.
