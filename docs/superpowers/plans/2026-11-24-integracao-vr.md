# Integração VR (VRMaster) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Novo perfil ERP `vr` que lê a tributação dos produtos da VR Integração Fiscal API, envia para a API OrionTax V2 no mesmo contrato da Sysmo e grava de volta na VR a tributação recebida da OrionTax.

**Architecture:** Mesmo desenho da Sysmo: um `IntegrationAdapter` (`VrIntegration`) com `send`/`receive`, criado pela `create_integration`. O acesso ao ERP é HTTP (`VrApiClient`, urllib, sem dependência nova), não banco. Funções puras isolam as conversões: `mapper.py` (leitura VR → payload OrionTax) e `correction.py` (payload OrionTax + estado atual VR → item do `PATCH /v2/integracaofiscal` e corpos do `/classificacaoTributaria/vincular`).

**Tech Stack:** Python 3, urllib, SQLite (`config/database.py`), PyQt5, unittest.

**Spec:** `docs/VR Integração Fiscal API — Referência completa para integração.md` (doravante "spec VR"). Contrato OrionTax: `core/api/oriontax_api_client.py` e `core/integrations/sysmo/mapper.py`.

## Global Constraints

- Sem novas dependências em `requirements.txt`; HTTP via `urllib` como em `core/api/oriontax_api_client.py`.
- A VR responde em HTTP sem TLS (porta 9025 ou 9010): a URL da VR aceita `http://` e `https://`; a URL OrionTax continua exigindo `https://`.
- Cabeçalho: `Authorization: Bearer <token>`, um espaço após Bearer. Token vem de `POST /auth` com `{"auth": {"tokenVRMaster": "<token>"}}`; resposta `{"retorno": ["<jwt>"]}`, válido por 24 h.
- Leitura: `GET /v3/produtos` com `cnpj` (14 dígitos, string), `usaPaginacao=true`, `numeroPagina` (a partir de 1), `itensPorPagina`. Gravação: `PATCH /v2/integracaofiscal` (lista) e `PATCH /classificacaoTributaria/vincular`.
- Cenário de ICMS usado nos dois sentidos: `icmsConsumidorFinal` (decisão do usuário, 2026-11-24).
- CNPJ e EAN chegam como inteiros nos retornos: sempre normalizar CNPJ com `zfill(14)` antes de comparar.
- A UF da loja não vem da API: fica no cadastro de clientes (`clientes.uf`, decisão do usuário, 2026-11-24). Para o perfil VR a UF é obrigatória; sem ela o envio/recebimento daquela loja para com mensagem clara.
- Mensagens ao usuário em português, no mesmo tom das da Sysmo (`⚠` para avisos, `[DRY-RUN]` para simulação).
- `ORIONTAX_DRY_RUN=1` faz o `receive` montar e registrar os payloads sem chamar nenhum endpoint de gravação da VR (mesma variável já usada pela Sysmo).
- POST/PATCH nunca são repetidos automaticamente; só GET tem retentativa. Um 401 dispara uma única renovação de token e uma nova tentativa (o servidor não processou a requisição).
- Testes: `python3 -m unittest discover -s tests` precisa continuar verde ao fim de cada task.

## Review Focus

1. **CNPJ com zero à esquerda** (`lojas[].cnpj` vem como inteiro, ex. `1234567000195`): a loja precisa ser encontrada no grupo mesmo assim. Teste em Task 3.
2. **Servidor ignora a paginação** e devolve a lista inteira em toda página: a leitura deve parar quando uma página não traz nenhum código novo, sem laço infinito. Teste em Task 2.
3. **Token expirado no meio da execução** (401 numa chamada qualquer): renova uma vez e segue; um segundo 401 vira erro claro. Teste em Task 2.
4. **Envelope real diferente do schema** (`{"retorno": [...]}` em vez de `{"produtos": [...]}`, seção 2.3 da spec VR): o cliente aceita as duas chaves. Teste em Task 2.
5. **Produto recebido da OrionTax que não existe/não está ativo na loja VR, ou com código não numérico**: vira rejeição com motivo, sem derrubar o lote. Teste em Task 5.

---

### Task 1: Perfil `vr`, configuração da API VR e UF da loja no banco local

**Files:**
- Modify: `config/database.py` (bloco `app_installation`, tabela `clientes`, `set_erp_type`, `create_cliente`, `update_cliente`, novos `get_cliente_by_cnpj_threadsafe`, `save_vr_config`, `get_vr_config`)
- Test: `tests/test_database_v2.py`

**Interfaces:**
- Produces:
  - `DatabaseManager.set_erp_type(erp_type)` aceita `"intersolid" | "sysmo" | "vr"`.
  - `DatabaseManager.save_vr_config(base_url: str, token: str, timeout_seconds: int = 60, page_size: int = 500, patch_batch_size: int = 50) -> bool`
  - `DatabaseManager.get_vr_config() -> Optional[dict]` com chaves `base_url, token, timeout_seconds, page_size, patch_batch_size` (token descriptografado; `None` se não configurado ou token vazio).
  - `DatabaseManager.create_cliente(nome: str, cnpj: str, uf: Optional[str] = None) -> bool` e `update_cliente(cliente_id: int, nome: str, cnpj: str, uf: Optional[str] = None) -> bool` — gravam `uf.strip().upper()` ou `NULL` para vazio; UF fora das 27 siglas → `False`.
  - `DatabaseManager.get_cliente_by_cnpj_threadsafe(cnpj: str) -> Optional[dict]` — cliente ativo pelo CNPJ (aceita com ou sem máscara), com a chave `uf`.
  - `UFS` (tupla com as 27 siglas, ordem alfabética) exportada por `config/database.py` para o diálogo de clientes.

- [ ] **Step 1: Write the failing tests**

```python
def test_switches_to_vr(self):
    self.db.set_erp_type("vr")
    self.assertEqual("vr", self.db.get_installation()["erp_type"])

def test_vr_config_round_trip(self):
    self.assertIsNone(self.db.get_vr_config())
    self.db.save_vr_config("http://10.0.0.5:9025/", "tok", page_size=200)
    cfg = self.db.get_vr_config()
    self.assertEqual("http://10.0.0.5:9025", cfg["base_url"])
    self.assertEqual("tok", cfg["token"])
    self.assertEqual(200, cfg["page_size"])
    self.assertEqual(50, cfg["patch_batch_size"])

def test_cliente_stores_optional_uf(self):
    self.assertTrue(self.db.create_cliente("Loja 1", "01.234.567/0001-95", " go "))
    self.assertTrue(self.db.create_cliente("Loja 2", "22881305000192"))
    self.assertEqual("GO", self.db.get_cliente_by_cnpj_threadsafe("01234567000195")["uf"])
    self.assertIsNone(self.db.get_cliente_by_cnpj_threadsafe("22.881.305/0001-92")["uf"])
    self.assertIsNone(self.db.get_cliente_by_cnpj_threadsafe("11111111000111"))

def test_cliente_rejects_invalid_uf_and_updates(self):
    self.assertFalse(self.db.create_cliente("Loja", "22881305000192", "XX"))
    self.db.create_cliente("Loja", "22881305000192")
    cid = self.db.get_cliente_by_cnpj_threadsafe("22881305000192")["id"]
    self.assertTrue(self.db.update_cliente(cid, "Loja", "22881305000192", "sp"))
    self.assertEqual("SP", self.db.get_cliente(cid)["uf"])

def test_adds_uf_column_to_existing_clientes(self):
    path = Path(self.temp.name) / "old_clientes.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, "
                 "cnpj TEXT UNIQUE NOT NULL, is_active INTEGER DEFAULT 1, "
                 "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("INSERT INTO clientes (nome, cnpj) VALUES ('Antiga', '22881305000192')")
    conn.commit(); conn.close()
    db = DatabaseManager(path)
    try:
        self.assertIsNone(db.get_cliente_by_cnpj_threadsafe("22881305000192")["uf"])
    finally:
        db.disconnect()

def test_migrates_old_erp_check_constraint(self):
    # banco criado pela versão 2.0.0.x, cujo CHECK não conhece 'vr'
    path = Path(self.temp.name) / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE app_installation (
        id INTEGER PRIMARY KEY CHECK (id = 1), installation_id TEXT NOT NULL UNIQUE,
        erp_type TEXT NOT NULL CHECK(erp_type IN ('intersolid', 'sysmo')),
        configured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("INSERT INTO app_installation (id, installation_id, erp_type) VALUES (1, 'abc', 'sysmo')")
    conn.commit(); conn.close()
    db = DatabaseManager(path)
    try:
        self.assertEqual("sysmo", db.get_installation()["erp_type"])
        self.assertEqual("abc", db.get_installation()["installation_id"])
        db.set_erp_type("vr")
        self.assertEqual("vr", db.get_installation()["erp_type"])
    finally:
        db.disconnect()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_database_v2 -v`
Expected: FAIL (`ValueError: ERP inválido` e `AttributeError: save_vr_config`).

- [ ] **Step 3: Implement in `config/database.py`**

- `CHECK(erp_type IN ('intersolid', 'sysmo', 'vr'))` no `CREATE TABLE`.
- Migração logo após o `CREATE TABLE IF NOT EXISTS app_installation`: se `SELECT sql FROM sqlite_master WHERE name='app_installation'` não contém `'vr'`, recriar a tabela (`CREATE TABLE app_installation_new` com o CHECK novo, `INSERT ... SELECT *`, `DROP`, `ALTER TABLE ... RENAME`) preservando a linha.
- Coluna `uf TEXT` em `clientes`: no `CREATE TABLE` e na lista de migrações com `ALTER TABLE clientes ADD COLUMN uf TEXT` (mesmo padrão `try/except sqlite3.OperationalError` das colunas Firebird).
- Tabela `config_vr`: `id INTEGER PRIMARY KEY CHECK (id = 1)`, `base_url TEXT NOT NULL`, `token_encrypted TEXT NOT NULL`, `timeout_seconds INTEGER NOT NULL DEFAULT 60`, `page_size INTEGER NOT NULL DEFAULT 500`, `patch_batch_size INTEGER NOT NULL DEFAULT 50`, `is_active INTEGER NOT NULL DEFAULT 1`, `updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`.
- `save_vr_config` segue `save_sysmo_config` (upsert `ON CONFLICT(id)`, token via `encryption_manager`), grava `base_url.rstrip('/')`. `get_vr_config` segue `get_sysmo_config`. `get_cliente_by_cnpj_threadsafe` segue `get_all_clientes_threadsafe` (conexão própria, porque o agendador chama de outra thread).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_database_v2 -v`
Expected: PASS (todos, inclusive os antigos).

- [ ] **Step 5: Commit**

```bash
git add config/database.py tests/test_database_v2.py
git commit -m "feat: adiciona perfil ERP vr, configuracao da API VR e UF da loja"
```

---

### Task 2: Cliente HTTP da VR Integração Fiscal API

**Files:**
- Create: `core/api/vr_api_client.py`
- Modify: `core/api/__init__.py` (exportar `VrApiClient`, `VrApiError`)
- Test: `tests/test_vr_api_client.py`

**Interfaces:**
- Consumes: dict de `get_vr_config()` (Task 1).
- Produces (`core.api.vr_api_client`):
  - `class VrApiError(RuntimeError)` com `status_code: Optional[int]`.
  - `class VrApiClient(config: dict)`; atributos `base_url`, `page_size`, `patch_batch_size`.
  - `info() -> dict` — `GET /info`, sem auth.
  - `authenticate() -> str` — `POST /auth`, guarda o JWT.
  - `list_products(cnpj: str, cancel_check: Callable[[], bool] = None) -> List[dict]` — todas as páginas de `GET /v3/produtos`.
  - `list_grupos_economicos() -> List[dict]` — `GET /gruposeconomicos`, chave `grupoEconomico`.
  - `list_icms(uf: str) -> List[dict]` — `GET /icms?uf=`, chave `icms`.
  - `list_piscofins() -> List[dict]` — `GET /piscofins`, chave `pisCofins`.
  - `list_pautas_fiscais(uf: str) -> List[dict]` — `GET /pautasfiscais?uf=`, chave `pautasFiscais`.
  - `list_classificacoes(cnpj: str) -> List[dict]` — `GET /classificacaoTributaria?cnpj=`, chave `retorno`.
  - `patch_integracao_fiscal(items: List[dict]) -> List[dict]` — devolve `integracaoFiscal[]`.
  - `vincular_classificacao(body: dict) -> dict` — devolve `detalhes`.
  - Método interno `_request(method, path, body=None, query=None, auth=True) -> (status, payload)`; os testes o substituem como em `tests/test_api_client.py::FakeApi`.

- [ ] **Step 1: Write the failing tests**

Fake que sobrescreve um transporte de baixo nível `_send(method, url, body, headers) -> (status, payload)` (o `_request` real cuida de auth/401/retry e chama `_send`), registrando as chamadas:

```python
def test_authenticates_and_sends_bearer(self):
    api = FakeVr([(200, {"retorno": ["jwt1"]}), (200, {"produtos": []})])
    api.list_products("22881305000192")
    self.assertEqual(("POST", "/auth"), api.calls[0][:2])
    self.assertEqual({"auth": {"tokenVRMaster": "tok"}}, api.calls[0][2])
    self.assertEqual("Bearer jwt1", api.calls[1][3]["Authorization"])

def test_reads_all_pages_until_short_page(self):
    page = lambda codes: (200, {"produtos": [{"codigo": c} for c in codes]})
    api = FakeVr([(200, {"retorno": ["jwt"]}), page([1, 2]), page([3])], page_size=2)
    self.assertEqual([1, 2, 3], [p["codigo"] for p in api.list_products("1")])
    self.assertIn("numeroPagina=2", api.calls[2][1])
    self.assertIn("usaPaginacao=true", api.calls[2][1])

def test_stops_when_server_ignores_pagination(self):
    full = (200, {"produtos": [{"codigo": 1}, {"codigo": 2}]})
    api = FakeVr([(200, {"retorno": ["jwt"]}), full, full, full], page_size=2)
    self.assertEqual([1, 2], [p["codigo"] for p in api.list_products("1")])

def test_accepts_retorno_envelope(self):
    api = FakeVr([(200, {"retorno": ["jwt"]}), (200, {"retorno": [{"codigo": 9}]})])
    self.assertEqual([{"codigo": 9}], api.list_products("1"))

def test_reauthenticates_once_on_401(self):
    api = FakeVr([(200, {"retorno": ["old"]}), (401, None), (200, {"retorno": ["new"]}), (200, {"produtos": []})])
    api.list_products("1")
    self.assertEqual("Bearer new", api.calls[-1][3]["Authorization"])

def test_second_401_raises(self):
    api = FakeVr([(200, {"retorno": ["a"]}), (401, None), (200, {"retorno": ["b"]}), (401, None)])
    with self.assertRaisesRegex(VrApiError, "401"):
        api.list_grupos_economicos()

def test_patch_is_not_retried_on_500(self):
    api = FakeVr([(200, {"retorno": ["jwt"]}), (500, {"info": "erro"})])
    with self.assertRaises(VrApiError):
        api.patch_integracao_fiscal([{"codigoProduto": 1}])
    self.assertEqual(2, len(api.calls))

def test_patch_returns_item_results(self):
    api = FakeVr([(200, {"retorno": ["jwt"]}),
                  (200, {"integracaoFiscal": [{"codigoProduto": 1, "status": "OK", "info": "x"}]})])
    self.assertEqual("OK", api.patch_integracao_fiscal([{"codigoProduto": 1}])[0]["status"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_vr_api_client -v`
Expected: FAIL with `ModuleNotFoundError: core.api.vr_api_client`.

- [ ] **Step 3: Implement `VrApiClient` in `core/api/vr_api_client.py`**

- Estrutura de `_send` e tratamento de `HTTPError`/`URLError` copiados do estilo de `OrionTaxApiClient._request` (mesmo `_json_default` para `Decimal`). `_send` devolve `(status, payload)` também para 4xx/5xx em vez de levantar; `_request` decide.
- `_request`: autentica sob demanda; em 401 com `auth=True`, renova o token uma vez e repete; GET repete até `max_retries` (padrão 3) em 429/5xx/erro de rede com `sleep(min(2**n, 8))`; demais status ≥ 400 viram `VrApiError(f"API VR retornou HTTP {status}: {detalhe}", status)`.
- Extração do envelope: `_data(payload, key)` devolve `payload[key]` se presente, senão `payload["retorno"]`, senão `[]`; levanta `VrApiError` se o resultado não for lista (ou dict, para `detalhes`).
- `list_products`: `itensPorPagina=self.page_size`; para quando a página vem vazia, menor que `page_size`, ou sem nenhum `codigo` ainda não visto; chama `cancel_check()` entre páginas e levanta `VrApiError("Operação cancelada.")` se verdadeiro.
- `page_size = max(1, int(config.get("page_size", 500)))`, `patch_batch_size = max(1, int(config.get("patch_batch_size", 50)))`, `timeout = int(config.get("timeout_seconds", 60))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_vr_api_client -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/api/vr_api_client.py core/api/__init__.py tests/test_vr_api_client.py
git commit -m "feat: adiciona cliente HTTP da VR Integracao Fiscal API"
```

---

### Task 3: Mapper VR → payload OrionTax

**Files:**
- Create: `core/integrations/vr/__init__.py` (vazio nesta task), `core/integrations/vr/mapper.py`
- Test: `tests/test_vr_mapper.py`

**Interfaces:**
- Produces (`core.integrations.vr.mapper`):
  - `ICMS_SCENARIO = "icmsConsumidorFinal"`
  - `@dataclass(frozen=True) class VrStoreContext: cnpj: str; uf: str; grupo_codigo: int; grupo_nome: str; regime: str`
  - `build_store_context(cnpj: str, uf: str, grupos: List[dict]) -> VrStoreContext` — `ValueError` se o CNPJ não está em nenhum `lojas[]`.
  - `regime_block(cadastro: dict, regime: str) -> dict` — `tributacaoLucroReal` se `"REAL"` in `regime.upper()`, senão `tributacaoLucroPresumido` (`{}` se ausente).
  - `normalize_ean(value) -> str` — completa com zeros até o menor tamanho em (8, 12, 13, 14) ≥ ao comprimento; `""` para vazio.
  - `parse_percent(value) -> Optional[float]` — `"60%"`→60.0, `"12,5%"`→12.5, `None`/`""`→None, número passa.
  - `digits(value) -> str` — só os dígitos.
  - `pick_classificacao(items: List[dict], today: date) -> Optional[dict]` — item com `dataInicioCst <= today <= dataFimCst` (`dd/MM/yyyy`; fim vazio = aberto); senão o primeiro; `None` para lista vazia.
  - `vr_product_to_api(product: dict, ctx: VrStoreContext, today: date) -> dict` — mesmas chaves de `sysmo_row_to_api`; `ValueError` com `"Produto <codigo>: ..."` para rejeições.

- [ ] **Step 1: Write the failing tests**

Fixture `vr_product()` com `codigo: 86922`, `descricao: " Desinfetante "`, `codigosBarras: [789123456789]`, `classificacaoFiscal: {"ncm": "1901.90.00", "cest": "17.004.00", "exTIPI": 0}`, `aliquotas: [{"uf": "SP", ...}, {"uf": "GO", "icmsConsumidorFinal": {"cst": "20", "csosn": "", "percentual": 19, "percentualReducao": 26.32, "percentualFCP": 2, "cBenef": "GO821001"}, "icmsDebito": {"cst": "00", "percentual": 19}}]`, `pisCofins: [{"grupoEconomico": "Outro", ...}, {"grupoEconomico": "Lojas Serve Bem", "naturezaReceita": 0, "debito": {"codigo": 3, "cst": 1, "tributacaoLucroReal": {"pis": 1.65, "cofins": 7.6}, "tributacaoLucroPresumido": {"pis": 0.65, "cofins": 3}}, "credito": {"codigo": 9, "cst": 50, "tributacaoLucroReal": {"pis": 1.65, "cofins": 7.6, "reducao": 0}}}]`, `classificacaoTributaria: [{"cst": "000", "cClassTrib": "000001", "percentualReducao": "0%", "dataInicioCst": "01/01/2025", "dataFimCst": "31/12/2025"}, {"cst": "200", "cClassTrib": "200003", "percentualReducao": "60%", "dataInicioCst": "01/01/2026", "dataFimCst": ""}]`. Contexto `VrStoreContext("01234567000195", "GO", 1, "Lojas Serve Bem", "LUCRO REAL")`, `today = date(2026, 11, 24)`.

```python
def test_store_context_matches_cnpj_with_leading_zero(self):
    grupos = [{"codigo": 7, "nome": "Lojas Serve Bem", "regimeTributario": "LUCRO REAL",
               "lojas": [{"cnpj": 1234567000195}]}]
    ctx = build_store_context("01.234.567/0001-95", "go", grupos)
    self.assertEqual(("01234567000195", "GO", 7, "LUCRO REAL"), (ctx.cnpj, ctx.uf, ctx.grupo_codigo, ctx.regime))

def test_store_context_rejects_unknown_cnpj(self):
    with self.assertRaisesRegex(ValueError, "grupo econômico"):
        build_store_context("11111111000111", "GO", [{"codigo": 1, "nome": "X", "lojas": []}])

def test_maps_identification_and_classification(self):
    p = vr_product_to_api(vr_product(), CTX, TODAY)
    self.assertEqual("86922", p["codigo"])
    self.assertEqual("Desinfetante", p["descricao"])
    self.assertEqual("0789123456789", p["codigo_barras"])
    self.assertEqual("19019000", p["ncm"])
    self.assertEqual("1700400", p["cest"])
    self.assertIsNone(p["cfop"]); self.assertIsNone(p["sequencial"])
    self.assertEqual(("GO", "GO"), (p["estado_origem"], p["estado_destino"]))

def test_maps_icms_from_consumer_scenario_of_store_uf(self):
    p = vr_product_to_api(vr_product(), CTX, TODAY)
    self.assertEqual((20, 19.0, 26.32, 2.0, "GO821001"),
                     (p["icms_cst"], p["icms_aliquota"], p["percentual_redbcde"], p["protege"], p["cbenef"]))

def test_uses_csosn_when_cst_is_empty(self):
    prod = vr_product(); prod["aliquotas"][1]["icmsConsumidorFinal"].update(cst="", csosn="102")
    self.assertEqual(102, vr_product_to_api(prod, CTX, TODAY)["icms_cst"])

def test_rejects_product_without_store_uf(self):
    prod = vr_product(); prod["aliquotas"] = prod["aliquotas"][:1]
    with self.assertRaisesRegex(ValueError, "Produto 86922: .*UF GO"):
        vr_product_to_api(prod, CTX, TODAY)

def test_maps_pis_cofins_of_store_group_and_regime(self):
    p = vr_product_to_api(vr_product(), CTX, TODAY)
    self.assertEqual(("01", 1.65, 7.6, 0), (p["pis_cst"], p["pis_aliquota"], p["cofins_aliquota"], p["natureza_receita"]))
    presumido = VrStoreContext(CTX.cnpj, "GO", 1, "Lojas Serve Bem", "LUCRO PRESUMIDO")
    self.assertEqual(0.65, vr_product_to_api(vr_product(), presumido, TODAY)["pis_aliquota"])

def test_missing_group_pis_sends_nulls(self):
    prod = vr_product(); prod["pisCofins"] = []
    p = vr_product_to_api(prod, CTX, TODAY)
    self.assertIsNone(p["pis_cst"]); self.assertEqual(0.0, p["pis_aliquota"])

def test_maps_current_ibs_cbs_classification(self):
    p = vr_product_to_api(vr_product(), CTX, TODAY)
    self.assertEqual(("200", "200003", 60.0, 60.0), (p["cst_ibs_cbs"], p["c_class_trib"], p["p_red_aliq_ibs"], p["p_red_aliq_cbs"]))
    self.assertIsNone(p["aliquota_ibs"]); self.assertIsNone(p["aliquota_cbs"])

def test_normalize_ean_and_parse_percent(self):
    self.assertEqual("00001234", normalize_ean(1234))
    self.assertEqual("7891234567895", normalize_ean(7891234567895))
    self.assertEqual("", normalize_ean(None))
    self.assertEqual(12.5, parse_percent("12,5%"))
    self.assertIsNone(parse_percent(""))

def test_rejects_missing_ncm(self):
    prod = vr_product(); prod["classificacaoFiscal"]["ncm"] = ""
    with self.assertRaisesRegex(ValueError, "ncm"):
        vr_product_to_api(prod, CTX, TODAY)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_vr_mapper -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `core/integrations/vr/mapper.py`**

- `icms_cst`: `int(cst)` se `cst` tem dígitos, senão `int(csosn)` se tem dígitos, senão `None`. Percentuais via `float`, ausentes → `0.0` (como `_number` da Sysmo).
- `pis_cst`: `str(debito["cst"]).zfill(2)`; alíquotas de `regime_block(debito, ctx.regime)`; sem item do grupo → `pis_cst=None`, alíquotas `0.0`, `natureza_receita=0`.
- Campos obrigatórios iguais a `REQUIRED_NON_EMPTY_FIELDS` da Sysmo (`codigo`, `descricao`, `ncm`); importar a constante de `core.integrations.sysmo.mapper`.
- `inf_ad_fisco=False`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_vr_mapper -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/integrations/vr/ tests/test_vr_mapper.py
git commit -m "feat: mapeia produtos da VR para o contrato da API OrionTax"
```

---

### Task 4: `VrIntegration.send` e registro na fábrica

**Files:**
- Create: `core/integrations/vr/integration.py`
- Modify: `core/integrations/vr/__init__.py` (exportar `VrIntegration`), `core/integrations/factory.py`, `core/integrations/profiles.py`
- Test: `tests/test_vr_integration.py`

**Interfaces:**
- Consumes: `VrApiClient` (Task 2), `build_store_context`, `vr_product_to_api` (Task 3), `OrionTaxApiClient.send_products`, `SyncLockRegistry`, `SyncResult`.
- Produces:
  - `class VrIntegration(IntegrationAdapter)`; `erp_type = "vr"`; `__init__(vr_config: dict, api_config: dict, installation_id: str, store_lookup: Callable[[str], Optional[dict]])`; atributos `self.vr` (`VrApiClient`), `self.api` (`OrionTaxApiClient`), `self.store_lookup`, `self.dry_run` (`os.environ.get("ORIONTAX_DRY_RUN") == "1"`).
  - `VrIntegration._store_uf(cnpj: str) -> str` — `self.store_lookup(cnpj)["uf"]`; cliente ausente ou sem UF → `ValueError("Informe a UF da loja <nome ou CNPJ formatado> no cadastro de clientes.")`. Usado por `send` e `receive` antes de qualquer chamada à VR; o `ValueError` vira `SyncResult(False, msg)`.
  - `send(cnpj, progress_callback=None) -> SyncResult`.
  - `receive(...)` levanta `NotImplementedError` nesta task (Task 6 implementa).
  - `cancel()` marca `self._cancelled = True` (lido via `cancel_check`).
  - `create_integration(db, "vr")` → `VrIntegration(..., store_lookup=db.get_cliente_by_cnpj_threadsafe)`; `RuntimeError("Configure a API VR e a API OrionTax antes de sincronizar.")` sem config.
  - `ERP_PROFILES["vr"] = {"name": "VR", "erp_connection": "API VR Integração Fiscal", "oriontax_connection": "API OrionTax", "send_label": "📤 Enviar Produtos para Análise", "receive_label": "📥 Receber Produtos Tributados", "show_tmp_cleanup": False}`.

- [ ] **Step 1: Write the failing tests**

Construir `VrIntegration` e trocar `integration.vr` e `integration.api` por stubs (`list_grupos_economicos`, `list_products`, `send_products` registrando lotes e devolvendo `"job-N"`), `api.batch_size = 2`.

```python
def test_send_maps_batches_and_reports_rejections(self):
    # 3 produtos válidos + 1 sem tributação na UF da loja
    result = integration.send("01234567000195", progress.append)
    self.assertTrue(result.success)
    self.assertEqual(3, result.records)
    self.assertEqual(["job-1", "job-2"], result.accepted_jobs)
    self.assertEqual(1, result.details["rejected_count"])
    self.assertTrue(any("UF GO" in m for m in progress))

def test_send_fails_when_cnpj_not_in_any_group(self):
    vr.grupos = [{"codigo": 1, "nome": "X", "regimeTributario": "LUCRO REAL", "lojas": []}]
    result = integration.send("01234567000195")
    self.assertFalse(result.success)
    self.assertIn("grupo econômico", result.message)
    self.assertEqual([], api.sent_batches)

def test_send_stops_when_store_has_no_uf(self):
    integration.store_lookup = lambda cnpj: {"nome": "Loja Centro", "cnpj": cnpj, "uf": None}
    result = integration.send("01234567000195")
    self.assertFalse(result.success)
    self.assertIn("Informe a UF da loja Loja Centro", result.message)
    self.assertEqual([], vr.calls)  # nenhuma chamada à VR

def test_send_with_no_valid_products_does_not_call_api(self):
    vr.products = [product_without_store_uf()]
    result = integration.send("01234567000195")
    self.assertFalse(result.success)
    self.assertEqual("Nenhum produto válido para envio.", result.message)
    self.assertEqual([], api.sent_batches)

def test_factory_creates_vr_integration(self):
    # DatabaseManager temporário com set_erp_type("vr"), save_vr_config, save_oriontax_api_config
    self.assertIsInstance(create_integration(db, "vr"), VrIntegration)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_vr_integration -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `send`**

Fluxo dentro de `SyncLockRegistry.acquire(self.installation_id)`: `uf = self._store_uf(cnpj)` → progresso "Conectando à API VR..." → `list_grupos_economicos()` → `build_store_context(cnpj, uf, grupos)` (o `ValueError` vira `SyncResult(False, msg)`) → progresso com nome do grupo e regime → `list_products(ctx.cnpj, cancel_check)` → mapear com `vr_product_to_api(p, ctx, date.today())` acumulando rejeições → mesmo bloco de avisos, lotes e mensagem final de `SysmoIntegration.send` (copiar a forma, inclusive os limites 20/100 de rejeições exibidas/guardadas). Erros `VrApiError` propagam como na Sysmo (o chamador registra).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_vr_integration -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/integrations/vr/ core/integrations/factory.py core/integrations/profiles.py tests/test_vr_integration.py
git commit -m "feat: envia produtos da VR para a API OrionTax"
```

---

### Task 5: Montagem da correção (OrionTax → item do PATCH VR)

**Files:**
- Create: `core/integrations/vr/correction.py`
- Test: `tests/test_vr_correction.py`

**Interfaces:**
- Consumes: `VrStoreContext`, `ICMS_SCENARIO`, `regime_block`, `digits`, `pick_classificacao`, `parse_percent` (Task 3).
- Produces (`core.integrations.vr.correction`):
  - `class CorrectionRejected(ValueError)` — mensagem `"Produto <codigo>: <motivo>"`.
  - `ICMS_SCENARIOS = ("icmsDebito", "icmsCredito", "icmsDebitoInterestadual", "icmsCreditoInterestadual", "icmsConsumidorFinal", "icmsBeneficioGoias")`
  - `@dataclass class VrCatalogs: icms: List[dict]; piscofins: List[dict]; pautas: List[dict]; classificacoes: List[dict]`
  - `format_ncm(value) -> str` (8 dígitos → `####.##.##`, senão `CorrectionRejected`), `format_cest(value) -> str` (7 dígitos → `##.###.##`, vazio → `""`).
  - `resolve_icms_id(values: dict, catalog: List[dict]) -> Optional[int]` — `codigo` do cadastro com `cst`, `csosn`, `percentual`, `percentualReducao`, `percentualDiferimento`, `percentualFCP` iguais (números com tolerância 0.001; `None`/`""` equivalem a 0/vazio).
  - `resolve_piscofins_id(cst: int, pis: float, cofins: float, regime: str, catalog: List[dict]) -> Optional[int]` — cadastro de saída (`tipoOperacao` em maiúsculas começa com `"S"` ou contém `"DEB"`), mesmo `cst`, `pis`/`cofins` do bloco do regime.
  - `build_correction(current: Optional[dict], target: dict, ctx: VrStoreContext, catalogs: VrCatalogs) -> Optional[dict]` — item do `PATCH /v2/integracaofiscal`, ou `None` quando o alvo já é igual ao estado atual.
  - `build_vinculos(pairs: List[Tuple[dict, dict]], ctx: VrStoreContext, catalogs: VrCatalogs, today: date) -> Tuple[List[dict], List[str]]` — `pairs` = `(current, target)`; devolve corpos do `/classificacaoTributaria/vincular` e mensagens de rejeição.

Regras de `build_correction` (spec VR seções 12 e 13.1; envia sempre o produto completo, porque campos omitidos podem ser zerados):
- `current is None` → `CorrectionRejected("não encontrado ou inativo na loja VR")`; `target["codigo"]` não numérico → `CorrectionRejected("código não numérico")`.
- `codigoProduto=int(current["codigo"])`, `estados=[ctx.uf]`, `gruposEconomicos=[ctx.grupo_codigo]`.
- `classificacaoFiscal`: `ncm=format_ncm(target["ncm"])`, `cest=format_cest(target["cest"])`, `exTIPI` do atual.
- `aliquotas`: os seis cenários do item `uf == ctx.uf` do atual, cada um com `idAliquota` resolvido quando houver; sem item da UF → rejeita. Sobre `icmsConsumidorFinal` aplicar o alvo: código de 3 dígitos vai em `csosn` (e `cst=""`), senão `cst=str(icms_cst).zfill(2)`; `percentual=icms_aliquota`; `percentualReducao` = `target["percentual_redbcde"]` se presente, senão `round((1 - icms_aliquota_reduzida / icms_aliquota) * 100, 2)` quando ambos > 0, senão 0; `percentualFCP=protege`; `cBenef=cbenef or ""`; demais campos do atual. Se `resolve_icms_id` não achar cadastro para esse cenário → `CorrectionRejected("sem cadastro de ICMS compatível em /icms (CST x, y%); crie no VRMaster")`.
- `pautaFiscal`: a do atual, com os três ICMS resolvidos como acima (sem id → só valores), `valorPercentual = tipoValor == "Percentual"` da pauta de `catalogs.pautas` com mesmo NCM (dígitos), ausente → `False`; sem `idPauta` (spec VR seção 15).
- `pisCofins`: item do atual com `grupoEconomico == ctx.grupo_nome` (ausente → rejeita). `pisCofinsEntrada` = `credito` do atual (`idPisCofins=credito["codigo"]`, valores do bloco do regime, `percentualReducao=reducao`). `pisCofinsSaida` com `cst=int(target["pis_cst"])`, `pis`, `cofins` do alvo, `naturezaReceita=target["natureza_receita"] or 0`; `idPisCofins` = `debito["codigo"]` se cst/pis/cofins iguais ao atual, senão `resolve_piscofins_id`; sem cadastro → rejeita. `pis_cst` nulo no alvo → mantém a saída atual.
- `regraFiscal` nunca é enviada.
- `None` quando NCM, CEST, `icmsConsumidorFinal` (cst/csosn, percentual, redução, FCP, cBenef) e PIS/COFINS de saída (cst, pis, cofins, natureza) do alvo já são iguais aos do atual.

Regras de `build_vinculos`: só pares cujo alvo tem `cst_ibs_cbs` e `c_class_trib` e difere de `pick_classificacao(current["classificacaoTributaria"], today)`; procurar em `catalogs.classificacoes` o item com `cst == str(..).zfill(3)` e `cClassTrib == str(..).zfill(6)` → `codigo`; sem cadastro → mensagem de rejeição (a API não cria classificações). Agrupar por `codigo`: `{"codigoClassificacaoTributaria": codigo, "codigoProdutos": [...], "cnpj": int(ctx.cnpj), "observacao": "OrionTax Sync"}`. Não enviar `reducaoPercentual`/`diferimentoPercentual` (gravariam na classificação, compartilhada por outros produtos).

- [ ] **Step 1: Write the failing tests**

Reaproveitar a fixture `vr_product()` e `CTX` de `tests/test_vr_mapper.py` (importar dela). Catálogos: `icms = [{"codigo": 7, "cst": "20", "csosn": "", "percentual": 19, "percentualReducao": 26.32, "percentualDiferimento": 0, "percentualFCP": 2}, {"codigo": 8, "cst": "00", "csosn": "", "percentual": 19, "percentualReducao": 0, "percentualDiferimento": 0, "percentualFCP": 2}]`, `piscofins = [{"codigo": 3, "cst": 1, "tipoOperacao": "SAIDA", "tributacaoLucroReal": {"pis": 1.65, "cofins": 7.6}}, {"codigo": 4, "cst": 4, "tipoOperacao": "SAIDA", "tributacaoLucroReal": {"pis": 0, "cofins": 0}}]`, `classificacoes = [{"codigo": 55, "cst": "000", "cClassTrib": "000001"}]`. Fixture `debito`/`credito` do produto com `codigo` 3 e 9.

```python
def test_unchanged_target_returns_none(self):
    target = vr_product_to_api(vr_product(), CTX, TODAY)
    self.assertIsNone(build_correction(vr_product(), target, CTX, CATALOGS))

def test_overlays_consumer_icms_and_resolves_id(self):
    target = vr_product_to_api(vr_product(), CTX, TODAY) | {"icms_cst": 0, "percentual_redbcde": 0}
    item = build_correction(vr_product(), target, CTX, CATALOGS)
    cf = item["aliquotas"]["icmsConsumidorFinal"]
    self.assertEqual(("00", 19.0, 0, 8), (cf["cst"], cf["percentual"], cf["percentualReducao"], cf["idAliquota"]))
    self.assertEqual(("00", 19), (item["aliquotas"]["icmsDebito"]["cst"], item["aliquotas"]["icmsDebito"]["percentual"]))  # cenário não alvo preservado
    self.assertEqual((86922, ["GO"], [1]), (item["codigoProduto"], item["estados"], item["gruposEconomicos"]))
    self.assertEqual("1901.90.00", item["classificacaoFiscal"]["ncm"])
    self.assertEqual("17.004.00", item["classificacaoFiscal"]["cest"])
    self.assertNotIn("regraFiscal", item)

def test_derives_reduction_from_reduced_rate_when_absent(self):
    target = {**vr_product_to_api(vr_product(), CTX, TODAY), "icms_aliquota_reduzida": 14.0}
    target.pop("percentual_redbcde")
    # 1 - 14/19 = 26.32%
    self.assertIsNone(build_correction(vr_product(), target, CTX, CATALOGS))

def test_rejects_when_no_compatible_icms_cadastro(self):
    target = vr_product_to_api(vr_product(), CTX, TODAY) | {"icms_aliquota": 17.0}
    with self.assertRaisesRegex(CorrectionRejected, "Produto 86922: sem cadastro de ICMS"):
        build_correction(vr_product(), target, CTX, CATALOGS)

def test_resolves_new_pis_cofins_saida_and_keeps_entrada(self):
    target = vr_product_to_api(vr_product(), CTX, TODAY) | {"pis_cst": "04", "pis_aliquota": 0, "cofins_aliquota": 0}
    item = build_correction(vr_product(), target, CTX, CATALOGS)
    self.assertEqual((4, 4), (item["pisCofins"]["pisCofinsSaida"]["idPisCofins"], item["pisCofins"]["pisCofinsSaida"]["cst"]))
    self.assertEqual(9, item["pisCofins"]["pisCofinsEntrada"]["idPisCofins"])

def test_rejects_product_missing_in_store(self):
    with self.assertRaisesRegex(CorrectionRejected, "não encontrado"):
        build_correction(None, {"codigo": "1", "ncm": "19019000"}, CTX, CATALOGS)

def test_rejects_non_numeric_code(self):
    with self.assertRaisesRegex(CorrectionRejected, "não numérico"):
        build_correction(vr_product(), {"codigo": "ABC", "ncm": "19019000"}, CTX, CATALOGS)

def test_rejects_invalid_ncm(self):
    target = vr_product_to_api(vr_product(), CTX, TODAY) | {"ncm": "1901"}
    with self.assertRaises(CorrectionRejected):
        build_correction(vr_product(), target, CTX, CATALOGS)

def test_csosn_target_goes_to_csosn_field(self):
    catalogs = replace(CATALOGS, icms=CATALOGS.icms + [{"codigo": 11, "cst": "", "csosn": "102", "percentual": 19,
                                                         "percentualReducao": 26.32, "percentualDiferimento": 0, "percentualFCP": 2}])
    target = vr_product_to_api(vr_product(), CTX, TODAY) | {"icms_cst": 102}
    cf = build_correction(vr_product(), target, CTX, catalogs)["aliquotas"]["icmsConsumidorFinal"]
    self.assertEqual(("", "102", 11), (cf["cst"], cf["csosn"], cf["idAliquota"]))

def test_build_vinculos_groups_by_classification(self):
    t = lambda code: {"codigo": str(code), "cst_ibs_cbs": "000", "c_class_trib": "1"}
    p1, p2 = vr_product(), {**vr_product(), "codigo": 86923}
    bodies, rejected = build_vinculos([(p1, t(86922)), (p2, t(86923))], CTX, CATALOGS, TODAY)
    self.assertEqual([{"codigoClassificacaoTributaria": 55, "codigoProdutos": [86922, 86923],
                       "cnpj": 1234567000195, "observacao": "OrionTax Sync"}], bodies)
    self.assertEqual([], rejected)

def test_build_vinculos_skips_unchanged_and_reports_unknown(self):
    same = {"codigo": "86922", "cst_ibs_cbs": "200", "c_class_trib": "200003"}
    unknown = {"codigo": "86922", "cst_ibs_cbs": "410", "c_class_trib": "410999"}
    self.assertEqual(([], []), build_vinculos([(vr_product(), same)], CTX, CATALOGS, TODAY))
    bodies, rejected = build_vinculos([(vr_product(), unknown)], CTX, CATALOGS, TODAY)
    self.assertEqual([], bodies); self.assertIn("410999", rejected[0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_vr_correction -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `core/integrations/vr/correction.py`** conforme as regras acima.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_vr_correction tests.test_vr_mapper -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/integrations/vr/correction.py tests/test_vr_correction.py
git commit -m "feat: monta correcoes fiscais da OrionTax para o PATCH da VR"
```

---

### Task 6: `VrIntegration.receive`

**Files:**
- Modify: `core/integrations/vr/integration.py`
- Test: `tests/test_vr_integration.py`

**Interfaces:**
- Consumes: `OrionTaxApiClient.receive_products()`, `VrApiClient.list_*`, `patch_integracao_fiscal`, `vincular_classificacao` (Task 2), `build_store_context` (Task 3), `VrCatalogs`, `build_correction`, `build_vinculos`, `CorrectionRejected` (Task 5).
- Produces: `VrIntegration.receive(cnpj, progress_callback=None) -> SyncResult` com `details` = `{"rejected_count", "rejected" (≤100), "unchanged", "patch_status": {status: quantidade}, "patch_info": [primeiros 100 itens não "sucesso"], "vinculos": [detalhes], "divergences": [≤100]}`.

Fluxo, dentro de `SyncLockRegistry.acquire`:
1. `uf = self._store_uf(cnpj)`; depois "Recebendo fotografia tributada da API OrionTax..." → `self.api.receive_products()` (o GET da OrionTax muda o estado dos itens, então ele só roda depois de validar a UF).
2. Contexto da loja (como no `send`, inclusive `_store_uf` antes de receber da OrionTax, para não consumir a fotografia de uma loja sem UF) e catálogos: `list_icms(ctx.uf)`, `list_piscofins()`, `list_pautas_fiscais(ctx.uf)`, `list_classificacoes(ctx.cnpj)`; estado atual: `list_products(ctx.cnpj)` indexado por `str(codigo)` (uma leitura paginada, não um GET por produto).
3. Para cada produto recebido: `build_correction(current_by_code.get(codigo), target, ctx, catalogs)` → lista de itens, contagem de inalterados, rejeições (`CorrectionRejected`). Depois `build_vinculos` só com os pares não rejeitados.
4. Avisos de rejeição no mesmo formato do `send`. Aviso único de escopo: `f"⚠ A correção vale para todas as lojas da UF {uf} e do grupo {grupo_nome}."` (spec VR 13.1, passo 5).
5. `self.dry_run` → registrar no progresso o JSON dos 3 primeiros itens e do primeiro vínculo e devolver `SyncResult(True, f"[DRY-RUN] {n} correção(ões) e {v} vínculo(s) montados; nada foi gravado na VR.", n, details=...)` sem chamar PATCH.
6. PATCH em lotes de `self.vr.patch_batch_size`, progresso "Gravando lote i/N na VR...". Contar `status` de cada item de `integracaoFiscal[]` (valores não documentados: guardar todos; considerar sucesso apenas status cujo texto em maiúsculas contenha `"SUCESSO"` ou seja `"OK"`, o resto vai para `patch_info`). Depois cada corpo de vínculo.
7. Verificação: nova `list_products(ctx.cnpj)`; para cada `codigoProduto` gravado, comparar NCM e `cst`/`csosn`/`percentual` de `icmsConsumidorFinal` da UF com o enviado; diferenças em `divergences`.
8. Mensagem: `f"{ok} produto(s) gravado(s) na VR, {inalterados} sem alteração, {rejeitados} rejeitado(s)."` + `f" {d} divergência(s) na releitura."` quando houver; `success = (falhas de status + divergências) == 0`.

- [ ] **Step 1: Write the failing tests**

Stubs como na Task 4, com `receive_products` devolvendo alvos derivados de `vr_product_to_api` com alterações controladas e `patch_integracao_fiscal` registrando lotes.

```python
def test_receive_patches_only_changed_products_in_batches(self):
    # 3 alvos alterados, 1 igual, 1 com código inexistente na loja; patch_batch_size = 2
    result = integration.receive(CNPJ, progress.append)
    self.assertEqual([2, 1], [len(b) for b in vr.patch_calls])
    self.assertEqual(1, result.details["unchanged"])
    self.assertEqual(1, result.details["rejected_count"])
    self.assertTrue(any("todas as lojas da UF GO" in m for m in progress))

def test_receive_dry_run_does_not_write(self):
    integration.dry_run = True
    result = integration.receive(CNPJ, progress.append)
    self.assertEqual([], vr.patch_calls); self.assertEqual([], vr.vincular_calls)
    self.assertTrue(result.message.startswith("[DRY-RUN]"))

def test_receive_reports_item_failures_from_patch(self):
    # patch devolve status "ERRO" para um item
    result = integration.receive(CNPJ)
    self.assertFalse(result.success)
    self.assertEqual(1, result.details["patch_status"]["ERRO"])

def test_receive_reports_divergence_on_reread(self):
    # segunda list_products devolve o produto ainda com o ICMS antigo
    result = integration.receive(CNPJ)
    self.assertFalse(result.success)
    self.assertEqual(1, len(result.details["divergences"]))

def test_receive_sends_vinculos(self):
    # alvo com cst_ibs_cbs/c_class_trib novos e cadastrados
    integration.receive(CNPJ)
    self.assertEqual(55, vr.vincular_calls[0]["codigoClassificacaoTributaria"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_vr_integration -v`
Expected: FAIL (`NotImplementedError`).

- [ ] **Step 3: Implement `receive`** conforme o fluxo acima.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s tests`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add core/integrations/vr/integration.py tests/test_vr_integration.py
git commit -m "feat: grava na VR a tributacao recebida da API OrionTax"
```

---

### Task 7: Interface, agendador e documentação

**Files:**
- Modify: `gui/settings.py` (novo `VrConfigDialog`), `gui/client_dialog.py` (campo UF), `gui/main_window.py` (menu ERP, aba Configurações, status, `execute_operation`, `WorkerThread.run`), `core/scheduler.py` (`_execute_scheduled_sync` e `_execute_sync_for_client`), `CHANGELOG.md`
- Test: `tests/test_vr_integration.py` (só o teste do roteamento do scheduler)

**Interfaces:**
- Consumes: `get_vr_config`/`save_vr_config` (Task 1), `VrApiClient.info`/`authenticate` (Task 2), `create_integration(db, "vr")` (Task 4), `ERP_PROFILES["vr"]`.
- Produces: `VrConfigDialog(parent)` em `gui/settings.py`.

- [ ] **Step 1: Write the failing test**

```python
def test_scheduler_routes_vr_through_integration(self):
    # DatabaseManager temporário com erp vr configurado; patch de core.integrations.create_integration
    # devolvendo um fake com send() -> SyncResult(True, "ok", 3)
    scheduler._execute_sync_for_client("ENVIAR", vr_cfg, api_cfg, CNPJ, "Loja", "vr")
    fake.send.assert_called_once()
    # e um log SUCESSO com registros=3 em logs_execucao
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_vr_integration -v`
Expected: FAIL (scheduler cai no fluxo Intersolid).

- [ ] **Step 3: Implement the wiring**

- `core/scheduler.py`: config `get_vr_config()` + `get_oriontax_api_config()` quando `erp_type == 'vr'`; o limite de um cliente e o desvio para `create_integration(self.db_manager, erp_type)` passam a valer para `erp_type in ('sysmo', 'vr')`.
- `gui/main_window.py`: `WorkerThread.run` e `execute_operation` com o mesmo `in ('sysmo', 'vr')` e `create_integration(self.db_manager, self.erp_type)`; menu `ERP` passa a ter três ações marcáveis num `QActionGroup` exclusivo, geradas de `ERP_PROFILES` na ordem `intersolid`, `vr`, `sysmo` (rótulos `Intersolid`, `VR`, `Sysmo`), com a do perfil ativo marcada (`setChecked`); clicar em outra chama `change_erp_profile(erp_type)` e, se o usuário cancelar a confirmação ou houver sync em andamento, a marcação volta para o perfil ativo. O título da janela já mostra o ERP (`OrionTax Sync 2.0 - VR`); na aba Configurações, para `vr`, grupo `'Configuração VR e API OrionTax'` com `'⚙️ Configurar API VR'` (`open_vr_config`) e `'⚙️ Configurar API OrionTax'`; `check_connection_status` mostra `✓ API VR: {base_url}` ou `✗ API VR: Não configurada`; o combo de clientes mostra a UF junto do nome quando preenchida (`Loja Centro - GO - 01.234.567/0001-95`).
- `gui/client_dialog.py`: combo `UF:` abaixo do CNPJ, com item vazio `—` seguido de `UFS` (Task 1); `load_cliente` seleciona a UF salva; `save_cliente` passa a UF (ou `None` para `—`) a `create_cliente`/`update_cliente`. Quando `db_manager.get_installation()["erp_type"] == "vr"`, UF vazia bloqueia o salvar com `'Informe a UF da loja (obrigatória para a integração VR).'`.
- `gui/settings.py` `VrConfigDialog`: campos URL base (placeholder `http://servidor:9025`), Token VRMaster (password), Timeout (5–300, 60), Itens por página (1–5000, 500), Produtos por PATCH (1–500, 50). Validação: URL começa com `http://` ou `https://`, token obrigatório. Botão Testar: `VrApiClient(valores).info()` e `.authenticate()`; sucesso mostra `servico major.minor.release`. O token salvo não é exibido; campo vazio ao editar mantém o token atual (passar o atual de `get_vr_config()`).
- `CHANGELOG.md`: entrada "Integração VR (VRMaster): envio para a API OrionTax e gravação via PATCH /v2/integracaofiscal".

- [ ] **Step 4: Run tests and smoke-check the GUI**

Run: `python3 -m unittest discover -s tests` → Expected: OK.
Run: `python3 main.py`; o menu ERP mostra Intersolid, VR e Sysmo com o ativo marcado; escolher VR, cancelar a confirmação (a marca volta ao ativo), escolher de novo, confirmar e reiniciar: VR aparece marcado e no título; a aba Configurações mostra o grupo VR, o diálogo salva e reabre com os valores (sem o token), e o status mostra `✓ API VR`. Em Clientes, editar uma loja, escolher GO, salvar e reabrir: GO continua selecionado; com UF `—`, salvar é bloqueado no perfil VR.

- [ ] **Step 5: Commit**

```bash
git add gui/settings.py gui/main_window.py core/scheduler.py CHANGELOG.md tests/test_vr_integration.py
git commit -m "feat: liga o perfil VR na interface e no agendador"
```

---

## Homologação (após a Task 7, com um cliente VR real)

Não é task de código: é o roteiro para fechar os pontos da seção 15 da spec VR antes de liberar o `receive` sem dry-run.

A gravação na VR nasce travada: enquanto "Permitir gravação na VR (somente após homologação)" estiver desmarcado em Configurar API VR, o `BUSCAR` sem dry-run para antes de chamar a OrionTax (a fotografia não é consumida). Cada `BUSCAR` que chega à OrionTax salva a fotografia recebida em `<pasta do banco>/vr_snapshots/receive-<data-hora>-<cnpj>.json`.

1. `ENVIAR` normal; conferir na OrionTax 5 produtos contra a tela de tributação do VRMaster (UF da loja, cenário consumidor final, PIS/COFINS do grupo).
2. `ORIONTAX_DRY_RUN=1` + `BUSCAR`; revisar os JSON registrados. Atenção: o dry-run consome a fotografia da OrionTax (o GET muda o estado dos itens no servidor); ela fica salva em `vr_snapshots`, mas é preciso pedir à OrionTax o reenvio antes da gravação real.
3. Teste de um único produto: marcar "Permitir gravação na VR" e rodar o `BUSCAR` com `ORIONTAX_VR_ONLY=<código de teste>` (lista separada por vírgula); só esse produto vira PATCH/vínculo, os demais são contados como fora da lista e não são gravados. Responder: campos omitidos são mantidos? sem `idPauta` a pauta é preservada? `status` real de `integracaoFiscal[]`? o PIS/COFINS gravado foi no regime do grupo?
4. Reenviar o mesmo payload (idempotência) e testar um produto CST 61, ainda com `ORIONTAX_VR_ONLY`.
5. Registrar as respostas na seção 15 da spec VR e ajustar `correction.py` se alguma hipótese cair.
6. Remover `ORIONTAX_VR_ONLY` (e pedir novo reenvio à OrionTax, se a fotografia já tiver sido consumida) para liberar a gravação completa.
