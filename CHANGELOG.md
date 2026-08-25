# Changelog — OrionTax Sync

---

## [1.0.5] — 2026-08-24

### Corrigido

#### ORA-01722 (invalid number) ao gravar EAN não numérico nas tabelas temporárias
- A coluna `EAN` é `NUMBER(14)` nas tabelas `MXF_TMP_ICMS_SAIDA`, `MXF_TMP_ICMS_ENTRADA`, `MXF_TMP_PIS_COFINS` e `MXF_TMP_CBS_IBS`. Quando o OrionTax retorna o placeholder textual `'SEM GTIN'` (produto sem código de barras cadastrado), o `INSERT` no BD Intersolid (Oracle/Firebird) quebrava com `ORA-01722: invalid number`, interrompendo a operação **BUSCAR** para o cliente inteiro.
- `EAN` foi adicionado a `TABLE_NUMBER_COLUMNS` em `core/oracle_client.py` (reaproveitado por `core/firebird_client.py`), passando a tratar valores não numéricos nessa coluna como `NULL` em vez de propagar o erro.

---

## [1.0.4.1] — 2026-08-03

### Adicionado

#### Botões de limpeza manual das tabelas temporárias
- Novo `QGroupBox` "Tabelas Temporárias (BD Intersolid)" na aba Operações (`gui/main_window.py`), com 3 botões:
  - "Limpar Tabela Temporária de ICMS" → `DELETE FROM MXF_TMP_ICMS_ENTRADA` e `MXF_TMP_ICMS_SAIDA`
  - "Limpar Tabela Temporária do PIS/COFINS" → `DELETE FROM MXF_TMP_PIS_COFINS`
  - "Limpar Tabela Temporária do IBS/CBS" → `DELETE FROM MXF_TMP_CBS_IBS`
- Cada botão pede confirmação antes de executar e usa a conexão BD Intersolid configurada (Oracle ou Firebird, via `create_db_client`).
- Novo método `clear_tmp_tables()` adicionado a `OracleClient` e `FirebirdClient`.

---

## [1.0.4] — 2026-07-03

### Adicionado

#### Log de progresso durante inserções travadas no banco de destino
- Novo helper `_executemany_with_heartbeat()` em `core/oracle_client.py` (reaproveitado em `core/firebird_client.py`): durante um `INSERT` em lote, se a chamada ficar mais de 15s sem retornar (ex.: trigger lento ou lock no banco), é emitida periodicamente uma mensagem informando a tabela e o tempo decorrido.
- Nas operações manuais (botão da tela principal), essas mensagens aparecem no console da interface. Nas execuções agendadas, são gravadas no log de arquivo com o nome do cliente.
- Objetivo: eliminar o cenário de operação travada silenciosamente, sem qualquer indicação do que está acontecendo — motivado por um caso real em que o `INSERT` em `MXF_TMP_ICMS_SAIDA` ficava preso por um trigger lento no Oracle sem nenhuma mensagem de erro.

#### Botão "Cancelar Execução"
- Novo botão na tela principal (`gui/main_window.py`), habilitado apenas durante uma operação manual em andamento.
- Ao acionar (com confirmação), interrompe a conexão ativa no momento: `connection.cancel()` no Oracle e no OrionTax (PostgreSQL), ou fechamento forçado da conexão no Firebird (driver sem suporte nativo a cancelamento de statement).
- Novo método `cancel()` adicionado a `OracleClient`, `FirebirdClient` e `OrionTaxClient`.

### Corrigido

#### Log das últimas 12h ausente no Heartbeat
- `HeartbeatService._read_log_file()` (`core/heartbeat.py`) localizava a pasta `logs/` usando `Path(__file__).parent.parent`, caminho não confiável dentro do executável PyInstaller (onedir) — resultando em `logs_ultimas_24h` sempre vazio em produção, mesmo com o heartbeat rodando normalmente.
- Corrigido para usar o mesmo padrão já adotado em `main.py`/`gui/main_window.py`: `sys.executable` quando `sys.frozen` é `True`, em vez de depender de `__file__`.

---

## [1.0.3] — 2026-06-24

### Adicionado

#### Sincronização da tabela TAB_CODIGO_BARRA na operação ENVIAR
- A operação **ENVIAR** (Oracle/Firebird → PostgreSQL) passou a incluir a tabela `TAB_CODIGO_BARRA`.
- Os dados são lidos do banco de origem (`TAB_CODIGO_BARRA`) e gravados na tabela `mxf_tab_codigo_barra` do PostgreSQL, com o CNPJ do cliente injetado automaticamente.
- A chave de deduplicação e de DELETE é composta por `cnpj + cod_produto + cod_ean`, refletindo a PK original da tabela no Oracle/Firebird.
- A operação **BUSCAR** não foi alterada — `mxf_tab_codigo_barra` é somente gravação.
- Internamente, `table_pairs` em `oriontax_client.py` passou de 2-tupla para 3-tupla `(key, table_name, dedup_cols)`, permitindo que cada tabela defina sua própria chave de dedup sem impactar as demais.

---

## [1.0.2.5] — 2026-05-11

### Alterado

#### Substituição de UPSERT por DELETE + INSERT no envio para OrionTax
- Na operação **ENVIAR** (Oracle/Firebird → PostgreSQL), o mecanismo de `INSERT ON CONFLICT DO UPDATE` foi substituído por `DELETE WHERE cnpj = X` seguido de `INSERT` simples.
- Novo método `delete_and_insert_dataframe` em `oriontax_client.py` responsável pela operação.
- DELETE e INSERTs ocorrem na mesma transação: em caso de falha, o rollback desfaz tudo.
- A operação **BUSCAR** (PostgreSQL → Oracle/Firebird) não foi alterada.

---

## [1.0.2.4] — 2026-05-06

### Corrigido

#### Filtro de produtos ativos em PIS/COFINS
- A leitura da view `MXF_VW_PIS_COFINS` passou a aplicar o filtro `STATUS = 'ATIVO'`, tanto no cliente Firebird (`firebird_client.py`) quanto no Oracle (`oracle_client.py`).
- Antes, todos os produtos eram retornados independentemente do status, podendo incluir itens inativos no envio à OrionTax.
- No Firebird, o método `_read_view` ganhou o parâmetro opcional `where_clause` para suportar filtros sem duplicar código.

---

## [1.0.2.3] — 2026-04-30

### Corrigido

#### Gravação dos dados de ICMS Entrada na operação ENVIAR
- Na operação **ENVIAR** (Intersolid → OrionTax), os dados lidos da view `MXF_VW_ICMS_ENTRADA` passaram a ser gravados também na tabela `mxf_tmp_icms_entrada` do PostgreSQL, além da `mxf_vw_icms_entrada`.
- Isso garante que a operação **BUSCAR** subsequente encontre os dados corretamente em `mxf_tmp_icms_entrada` e os devolva para a tabela `MXF_TMP_ICMS_ENTRADA` do Oracle/Firebird.

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
