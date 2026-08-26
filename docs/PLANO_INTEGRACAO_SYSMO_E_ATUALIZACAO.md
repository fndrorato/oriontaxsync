# Plano de integração Sysmo e atualização automática

## 1. Objetivo

Evoluir o OrionTax Sync para uma aplicação única, capaz de operar com os ERPs
Intersolid e Sysmo, preservando integralmente a integração Intersolid existente.

Para a Sysmo, o aplicativo local será responsável por:

- ler os produtos no PostgreSQL da Sysmo;
- transformar os registros para o contrato V2 da API OrionTax;
- enviar os produtos para `POST /api/v2/enviar/`;
- obter os produtos tributados em `GET /api/v2/receber/`;
- transformar a resposta para o contrato da Sysmo;
- gravar os produtos em `tb_sysmointegradorrecebimento`;
- executar operações manuais ou agendadas;
- registrar logs e estado das sincronizações;
- verificar, baixar e instalar novas versões do aplicativo.

O build atual do GitHub Actions continuará existindo sem alterações funcionais.
Será criado um segundo workflow, isolado, para gerar o instalador com Inno Setup
e publicar releases aptas ao mecanismo de atualização automática.

---

## 2. Decisões arquiteturais

### 2.1 Uma aplicação e um executável

Haverá um único produto:

```text
OrionTax Sync
├── perfil Intersolid
└── perfil Sysmo
```

Não serão mantidos executáveis, branches ou cópias independentes por ERP. Isso
evita divergência de correções, telas, logs, scheduler e atualização automática.

### 2.2 O ERP será uma configuração explícita

O sistema não tentará deduzir o ERP pelo tipo de banco. O perfil da instalação
será persistido explicitamente:

```text
erp_type = intersolid | sysmo
```

Oracle, Firebird e PostgreSQL são tecnologias de banco. Intersolid e Sysmo são
contratos de integração e possuem tabelas, mapeamentos e regras diferentes.

### 2.3 Compatibilidade do fluxo atual

Na primeira fase, o fluxo Intersolid continuará usando os componentes atuais:

```text
Intersolid Oracle/Firebird ⇄ OrionTax PostgreSQL
```

O novo fluxo será:

```text
Sysmo PostgreSQL ⇄ OrionTax Sync ⇄ API OrionTax V2
```

A refatoração deve envolver o fluxo existente em um adaptador, sem reescrever
as consultas e inserções que já estão em produção.

### 2.4 Contrato comum de integração

A interface e o scheduler chamarão um contrato comum:

```python
class IntegrationAdapter:
    def validate_configuration(self): ...
    def test_erp_connection(self): ...
    def test_oriontax_connection(self): ...
    def send(self, client, progress_callback, cancel_token): ...
    def receive(self, client, progress_callback, cancel_token): ...
    def cancel(self): ...
```

Implementações previstas:

```text
IntersolidIntegration
SysmoIntegration
```

O objetivo é retirar da GUI e do scheduler o conhecimento sobre SQL, tabelas,
DataFrames, HTTP, Oracle, Firebird ou PostgreSQL.

---

## 3. Estrutura proposta

```text
core/
├── integrations/
│   ├── base.py
│   ├── factory.py
│   ├── intersolid/
│   │   ├── integration.py
│   │   └── profile.py
│   └── sysmo/
│       ├── integration.py
│       ├── repository.py
│       ├── mapper.py
│       ├── schemas.py
│       └── profile.py
├── api/
│   └── oriontax_api_client.py
├── sync/
│   ├── service.py
│   ├── result.py
│   └── lock.py
└── updater/
    ├── checker.py
    ├── downloader.py
    ├── manifest.py
    └── launcher.py

gui/
├── first_run.py
├── sysmo_settings.py
├── api_settings.py
└── update_dialog.py
```

Nomes podem ser ajustados durante a implementação, mas as responsabilidades
devem permanecer separadas.

---

## 4. Perfil da instalação e primeira execução

### 4.1 Assistente inicial

Quando ainda não existir `erp_type`, após autenticar o administrador o sistema
mostrará um assistente:

```text
Configurar esta instalação

ERP utilizado:
( ) Intersolid
( ) Sysmo

[Continuar]
```

Na etapa seguinte serão solicitadas apenas as configurações aplicáveis ao ERP.

### 4.2 Persistência

Adicionar ao SQLite uma tabela com uma única linha:

```sql
CREATE TABLE app_installation (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    installation_id TEXT NOT NULL UNIQUE,
    erp_type TEXT NOT NULL CHECK (erp_type IN ('intersolid', 'sysmo')),
    configured_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
```

`installation_id` será um UUID gerado na primeira execução. Ele não deve mudar
em upgrades e poderá identificar a instalação no heartbeat e suporte.

### 4.3 Troca de ERP

A troca ficará disponível somente para administrador em uma ação avançada.
Antes de trocar, o sistema deverá:

1. confirmar a intenção;
2. impedir a troca se houver sincronização em execução;
3. desativar os agendamentos atuais;
4. preservar configurações anteriores para possível retorno;
5. abrir o assistente do novo ERP;
6. exigir testes de conexão antes de ativar operações.

Não excluir credenciais ou histórico automaticamente.

---

## 5. Comportamento da interface por ERP

### 5.1 Estrutura comum

As abas permanecem comuns:

```text
Operações | Configurações | Logs | Agendamentos | Atualizações
```

Um `ERPProfile` fornecerá títulos, capacidades e rótulos. A interface não deve
conter vários `if erp == ...` espalhados.

### 5.2 Perfil Intersolid

Status:

```text
ERP: Intersolid
Banco do ERP: Oracle ou Firebird
Destino OrionTax: PostgreSQL
```

Operações:

- Enviar dados para OrionTax;
- Buscar dados da OrionTax;
- limpar tabelas temporárias, mantendo as ações atuais.

Configurações:

- Banco Intersolid;
- Banco OrionTax;
- heartbeat;
- atualização automática.

### 5.3 Perfil Sysmo

Status:

```text
ERP: Sysmo
Banco Sysmo: PostgreSQL
API OrionTax: conectada/desconectada
```

Operações:

- Enviar produtos para análise;
- Receber produtos tributados;
- cancelar operação em andamento.

Configurações:

- conexão PostgreSQL Sysmo;
- URL da API OrionTax;
- token Bearer;
- timeout HTTP;
- tamanho do lote de envio;
- tamanho da página de recebimento;
- heartbeat;
- atualização automática.

A seção de limpeza das tabelas temporárias Intersolid não aparecerá no perfil
Sysmo. Ações destrutivas na tabela Sysmo não serão expostas como botões comuns.

### 5.4 Terminologia de operação

Internamente, migrar gradualmente de `ENVIAR`/`BUSCAR` para nomes não ambíguos:

```text
EXPORT_TO_ORIONTAX
IMPORT_FROM_ORIONTAX
```

Durante a compatibilidade, o banco local poderá continuar persistindo
`ENVIAR`/`BUSCAR`, com tradução no serviço de integração.

---

## 6. Configurações Sysmo e API

### 6.1 Configuração PostgreSQL Sysmo

Persistir:

- host;
- porta, padrão 5432;
- nome do banco;
- usuário;
- senha criptografada;
- timeout de conexão;
- SSL mode, se utilizado;
- estado ativo;
- data do último teste bem-sucedido.

Criar tabela específica `config_sysmo`. Não reutilizar `config_oracle`, pois
isso perpetuaria o acoplamento entre ERP e tecnologia de banco.

### 6.2 Configuração da API

Persistir:

- URL base, sem endpoint fixo;
- token Bearer criptografado;
- timeout de conexão e leitura;
- tamanho do lote POST;
- tamanho de página GET, máximo atual 500;
- quantidade máxima de tentativas;
- verificação TLS sempre habilitada em produção;
- data do último teste bem-sucedido.

O token nunca será exibido integralmente ou registrado em logs.

### 6.3 Testes de configuração

O teste Sysmo deve validar:

- conexão PostgreSQL;
- existência de `tb_sysmointegradorenvio`;
- existência de `tb_sysmointegradorrecebimento`;
- presença das colunas obrigatórias;
- permissão de `SELECT` na tabela de envio;
- permissão necessária na tabela de recebimento sem alterar dados.

O teste da API deve validar:

- DNS, HTTPS e certificado;
- autenticação do token;
- compatibilidade mínima da API;
- resposta estruturada;
- latência aproximada.

É recomendável criar um endpoint de saúde/autenticação sem efeitos colaterais.
O `GET /api/v2/receber/` atual não serve como teste porque altera estados.

---

## 7. Fluxo Sysmo para OrionTax

### 7.1 Origem

Consultar `tb_sysmointegradorenvio` com as colunas documentadas na integração
Sysmo, incluindo:

- `cd_sequencial`;
- `cd_produto`;
- `tx_codigobarras`;
- `tx_descricaoproduto`;
- `tx_ncm`;
- `tx_cest`;
- `nr_cfop`;
- `nr_cst_icms`;
- alíquotas de ICMS/FCP;
- cBenef;
- CST e alíquotas de PIS/COFINS;
- natureza da receita;
- estados de origem e destino.

As colunas IBS/CBS serão detectadas no schema antes de serem selecionadas. A
integração não deve falhar em versões da Sysmo que ainda não as possuam.

### 7.2 Mapeamento para API V2

Criar um mapper explícito e testável:

| Sysmo | API OrionTax |
|---|---|
| `cd_produto` | `codigo` |
| `tx_codigobarras` | `codigo_barras` |
| `tx_descricaoproduto` | `descricao` |
| `tx_ncm` | `ncm` |
| `tx_cest` | `cest` |
| `nr_cfop` | `cfop` |
| `nr_cst_icms` | `icms_cst` |
| `vl_aliquota_integral_icms` | `icms_aliquota` |
| redução calculada/mapeada | `percentual_redbcde` |
| `tx_cbenef` | `cbenef` |
| `vl_aliquota_fcp` | `protege` |
| `nr_cst_pis` | `pis_cst` |
| `vl_aliquota_pis` | `pis_aliquota` |
| `vl_aliquota_cofins` | `cofins_aliquota` |
| `nr_naturezareceita` | `natureza_receita` |
| campos de reforma, quando existirem | campos IBS/CBS da API |

Regras exatas de redução e de `protege` deverão ser homologadas com dados reais.

### 7.3 Validação local

Antes do POST:

- garantir que o corpo seja uma lista;
- validar todas as chaves exigidas pela implementação real da API;
- preservar código e código de barras como texto;
- normalizar NCM e CST sem perda de zeros à esquerda;
- enviar `inf_ad_fisco` como boolean JSON, nunca string;
- validar `natureza_receita` antes da conversão inteira;
- limitar valores e comprimentos conforme contrato;
- rejeitar ou isolar registros inválidos antes de enviar o lote;
- produzir relatório com código do produto, campo e motivo.

### 7.4 Lotes

O tamanho será configurável, com valor inicial a ser homologado. O envio deve:

1. criar um identificador local da execução;
2. obter uma fotografia consistente da origem;
3. dividir a fotografia em lotes determinísticos;
4. enviar lotes sequencialmente no primeiro release;
5. registrar `job_id` por lote;
6. não reenviar automaticamente respostas HTTP 400;
7. repetir falhas transitórias com backoff;
8. interromper de forma segura quando cancelado.

Retentativas automáticas serão limitadas a erros de rede, timeout, HTTP 429 e
HTTP 5xx. Como o POST não possui chave de idempotência documentada, uma queda de
conexão após o servidor receber o payload pode causar duplicidade lógica. A API
deverá aceitar uma chave idempotente antes de retentativas totalmente seguras.

### 7.5 Resultado do POST

O HTTP 201 confirma somente validação síncrona e enfileiramento. Salvar:

- execução local;
- número do lote;
- quantidade enviada;
- `job_id` remoto;
- data/hora;
- status `accepted`, não `completed`.

### 7.6 Evolução necessária na API

Recomendado antes da operação automática em produção:

```http
GET /api/v2/jobs/{job_id}/
```

Estados esperados:

```text
queued | processing | completed | completed_with_errors | failed
```

Sem esse endpoint, o aplicativo deverá informar corretamente “recebido pela
API” e não “processado com sucesso”. O agendamento pode funcionar, mas a
observabilidade funcional ficará incompleta.

---

## 8. Fluxo OrionTax para Sysmo

### 8.1 Obtenção paginada

Usar:

```http
GET /api/v2/receber/?page=N&page_size=500
Authorization: Bearer <token>
```

O consumidor deve:

- validar `count`, `total_pages`, `page`, `page_size` e `results`;
- percorrer todas as páginas;
- não depender da ordem atual da API;
- deduplicar por código de produto;
- aceitar que estados 2 e 3 sejam reenviados;
- não gravar na Sysmo até obter e validar a fotografia completa;
- abortar a troca da fotografia se qualquer página falhar.

### 8.2 Risco conhecido do GET atual

O GET promove todos os itens de estado 1 para 2 antes de concluir a paginação.
Uma falha depois da primeira página pode marcar itens não recebidos como
enviados. Além disso, não existe ordenação determinística explícita.

Recomendação de evolução da API:

```http
POST /api/v2/exports/
GET  /api/v2/exports/{export_id}/items?page=N
POST /api/v2/exports/{export_id}/confirm/
```

O snapshot deve ter ordenação estável, expiração e confirmação somente depois
do commit na Sysmo.

### 8.3 Mapeamento para Sysmo

Aplicar o mapeamento já documentado no fluxo existente, incluindo:

- código e sequencial;
- descrição, código de barras, NCM e CEST;
- CFOP, CST e alíquotas ICMS;
- redução, FCP/PROTEGE e cBenef;
- CST e alíquotas PIS/COFINS;
- natureza da receita;
- estados de origem/destino;
- campos IBS/CBS quando suportados pelo schema Sysmo;
- `fl_recebido = 'S'`, conforme contrato atual.

### 8.4 Validação antes da escrita

Antes de modificar a tabela remota:

- consultar schema e comprimentos `varchar`;
- validar tipos e precisão numérica;
- validar campos obrigatórios;
- detectar códigos duplicados;
- validar sequenciais;
- registrar todos os produtos inválidos;
- impedir a substituição se a fotografia estiver vazia de forma inesperada;
- exigir confirmação de configuração para permitir fotografia vazia legítima.

### 8.5 Escrita segura

Primeira implementação compatível com o contrato atual:

```sql
BEGIN;
DELETE FROM tb_sysmointegradorrecebimento;
INSERT INTO tb_sysmointegradorrecebimento (...);
COMMIT;
```

Proteções obrigatórias:

- lock local por instalação, cliente e direção;
- nenhuma execução concorrente manual/agendada;
- transação única;
- rollback integral;
- timeout de comando;
- contagem antes/depois;
- log da execução;
- atualização local somente depois do commit.

Evolução preferível, se o contrato permitir: staging + validação + troca atômica
ou UPSERT, evitando `DELETE` global.

---

## 9. Concorrência, cancelamento e estado

### 9.1 Lock

Uma operação será identificada por:

```text
installation_id + client_id + direction
```

No primeiro release, bloquear também envio e recebimento simultâneos na mesma
base Sysmo, pois ambos participam do mesmo ciclo funcional.

### 9.2 Máquina de estados local

```text
created
  → reading_source
  → validating
  → sending/receiving
  → writing_destination
  → accepted/completed
  → failed/cancelled
```

Registrar início, fim, quantidade, etapa, erro resumido e detalhes técnicos.

### 9.3 Cancelamento

- durante SELECT: cancelar/fechar conexão com segurança;
- durante HTTP: usar timeout curto e cancelamento entre lotes/páginas;
- durante escrita Sysmo: fazer rollback, nunca deixar carga parcial;
- desabilitar atualização do aplicativo enquanto houver operação ativa.

---

## 10. Agendamentos

Os agendamentos atuais serão associados ao perfil da instalação. Regras:

- não executar se a configuração estiver incompleta;
- impedir sobreposição de jobs;
- aplicar `max_instances=1` e política explícita de `coalesce`;
- registrar “ignorado por operação em andamento” sem classificar como falha;
- configurar horários independentes para enviar e receber;
- permitir defasagem entre o POST e o GET, pois o POST é assíncrono;
- preferencialmente aguardar conclusão dos jobs antes do recebimento.

Sem endpoint de status, usar uma janela configurável entre envio e recebimento,
mas tratá-la como solução temporária, não como garantia de conclusão.

---

## 11. Logs, auditoria e monitoramento

Cada execução deverá registrar:

- ERP e versão do aplicativo;
- `installation_id` e cliente, sem credenciais;
- direção da operação;
- início, fim e duração;
- contagem lida, válida, rejeitada e gravada;
- lotes, páginas e `job_id` remoto;
- resultado de cada retentativa;
- etapa exata da falha;
- códigos de produtos problemáticos;
- cancelamento manual ou automático.

Não registrar:

- senha do PostgreSQL;
- token Bearer;
- header Authorization;
- URL contendo segredos;
- payload completo em nível INFO.

O heartbeat deve incluir `erp_type`, `installation_id`, versão, última execução e
status de atualização, desde que o servidor seja preparado para esses campos.

---

## 12. Atualização automática

### 12.1 Estratégia

O aplicativo não atualizará arquivos em uso diretamente. Ele baixará um
instalador produzido pelo Inno Setup, validará o pacote e o iniciará após
encerrar sincronizações e o próprio processo.

### 12.2 Workflow atual preservado

`.github/workflows/build.yml` continuará:

- sendo acionado nos pushes atuais;
- gerando `dist/OrionTaxSync/`;
- compactando `OrionTaxSync.zip`;
- publicando o artifact temporário existente.

Não será adicionada dependência do Inno Setup nesse workflow na primeira etapa.

### 12.3 Novo workflow isolado

Criar:

```text
.github/workflows/release-installer.yml
```

Gatilhos previstos:

```yaml
on:
  workflow_dispatch:
  push:
    tags:
      - 'v*.*.*'
```

Etapas:

1. checkout;
2. validar que a tag segue SemVer;
3. configurar Python 3.12;
4. instalar dependências;
5. executar testes;
6. gerar pasta com PyInstaller;
7. instalar/localizar Inno Setup no runner;
8. compilar `installer.iss` passando a versão da tag;
9. calcular SHA-256 do instalador;
10. gerar manifesto;
11. publicar artifact para execução manual;
12. quando acionado por tag, publicar GitHub Release.

Assim, falha no novo workflow não impede nem modifica o build atual.

### 12.4 Fonte única de versão

Hoje existe divergência:

```text
version.py:    1.0.5
installer.iss: 1.0.1
```

A versão de release será derivada da tag. O workflow deverá:

- retirar o prefixo `v`;
- validar SemVer;
- injetar a versão no build/instalador;
- conferir que a versão do aplicativo coincide;
- falhar antes de publicar se houver divergência.

Uma opção inicial simples é exigir que `APP_VERSION` já esteja igual à tag e
passar `/DMyAppVersion=<versão>` ao compilador Inno Setup.

### 12.5 Alteração no Inno Setup

Permitir override sem quebrar compilação local:

```ini
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
```

O nome do arquivo deve conter a versão:

```text
OrionTaxSync_Setup_1.1.0.exe
```

Manter o mesmo `AppId` em todas as versões para que o Inno reconheça upgrade.

### 12.6 Manifesto

Publicar `update-manifest.json`:

```json
{
  "schema_version": 1,
  "version": "1.1.0",
  "channel": "stable",
  "mandatory": false,
  "minimum_supported_version": "1.0.5",
  "installer_url": "https://servidor/releases/v1.1.0/OrionTaxSync_Setup_1.1.0.exe",
  "sha256": "...",
  "size": 123456789,
  "published_at": "2026-08-25T12:00:00Z",
  "release_notes": "Integração Sysmo e melhorias de atualização."
}
```

O manifesto pode ser hospedado em endpoint da OrionTax, GitHub Release ou
storage próprio. Para repositório privado, não incluir token GitHub no cliente;
nesse caso, servir arquivos por infraestrutura da OrionTax.

### 12.7 Verificação no aplicativo

- verificar no início sem bloquear a interface;
- repetir em intervalo configurável, inicialmente 12 horas;
- disponibilizar “Verificar atualizações” no menu Ajuda;
- comparar versões com `packaging.version.Version`;
- suportar canal `stable` inicialmente;
- ignorar versão já recusada, salvo atualização obrigatória;
- usar timeout e falhar silenciosamente para a operação principal;
- registrar somente diagnóstico necessário.

### 12.8 Instalação

Fluxo:

1. baixar para diretório temporário exclusivo;
2. validar tamanho e SHA-256;
3. futuramente validar assinatura digital Authenticode;
4. aguardar inexistência de sincronização ativa;
5. solicitar confirmação do usuário quando opcional;
6. iniciar instalador com parâmetros silenciosos;
7. encerrar o aplicativo;
8. instalar sobre o mesmo `AppId`/diretório;
9. reabrir o aplicativo;
10. validar startup e registrar versão atualizada.

Parâmetros iniciais possíveis:

```text
/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS
```

Como a instalação usa `{autopf}` e privilégios administrativos, o UAC poderá
ser exibido. Atualização totalmente silenciosa exigiria instalação por usuário
ou um serviço privilegiado, o que não faz parte da primeira entrega.

### 12.9 Dados fora da pasta de programa

Antes de habilitar auto-update, mover dados mutáveis para local persistente:

```text
%ProgramData%\OrionTaxSync\
├── data\oriontax.db
├── logs\
├── backups\
└── updates\
```

ou `%LocalAppData%` se a decisão for instalação por usuário.

Implementar migração idempotente da localização antiga, backup do SQLite antes
do upgrade e compatibilidade com instalações existentes.

Revisar `[UninstallDelete]`: desinstalação/upgrade não deve remover dados e logs
automaticamente. Exclusão definitiva deve ser uma escolha explícita.

### 12.10 Segurança da distribuição

Obrigatório para produção:

- HTTPS;
- SHA-256 do pacote;
- manifesto servido de origem controlada;
- proteção contra downgrade;
- rejeitar versão menor que a atual;
- nunca executar arquivo com hash divergente;
- limitar redirects e validar destino;
- registrar falhas de integridade.

Recomendado:

- certificado de assinatura de código;
- assinatura do instalador no CI por segredo protegido;
- proteção do environment de release no GitHub;
- aprovação manual para canal estável;
- retenção da versão anterior para rollback.

---

## 13. Banco local e migrações

Adicionar migrações incrementais para:

- `app_installation`;
- `config_sysmo`;
- `config_oriontax_api`;
- execuções de sincronização;
- lotes/jobs remotos;
- preferências de atualização;
- versão do schema local.

Todas as migrações devem ser:

- idempotentes;
- executadas antes de abrir a janela principal;
- transacionais quando possível;
- precedidas de backup em atualizações de schema;
- testadas partindo de um banco da versão 1.0.5.

Credenciais antigas não serão copiadas entre campos sem descriptografia e nova
criptografia controlada. Falha de descriptografia exige reconfiguração, sem
apagar o valor anterior.

---

## 14. Testes

### 14.1 Unitários

- factory retorna adaptador correto;
- perfil fornece textos/capacidades corretos;
- mapper Sysmo → API para todos os campos;
- mapper API → Sysmo;
- zeros à esquerda;
- valores nulos e vazios;
- redução de ICMS;
- booleanos;
- campos IBS/CBS presentes e ausentes;
- parser de manifesto;
- comparação SemVer;
- validação SHA-256.

### 14.2 Integração com banco Sysmo de teste

- conexão e schema;
- leitura vazia e volumosa;
- tipos incompatíveis;
- descrição acima do limite;
- escrita completa;
- rollback após falha;
- fotografia vazia protegida;
- execução concorrente bloqueada;
- cancelamento durante gravação.

### 14.3 Integração com API de homologação

- token válido/inválido;
- POST válido;
- validações HTTP 400;
- timeout e 5xx;
- registro de `job_id`;
- GET sem itens;
- múltiplas páginas;
- falha em página intermediária;
- duplicidade entre páginas;
- reenvio de estados 2/3;
- payload grande.

### 14.4 Regressão Intersolid

- conexão Oracle thin/thick;
- conexão Firebird;
- enviar;
- buscar;
- limpar temporárias;
- cancelar;
- execução manual;
- agendamento;
- heartbeat;
- leitura de configuração existente sem `erp_type`.

Para instalações antigas sem `erp_type`, a migração deve assumir `intersolid`,
evitando exibir assistente e alterar o comportamento atual.

### 14.5 Atualização

- build manual do instalador;
- release por tag;
- instalação limpa;
- upgrade sobre 1.0.5;
- preservação do SQLite/logs;
- aplicativo aberto durante upgrade;
- sincronização ativa impede update;
- hash incorreto;
- download interrompido;
- sem rede;
- UAC recusado;
- reinício após atualização;
- rollback/manual reinstalação da versão anterior.

---

## 15. Estratégia de entrega

### Fase 0 — decisões e homologação

- obter banco Sysmo de homologação;
- confirmar permissões e contrato das tabelas;
- validar campos IBS/CBS por versão;
- definir URL e política de autenticação da API;
- decidir hospedagem dos releases;
- decidir `%ProgramData%` ou `%LocalAppData%`;
- definir política de atualização obrigatória.

### Fase 1 — fundação multi-ERP

- criar `erp_type` e `installation_id`;
- migrar instalações antigas para Intersolid;
- criar fábrica e contrato de integração;
- envolver o fluxo Intersolid sem mudar seu comportamento;
- tornar textos e capacidades da GUI dependentes do perfil.

### Fase 2 — cliente API

- implementar autenticação Bearer;
- timeouts, TLS, paginação e erros;
- implementar modelos de request/response;
- criar mocks e testes;
- adicionar endpoint de teste sem efeito colateral.

### Fase 3 — adaptador Sysmo de envio

- configuração PostgreSQL;
- repository de leitura;
- detecção de schema;
- mapper e validação;
- lotes POST;
- persistência de `job_id` e logs;
- operação manual em homologação.

### Fase 4 — adaptador Sysmo de recebimento

- GET paginado;
- fotografia completa;
- mapper de retorno;
- validação de schema/tamanho;
- escrita transacional;
- lock, rollback e cancelamento;
- operação manual em homologação.

### Fase 5 — robustez da API

- endpoint de status de job;
- idempotência de POST;
- snapshot/ack no GET;
- ordenação determinística;
- homologar transições de estado ponta a ponta.

### Fase 6 — scheduler e monitoramento

- agendamentos Sysmo;
- bloqueio de sobreposição;
- heartbeat enriquecido;
- métricas e alertas;
- política de retentativa.

### Fase 7 — instalador isolado no CI/CD

- parametrizar `installer.iss`;
- criar `release-installer.yml`;
- gerar instalador e SHA-256;
- publicar artifact manual;
- testar instalação/upgrade;
- habilitar release por tag.

### Fase 8 — auto-update

- manifesto;
- verificação em background;
- download e validação;
- execução segura do instalador;
- migração de dados persistentes;
- assinatura de código;
- piloto e rollout gradual.

### Fase 9 — produção

- piloto com um cliente Sysmo;
- operação manual monitorada;
- reconciliação de contagens e amostras;
- habilitar agendamento;
- disponibilizar atualização opcional;
- acompanhar métricas;
- promover atualização obrigatória somente após estabilidade.

---

## 16. Critérios de aceite gerais

A integração será considerada pronta quando:

- a mesma build operar corretamente com Intersolid e Sysmo;
- instalação antiga assumir Intersolid sem intervenção;
- o perfil Sysmo nunca solicitar credenciais do banco OrionTax;
- nenhum segredo aparecer nos logs;
- envio registrar aceite e conclusão como estados diferentes;
- recebimento nunca deixar carga parcial na Sysmo;
- falha de uma página não substituir a fotografia anterior;
- jobs concorrentes forem bloqueados;
- cancelamento provocar rollback quando necessário;
- regressão Intersolid estiver aprovada;
- instalador atualizar uma versão existente preservando dados;
- pacote com hash inválido nunca for executado;
- falha do workflow de instalador não afetar o workflow atual.

---

# Checklist de execução

## A. Preparação e decisões

- [ ] Definir responsável técnico pela integração Sysmo.
- [ ] Disponibilizar PostgreSQL Sysmo de homologação.
- [ ] Obter usuário com permissões mínimas necessárias.
- [ ] Confirmar contrato oficial das tabelas de envio e recebimento.
- [ ] Confirmar se `DELETE + INSERT` é o mecanismo homologado.
- [ ] Levantar limites, tipos, constraints e triggers das tabelas.
- [ ] Confirmar disponibilidade dos campos IBS/CBS.
- [ ] Preparar cliente/token da API em homologação.
- [ ] Definir URL de produção e homologação.
- [ ] Definir hospedagem de manifesto e instaladores.
- [ ] Decidir `%ProgramData%` versus `%LocalAppData%`.
- [ ] Definir política de releases opcionais e obrigatórios.
- [ ] Definir plano de rollback.

## B. Fundação multi-ERP

- [ ] Criar migração `app_installation`.
- [ ] Gerar e persistir `installation_id`.
- [ ] Migrar instalações existentes automaticamente para `intersolid`.
- [ ] Criar assistente de primeira execução.
- [ ] Criar contrato `IntegrationAdapter`.
- [ ] Criar factory por `erp_type`.
- [ ] Encapsular integração atual em `IntersolidIntegration`.
- [ ] Criar perfis de UI Intersolid e Sysmo.
- [ ] Ocultar ações não suportadas por perfil.
- [ ] Implementar troca administrativa de ERP.
- [ ] Desativar agendamentos na troca de perfil.
- [ ] Executar regressão completa da Intersolid.

## C. Configuração Sysmo/API

- [ ] Criar `config_sysmo`.
- [ ] Criar `config_oriontax_api`.
- [ ] Criptografar senha e token.
- [ ] Criar tela de configuração Sysmo.
- [ ] Criar tela de configuração da API.
- [ ] Implementar teste read-only do schema Sysmo.
- [ ] Criar/confirmar endpoint de teste da API sem efeito colateral.
- [ ] Impedir logs de credenciais e headers.
- [ ] Validar configurações antes de habilitar operações.

## D. Sysmo para API

- [ ] Implementar repository PostgreSQL Sysmo.
- [ ] Implementar SELECT com schema detectado.
- [ ] Implementar mapper Sysmo → API V2.
- [ ] Homologar redução ICMS e PROTEGE.
- [ ] Normalizar zeros à esquerda e tipos.
- [ ] Implementar validação por produto.
- [ ] Implementar relatório de rejeições locais.
- [ ] Implementar lotes configuráveis.
- [ ] Implementar timeouts e backoff limitado.
- [ ] Persistir execução, lotes e `job_id`.
- [ ] Diferenciar `accepted` de `completed`.
- [ ] Testar carga vazia, pequena e volumosa.
- [ ] Testar cancelamento entre lotes.

## E. API para Sysmo

- [ ] Implementar GET paginado.
- [ ] Validar envelope e todas as páginas.
- [ ] Deduplicar por código.
- [ ] Tratar reenvio idempotente.
- [ ] Implementar mapper API → Sysmo.
- [ ] Validar tipos e comprimentos remotos.
- [ ] Proteger contra fotografia vazia inesperada.
- [ ] Implementar lock de sincronização.
- [ ] Implementar transação e rollback.
- [ ] Atualizar estado somente após commit.
- [ ] Testar falha em página intermediária.
- [ ] Testar falha durante INSERT.
- [ ] Testar cancelamento e concorrência.
- [ ] Reconciliar contagens ponta a ponta.

## F. Melhorias da API

- [ ] Criar endpoint de status do `job_id`.
- [ ] Criar chave idempotente no POST.
- [ ] Alinhar serializers síncrono e assíncrono.
- [ ] Tornar paginação determinística.
- [ ] Corrigir mudança de estado antes da entrega completa.
- [ ] Implementar snapshot e confirmação do GET.
- [ ] Validar cliente ativo na autenticação.
- [ ] Documentar contrato OpenAPI efetivo.

## G. Scheduler e observabilidade

- [ ] Associar agendamentos ao perfil ERP.
- [ ] Configurar `max_instances=1`.
- [ ] Definir política de `coalesce` e atraso.
- [ ] Impedir operações manuais concorrentes.
- [ ] Persistir máquina de estados da execução.
- [ ] Enriquecer logs com lotes/páginas/jobs.
- [ ] Enriquecer heartbeat com ERP e instalação.
- [ ] Criar alertas para falhas consecutivas.
- [ ] Testar reinício durante sincronização.

## H. Workflow Inno Setup isolado

- [ ] Manter `.github/workflows/build.yml` sem mudança funcional.
- [ ] Parametrizar `MyAppVersion` em `installer.iss`.
- [ ] Manter o mesmo `AppId`.
- [ ] Incluir versão no nome do instalador.
- [ ] Criar `.github/workflows/release-installer.yml`.
- [ ] Adicionar `workflow_dispatch`.
- [ ] Adicionar gatilho por tag SemVer.
- [ ] Instalar/localizar Inno Setup no runner.
- [ ] Gerar pasta PyInstaller no novo workflow.
- [ ] Compilar instalador.
- [ ] Calcular SHA-256.
- [ ] Publicar artifact na execução manual.
- [ ] Publicar GitHub Release somente por tag.
- [ ] Proteger environment de release.
- [ ] Testar que falha desse workflow não afeta o atual.

## I. Persistência e instalador

- [ ] Definir fonte única da versão.
- [ ] Alinhar `version.py` e `installer.iss`.
- [ ] Mover SQLite e logs para diretório persistente.
- [ ] Criar migração idempotente do caminho antigo.
- [ ] Fazer backup antes de migrar schema.
- [ ] Remover exclusão automática de dados no uninstall/upgrade.
- [ ] Testar instalação limpa.
- [ ] Testar upgrade sobre 1.0.5.
- [ ] Testar preservação de credenciais e agendamentos.
- [ ] Testar UAC e aplicativo aberto.

## J. Auto-update

- [ ] Definir schema do manifesto.
- [ ] Publicar manifesto de homologação.
- [ ] Implementar parser e validação.
- [ ] Comparar versões com `packaging.version.Version`.
- [ ] Implementar verificação em background.
- [ ] Adicionar ação manual em Ajuda.
- [ ] Criar diálogo de release notes.
- [ ] Baixar para diretório temporário exclusivo.
- [ ] Validar tamanho e SHA-256.
- [ ] Bloquear downgrade.
- [ ] Impedir update durante sincronização.
- [ ] Executar instalador e encerrar aplicativo.
- [ ] Reabrir e confirmar versão instalada.
- [ ] Tratar download interrompido e sem rede.
- [ ] Implementar assinatura Authenticode.
- [ ] Testar rollback.

## K. Homologação e rollout

- [ ] Executar suíte unitária.
- [ ] Executar testes de integração Sysmo.
- [ ] Executar regressão Intersolid.
- [ ] Validar segurança dos logs.
- [ ] Instalar em máquina limpa de homologação.
- [ ] Atualizar uma instalação existente.
- [ ] Selecionar cliente piloto Sysmo.
- [ ] Executar primeiro envio manual.
- [ ] Conferir `job_id` e resultado funcional.
- [ ] Executar primeiro recebimento manual.
- [ ] Comparar amostra campo a campo na Sysmo.
- [ ] Habilitar agendamento no piloto.
- [ ] Monitorar ao menos um ciclo operacional acordado.
- [ ] Liberar atualização opcional.
- [ ] Expandir rollout gradualmente.
- [ ] Tornar atualização obrigatória somente após estabilidade.

---

## 17. Ordem recomendada para iniciar

Os primeiros itens concretos são:

1. validar o contrato e schema Sysmo em homologação;
2. criar a fundação multi-ERP sem alterar o comportamento Intersolid;
3. implementar e testar o cliente HTTP da API;
4. entregar primeiro o envio Sysmo → API manual;
5. entregar o recebimento API → Sysmo manual;
6. fortalecer a API com status/idempotência/snapshot;
7. habilitar scheduler;
8. criar o workflow Inno isolado e testar upgrades;
9. habilitar auto-update após os dados estarem fora da pasta do programa;
10. executar piloto e rollout gradual.

Essa ordem reduz o risco: cada etapa pode ser validada sem depender da próxima e
o workflow atual continua disponível durante toda a evolução.
