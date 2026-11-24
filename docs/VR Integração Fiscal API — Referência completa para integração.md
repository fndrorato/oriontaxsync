# VR Integração Fiscal API — Referência completa para integração

Nov 24, 2026 · @Fernando

## 1. Visão geral

A VR Integração Fiscal API (versão 4.5.7, OpenAPI 3.0.3) lê e corrige a tributação dos produtos cadastrados no VRMaster. Ela roda dentro da rede do cliente, como serviço Docker ao lado do VRMaster, e responde em HTTP sem TLS na porta 9025 (padrão da coleção Postman) ou 9010 (padrão do YAML de referência).

Tudo neste documento vem da especificação OpenAPI publicada pela VR e da página de instalação da base de conhecimento (links em Fontes, no fim). O que a especificação não define está marcado como ponto a validar na seção 15.

**Como o VRMaster guarda a tributação.** A API espelha o modelo do ERP, e entendê-lo evita a maior parte dos erros de integração:

| Dado fiscal | Onde fica guardado | Consequência para a integração |
| --- | --- | --- |
| NCM, CEST, Ex-TIPI, descrição, EAN | No produto | Vale para todas as lojas |
| ICMS (débito, crédito, interestadual, consumidor final, benefício GO) | No produto, por UF | Uma correção de ICMS em SP vale para todas as lojas de SP |
| Pauta fiscal / ST (MVA, MVA ajustada) | No produto, por UF | Mesmo escopo do ICMS |
| PIS/COFINS (entrada e saída) | No produto, por grupo econômico | Uma correção vale para todas as lojas do grupo |
| Classificação tributária da reforma (CST IBS/CBS, cClassTrib) | No produto ou no NCM, por loja (CNPJ) | Único dado gravado loja a loja |

**Grupo econômico** é o agrupamento de lojas que compartilham o mesmo perfil fiscal federal: regime tributário (Lucro Real, Lucro Presumido), CNAE, natureza jurídica e periodicidade de apuração. As lojas herdam do grupo as características fiscais.

**Leitura e gravação usam formatos diferentes.** A leitura (`GET /v3/produtos`) é filtrada por CNPJ e devolve listas: ICMS por UF e PIS/COFINS por grupo econômico. A gravação (`PATCH /v2/integracaofiscal`) não recebe CNPJ: recebe um objeto de alíquotas e as listas `estados` e `gruposEconomicos` onde ele deve ser aplicado. A seção 13 detalha a conversão.

## 2. Acesso, autenticação e respostas

Para chamar a API são necessários três itens: o módulo licenciado pela VR, o serviço ativo no Service Manager e um token gerado no VRMaster.

### 2.1 Licenciamento e instalação

1. **Liberação comercial:** o cliente ou parceiro pede à VR Software a ativação do módulo de Integração Fiscal. A licença é processada no VRGestor e o serviço fica habilitado para a unidade, sem alteração manual no banco.
2. **Instalação:** no servidor com VR Ubuntu configurado, a pasta `~/.vr` precisa conter `servicecontainer/service/VRIntegracaoFiscalAPI.war`, `servicemanager/service/`, `docker-compose-sm.yml` e `vr.properties`. O ambiente sobe com `docker-compose -f ~/.vr/docker-compose-sm.yml up -d` e cria os containers vrredis, vrrabbitmq, vrservicecontainer e vrservicemanager.
3. **Ativação:** no painel do VR Service Manager, o serviço **VRIntegracaoFiscalAPI** é ativado pelo botão Ativar.
4. **Token:** no VRMaster, menu Sistema > API, cadastra-se a API para a unidade. O sistema exibe o token (o campo `tokenVRMaster` da autenticação).

### 2.2 Autenticação

`POST /auth` troca o token do VRMaster por um Bearer Token (JWT) válido por 24 horas. É a única rota de negócio sem autenticação.

```json
{"auth": {"tokenVRMaster": "507040e2f80589b61b047b9839251fa8"}}
```

| Campo | Tipo | Obrigatório | Descrição |
| --- | --- | --- | --- |
| `auth` | objeto | Sim | Envelope das credenciais |
| `auth.tokenVRMaster` | string | Sim | Token do produto VRIntegração Fiscal API cadastrado no VRMaster |

Resposta 200: `{"retorno": ["eyJhbGciOi..."]}`. O primeiro item de `retorno` é o token. Todas as demais chamadas levam o cabeçalho `Authorization: Bearer <token>`, com um único espaço após Bearer.

### 2.3 Envelope das respostas

As respostas de negócio seguem um envelope comum. A chave que carrega os dados muda por endpoint.

| Campo | Tipo | Descrição |
| --- | --- | --- |
| `dataHora` | string `dd/MM/yyyy HH:mm:ss` | Momento em que o processamento terminou, ex. 08/03/2022 13:06:22 |
| `info` | string | Mensagem curta sobre o resultado do processamento |
| chave de dados | lista ou objeto | `produtos`, `icms`, `pisCofins`, `pautasFiscais`, `grupoEconomico`, `integracaoFiscal`, `detalhes` ou `retorno`, conforme o endpoint |

Os exemplos da especificação mostram `{"retorno": []}` em quase todos os endpoints, enquanto os schemas nomeiam chaves específicas. O formato real precisa ser confirmado na primeira chamada (seção 15).

### 2.4 Códigos HTTP documentados

| Código | Quando ocorre |
| --- | --- |
| 200 | Sucesso. Em `/v3/produtos`, também quando a loja não tem produtos no filtro (lista vazia). Em `/classificacaoTributaria/vincular`, também em sucesso parcial |
| 400 | CNPJ que não corresponde a uma loja ativa, em `/v3/produtos` e `/v3/produtos/{id}` |
| 401 | Token ausente ou expirado (esperado pelo esquema `bearerAuth`; a especificação não lista o código) |
| 404 | Produto inexistente na loja informada, em `/v3/produtos/{id}` |

### 2.5 Formatos de dados

| Dado | Formato na API | Exemplo |
| --- | --- | --- |
| Datas de cadastro e vigência | `dd/MM/yyyy` | 13/06/2021 |
| Datas do cadastro de cBenef | `yyyy-MM-dd` (ISO) | 2023-03-10 |
| NCM | `####.##.##` ou 8 dígitos (o vincular aceita os dois) | 1901.90.00 |
| CEST | `##.###.##` | 17.004.00 |
| CNPJ | 14 dígitos sem máscara; string na consulta, inteiro nos retornos | 22881305000192 |
| Percentuais | número decimal (double), em pontos percentuais | 18 = 18% |
| Percentuais da classificação tributária (leitura) | string formatada | "60%" |
| Flags da classificação tributária | `S` ou `N` | S |

## 3. Catálogo de endpoints

A API tem 22 operações. Para ler e corrigir produtos, use as versões atuais: `/v3/produtos` na leitura e `/v2/integracaofiscal` na gravação.

| Método e rota | Finalidade | Parâmetros | Situação |
| --- | --- | --- | --- |
| `GET /` | Versionamento da API | — | Ativo, sem autenticação |
| `GET /info` | Versionamento da API (serviço, major, minor, release, build, beta, data) | — | Ativo, sem autenticação |
| `GET /swagger-ui/index.html` | Swagger UI, verificação de disponibilidade | — | Ativo, sem autenticação |
| `POST /auth` | Emite o Bearer Token de 24 h | corpo `auth.tokenVRMaster` | Ativo, sem autenticação |
| `GET /v3/produtos` | Lista paginada da tributação completa dos produtos ativos na loja, com IBS/CBS | `cnpj` (obrigatório), `usaPaginacao`, `numeroPagina`, `itensPorPagina`, `dataAlteracao` | **Recomendado** |
| `GET /v3/produtos/{id}` | Tributação completa de um produto na loja | `id` (path), `cnpj` (obrigatório) | **Recomendado** |
| `GET /v2/produtos` | Lista com classificação da reforma, CNPJ opcional | `usaPaginacao`, `numeroPagina`, `itensPorPagina`, `dataAlteracao`, `cnpj` | Depreciado |
| `GET /v2/produtos/{id}` | Um produto, versão 2 | `id`, `cnpj` | Depreciado |
| `GET /produtos` | Lista básica (NCM, CEST, ICMS, PIS/COFINS), sem CNPJ e sem reforma | `usaPaginacao`, `numeroPagina`, `itensPorPagina`, `dataAlteracao` | Depreciado |
| `GET /produtos/{id}` | Um produto, versão 1 | `id` | Depreciado |
| `GET /icms` | Cadastros de ICMS ativos; com `uf`, só os vinculados a produtos daquela UF | `uf` | Ativo |
| `GET /icms/estadosOperantes` | UFs que têm cadastro de ICMS vinculado | — | Ativo |
| `GET /piscofins` | Cadastros de PIS/COFINS ativos | — | Ativo |
| `GET /pautasfiscais` | Pautas fiscais (ST) ativas da UF | `uf` | Ativo |
| `GET /gruposeconomicos` | Grupos econômicos, dados fiscais e lojas vinculadas | — | Ativo |
| `GET /IbsCbs` | Alíquotas de CBS, IBS estadual e IBS municipal por UF, com vigência | — | Ativo |
| `GET /classificacaoTributaria` | Classificações da reforma vinculadas a produto e/ou NCM, por loja | `cnpj`, `idProduto`, `ncm` | Ativo |
| `PATCH /classificacaoTributaria/vincular` | Vincula produtos e/ou NCMs a uma classificação tributária, na loja do CNPJ | corpo (seção 9.4) | Ativo, **grava** |
| `POST /cBenef/new` | Cadastra códigos de benefício fiscal por UF | corpo (seção 11.4) | Ativo, **grava** |
| `PATCH /v2/integracaofiscal` | Corrige NCM, CEST, ICMS, pauta, PIS/COFINS e regra fiscal de uma lista de produtos | corpo (seção 12) | **Recomendado**, **grava** |
| `PATCH /integracaofiscal` | Mesma correção, versão 1 | corpo igual ao v2 | Depreciado, **grava** |
| `DELETE /regrafiscal/{id}` | Remove uma regra fiscal do produto na UF | `id` (path), cabeçalhos `uf` e `codigoProduto` (obrigatórios) | Ativo, **grava** |

As versões depreciadas de produto diferem da v3 assim: a v1 não filtra por CNPJ nem traz dados da reforma; a v2 filtra por CNPJ de forma opcional e traz a classificação da reforma de forma menos completa.

## 4. Produto: identificação

Cada produto da leitura v3 traz quatro campos de identificação e quatro blocos fiscais. O código interno do VRMaster (`codigo`) é a chave usada em todas as gravações.

### 4.1 Estrutura do produto (`GET /v3/produtos`)

```
produtos[]
├── codigo                 identificação (esta seção)
├── descricao
├── codigosBarras[]
├── dataAlteracao
├── classificacaoFiscal     NCM, CEST, Ex-TIPI (seção 5)
├── aliquotas[]             ICMS e pauta fiscal, um item por UF (seções 6 e 7)
├── pisCofins[]             PIS/COFINS, um item por grupo econômico (seção 8)
└── classificacaoTributaria[]  IBS/CBS da reforma (seção 9)
```

### 4.2 Campos de identificação

| Campo | Tipo | Descrição | Exemplo | Gravável pela API |
| --- | --- | --- | --- | --- |
| `codigo` | inteiro (int64) | Id do cadastro do produto no banco do VRMaster. Na gravação chama-se `codigoProduto` | 86922 | Não (é a chave) |
| `descricao` | string | Descrição do produto | Desinfetante | Não |
| `codigosBarras` | lista de inteiros (int64) | Códigos de barras (EAN/GTIN) vinculados ao produto. Um produto pode ter vários | \[7891234567895\] | Não |
| `dataAlteracao` | string `dd/MM/yyyy` | Data da última alteração do cadastro do produto | 13/06/2021 | Não (atualizada pelo ERP) |

**EAN como inteiro.** Os códigos de barras vêm como números, não como texto. Zeros à esquerda se perdem: um GTIN-14 que começa com 0 chega com 13 dígitos. Para casar com cadastros externos, normalize com zero-fill até o tamanho do padrão (8, 12, 13 ou 14 dígitos) ou compare como número.

**Descrição e EAN são somente leitura.** A API de integração fiscal não tem campo para alterar descrição, EAN, unidade, preço ou outro dado comercial. Ela só corrige tributação.

### 4.3 Paginação e sincronização

| Parâmetro | Tipo | Obrigatório | Descrição |
| --- | --- | --- | --- |
| `cnpj` | string | Sim | CNPJ da loja, 14 dígitos. Define o escopo: só vêm produtos ativos naquela loja; um produto excluído nela não vem, mesmo se ativo em outra |
| `usaPaginacao` | boolean | Não | Liga a paginação |
| `numeroPagina` | inteiro | Não | Página pedida, a partir de 1 |
| `itensPorPagina` | inteiro | Não | Tamanho da página |
| `dataAlteracao` | string `dd/MM/yyyy` | Não | Filtra por data de última alteração. A especificação não diz se é "igual a" ou "a partir de" (seção 15) |

O filtro de data tem granularidade de dia. Numa sincronização incremental, repita a leitura a partir do último dia processado, inclusive, e descarte os produtos sem mudança comparando um hash do conteúdo.

A especificação não descreve metadados de paginação (total de páginas ou de itens). O fim da lista deve ser detectado por uma página vazia ou menor que `itensPorPagina`.

## 5. Classificação fiscal: NCM, CEST e Ex-TIPI

NCM, CEST e Ex-TIPI ficam no produto e valem para todas as lojas e UFs. São os únicos dados de classificação que a gravação v2 altera diretamente.

| Campo | Tipo | Descrição | Formato e exemplo | Leitura (v3) | Gravação (v2) |
| --- | --- | --- | --- | --- | --- |
| `classificacaoFiscal.ncm` | string | Nomenclatura Comum do Mercosul: classifica a mercadoria e define a base da tributação (TIPI, ST, monofásico, reforma) | `####.##.##`, ex. 1901.90.00 | Sim | Sim |
| `classificacaoFiscal.cest` | string | Código Especificador da Substituição Tributária: identifica mercadorias sujeitas a ST e antecipação de ICMS. Vai na NF-e/NFC-e quando a mercadoria consta do Convênio ICMS 142/18 | `##.###.##`, ex. 17.004.00 | Sim | Sim |
| `classificacaoFiscal.exTIPI` | inteiro (int32) | Exceção da Tabela de Incidência do IPI: código que diferencia alíquota de IPI dentro do mesmo NCM. 0 quando não há exceção | 0 | Sim | Sim |

O NCM aparece também em outros pontos da API:

| Onde | Papel |
| --- | --- |
| `GET /pautasfiscais` → `pautasFiscais[].ncm` | NCM ao qual a pauta fiscal (ST) se aplica |
| `GET /classificacaoTributaria?ncm=` | Filtra classificações da reforma vinculadas àquele NCM |
| `PATCH /classificacaoTributaria/vincular` → `ncms[]` | Vincula a classificação tributária a um NCM inteiro, em vez de produto a produto. Aceita `####.##.##` ou 8 dígitos; NCM sem os três níveis é recusado por formato |
| `classificacaoTributaria[].tipoCadastro` | `NCM` quando a classificação do produto vem do NCM, `PRODUTO` quando vem do próprio produto |

A especificação não diz se a gravação valida o NCM contra a tabela oficial nem se aceita NCM sem pontos no `/v2/integracaofiscal` (seção 15).

## 6. ICMS

O ICMS de cada produto é guardado por UF, em seis cenários de operação. Cada cenário tem o mesmo conjunto de campos (CST/CSOSN, alíquota, redução, FCP, diferimento, cBenef), e o mesmo objeto aparece em três formatos: leitura, gravação e cadastro.

### 6.1 Estrutura por UF

Na leitura, `aliquotas[]` tem um item por UF em que o produto tem tributação:

```
aliquotas[]
├── uf                         AC, AL, … SP, TO e EX (exterior)
├── icmsDebito                 ICMS_Resumo
├── icmsCredito                ICMS_Resumo
├── icmsDebitoInterestadual    ICMS_Resumo
├── icmsCreditoInterestadual   ICMS_Resumo
├── icmsConsumidorFinal        ICMS_Resumo
├── icmsBeneficioGoias         ICMS_Resumo
└── pautaFiscal                Pauta_Fiscal_Resumo (seção 7)
```

Na gravação, `aliquotas` é um único objeto com os mesmos seis cenários, aplicado a todas as UFs da lista `estados` (seção 12).

### 6.2 Os seis cenários

A especificação só descreve o cenário de Goiás. Os outros cinco têm o significado usual da nomenclatura do VRMaster, que deve ser confirmado na tela de tributação do produto durante a homologação.

| Cenário | Operação (interpretação usual) | Documento típico |
| --- | --- | --- |
| `icmsDebito` | Saída interna: venda dentro da UF para contribuinte | NF-e de saída |
| `icmsCredito` | Entrada interna: compra de fornecedor da mesma UF, define o crédito | NF-e de entrada |
| `icmsDebitoInterestadual` | Saída para outra UF | NF-e de saída interestadual |
| `icmsCreditoInterestadual` | Entrada vinda de outra UF (alíquota de 4%, 7% ou 12%) | NF-e de entrada interestadual |
| `icmsConsumidorFinal` | Venda a consumidor final, inclusive no PDV | NFC-e, SAT/MFE, NF-e a consumidor |
| `icmsBeneficioGoias` | Operações com benefício de redução de base de cálculo e crédito outorgado de Goiás (texto da especificação) | NF-e/NFC-e em GO |

### 6.3 Campos de cada cenário

| Campo | Tipo | Descrição | Leitura v3 (`ICMS_Resumo`) | Gravação v2 (`ICMS_Correcao`) | Cadastro `/icms` (`ICMS_Cadastro`) |
| --- | --- | --- | --- | --- | --- |
| `idAliquota` / `codigo` | inteiro | Id do cadastro de alíquota de ICMS. Na gravação, quando informado, a API usa o cadastro com esse código | Não vem | `idAliquota` | `codigo` |
| `cst` | string (2 dígitos) | Código de Situação Tributária do ICMS, regime normal (tabela na seção 14) | Sim, inclui 61 | Sim, **sem 61** no enum | Sim, inclui 61 |
| `csosn` | string (3 dígitos) | Código de Situação da Operação no Simples Nacional | Sim | Sim | Sim |
| `percentual` | número | Alíquota base do ICMS, em % | Sim | Sim | Sim |
| `percentualReducao` | número | Percentual de redução da base de cálculo (CST 20 e 70) | Sim | Sim | Sim |
| `percentualDiferimento` | número | Percentual de diferimento, considerado com CST 51 | Sim | Sim | Sim |
| `percentualFCP` | número | Percentual do Fundo de Combate à Pobreza, varia por UF | Sim | Sim | Sim |
| `aplicaReducaoFCP` | boolean | Se a redução de base também se aplica ao cálculo do FCP | Sim | Sim | Sim |
| `cBenef` | string | Código de Benefício Fiscal da UF (ex. SP999, GO999), obrigatório na NF-e em várias UFs para CST com benefício | Sim | Sim | Não |
| `aliquotaMonofasico` / `aliquotaIcmsMonofasico` | número | Alíquota do ICMS monofásico (combustíveis), considerada só com CST 61 | Não vem | `aliquotaMonofasico` | `aliquotaIcmsMonofasico` |
| `idMotivoDesoneracao` | inteiro | Código do motivo de desoneração do ICMS (campo `motDesICMS` da NF-e) | Não vem | Sim | Não |
| `motivoDesoneracao` | string | Descrição do motivo de desoneração, para CST diferente de 00, 10 e 51 | Não vem | Não | Sim |
| `percentualDesonerado` | número | Percentual desonerado para cálculo do ICMS | Não vem | Não | Sim |
| `percentualIcmsConsumidor` | número | Percentual do ICMS consumidor vinculado ao cadastro | Não vem | Não | Sim |
| `descricao` | string (até 40) | Nome do cadastro de alíquota | Não vem | Não | Sim |
| `mensagem` | string | Mensagem do cadastro de ICMS (texto para informações complementares) | Não vem | Não | Sim |
| `status` | `ATIVO` ou `INATIVO` | Se o cadastro está em uso | Não vem | Não | Sim |

### 6.4 Como o VRMaster relaciona produto e alíquota

No VRMaster, o produto aponta para um cadastro de alíquota de ICMS (tabela consultada em `/icms`). Por isso a gravação aceita `idAliquota`: com ele, a API reaproveita um cadastro existente. A leitura v3, porém, devolve os valores e não o id. Para gravar com segurança, localize o `codigo` em `/icms?uf=` comparando CST, CSOSN, percentual, redução, diferimento e FCP.

O comportamento da gravação sem `idAliquota`, só com os valores, não está documentado: pode localizar um cadastro igual, criar um novo ou recusar (seção 15).

### 6.5 Inconsistência a observar

O enum de CST da gravação não inclui 61, mas o campo `aliquotaMonofasico` da mesma gravação diz que só vale para CST 61. Leitura e cadastro aceitam 61. Antes de corrigir produtos monofásicos, teste se o PATCH aceita CST 61.

## 7. Pauta fiscal e substituição tributária

A pauta fiscal guarda os parâmetros de ICMS-ST e antecipação do produto em cada UF: MVA, MVA ajustada e três cenários de ICMS próprios da ST. Tem o mesmo escopo do ICMS (por UF) e aparece em três formatos.

| Campo | Tipo | Descrição | Leitura v3 (`aliquotas[].pautaFiscal`) | Gravação v2 (`pautaFiscal`) | Cadastro `/pautasfiscais` |
| --- | --- | --- | --- | --- | --- |
| `idPauta` | inteiro | Id da pauta fiscal. Na gravação, quando informado, a API usa a pauta cadastrada com esse código | Não vem | Sim | Não vem (sem id na lista) |
| `ncm` | string | NCM ao qual a pauta se aplica | Não | Não | Sim |
| `mva` | número | Margem de Valor Agregado (índice de valor agregado) usada na base do ICMS-ST | Sim | Sim | Sim |
| `mvaAjustada` | número | MVA ajustada para operações interestaduais, corrigida pela diferença de alíquotas | Sim | Sim | Sim |
| `valorPercentual` / `tipoValor` | boolean / string | Como interpretar MVA e MVA ajustada: valor absoluto ou percentual | Não | `valorPercentual` (boolean) | `tipoValor` ("Absoluto" ou "Percentual") |
| `percentualProdepe` | número | Alíquota base do incentivo do PRODEPE (Programa de Desenvolvimento do Estado de Pernambuco) | Sim | Sim | Sim |
| `recolheIcmsAntecipadamente` | boolean | Se o ICMS é recolhido por antecipação | Sim | Sim | Sim |
| `icmsDebito` | objeto ICMS | ICMS de débito usado no cálculo da ST | `ICMS_Resumo` | `ICMS_Correcao` | `ICMS_Cadastro` |
| `icmsCredito` | objeto ICMS | ICMS de crédito (próprio) abatido no cálculo da ST | `ICMS_Resumo` | `ICMS_Correcao` | `ICMS_Cadastro` |
| `icmsInterestadual` | objeto ICMS | ICMS interestadual usado na ST de entradas de outra UF | `ICMS_Resumo` | `ICMS_Correcao` | `ICMS_Cadastro` |

Os três objetos ICMS da pauta têm exatamente os campos da tabela 6.3, em cada formato.

A leitura v3 não devolve `idPauta` nem `valorPercentual`. Para regravar a pauta sem perder a forma de interpretar o MVA, localize a pauta em `/pautasfiscais?uf=` pelo NCM do produto e use o `tipoValor` dela. Como essa lista também não traz o id, a resolução de `idPauta` fica pendente de validação (seção 15).

## 8. PIS/COFINS

O PIS/COFINS é guardado por grupo econômico, com um cadastro para entrada (crédito) e outro para saída (débito). Cada cadastro traz as alíquotas de Lucro Real e de Lucro Presumido. A alíquota efetiva depende do regime do grupo (`regimeTributario` em `/gruposeconomicos`).

### 8.1 Estrutura na leitura

```
pisCofins[]                       um item por grupo econômico
├── grupoEconomico                NOME do grupo (não o código)
├── naturezaReceita               código da natureza da receita
├── credito                       PIS-COFINS_Cadastro (entrada)
│   ├── codigo, cst, descricao, substituicao, tipoOperacao
│   ├── tipoCreditoTributado, tipoCreditoNaoTributado
│   ├── tributacaoLucroReal       pis, cofins, csa, reducao
│   └── tributacaoLucroPresumido  pis, cofins, csa, reducao
└── debito                        PIS-COFINS_Cadastro (saída), mesmos campos
```

### 8.2 Campos

| Campo | Tipo | Descrição | Leitura v3 | Gravação v2 (`PIS-COFINS_Correcao`) | Cadastro `/piscofins` |
| --- | --- | --- | --- | --- | --- |
| `grupoEconomico` | string | Nome do grupo econômico que adota essa tributação, ex. Lojas Serve Bem | Sim, por item | Não (escopo vai em `gruposEconomicos[]`, por código) | Não |
| `codigo` / `idPisCofins` | inteiro | Id do cadastro de tributação PIS/COFINS. Na gravação, quando informado, a API usa o cadastro com esse código | `credito.codigo`, `debito.codigo` | `idPisCofins` | `codigo` |
| `cst` | inteiro | CST do PIS/COFINS (tabela na seção 14). Saída: 01 a 09 e 49; entrada: 50 a 99 | Sim | Sim | Sim |
| `descricao` | string (até 30) | Nome do cadastro de tributação | Sim | Não | Sim |
| `tipoOperacao` | string | Se o cadastro é de Crédito (Entrada) ou Saída (Débito) | Sim | Não (definido por `pisCofinsEntrada`/`pisCofinsSaida`) | Sim |
| `substituicao` | boolean | Se o cadastro é para operações com substituição tributária de PIS/COFINS | Sim | Não | Sim |
| `pis` | número | Alíquota do PIS, em % | Em `tributacaoLucroReal` e `tributacaoLucroPresumido` | Sim, um valor | Em `tributacaoLucroReal` e `tributacaoLucroPresumido` |
| `cofins` | número | Alíquota da COFINS, em % | Idem | Sim, um valor | Idem |
| `csa` | inteiro | Código de Contribuição Social Apurada (código de crédito/contribuição usado na EFD-Contribuições) | Idem | Sim | Idem |
| `reducao` / `percentualReducao` | número | Percentual de redução da base de cálculo do PIS/COFINS | `reducao`, em cada regime | `percentualReducao` | `reducao`, em cada regime |
| `naturezaReceita` | inteiro | Código da natureza da receita (tabelas 4.3.10 a 4.3.16 da EFD-Contribuições), detalha receitas isentas, com alíquota zero, suspensão ou monofásicas | Sim, no item do grupo | Sim, em cada lado | Não |
| `tipoCreditoTributado` | inteiro | Categoria do crédito vinculado à receita tributada (código de tipo de crédito da EFD-Contribuições) | Sim | Sim | Sim |
| `tipoCreditoNaoTributado` | inteiro | Categoria do crédito vinculado à receita não tributada | Sim | Sim | Sim |

### 8.3 Regime tributário

O cadastro guarda as alíquotas dos dois regimes, mas a gravação recebe um único `pis` e um único `cofins`. A especificação não diz em qual regime esses valores são gravados. A hipótese natural é o regime do grupo econômico informado em `gruposEconomicos`, o que precisa ser confirmado (seção 15). Valores de referência para tributação normal: Lucro Real não cumulativo PIS 1,65% e COFINS 7,6%; Lucro Presumido cumulativo PIS 0,65% e COFINS 3%.

### 8.4 Nome versus código do grupo

A leitura identifica o grupo pelo nome (`grupoEconomico`), e a gravação pede o código numérico (`gruposEconomicos[]`). A ponte é `/gruposeconomicos`, que devolve `codigo` e `nome` (seção 10). Se dois grupos tiverem o mesmo nome, a conversão fica ambígua; nesse caso, use as lojas do grupo para desempatar.

## 9. IBS/CBS (reforma tributária)

A tributação da reforma é feita por classificação tributária (CST IBS/CBS + cClassTrib), vinculada ao produto ou ao NCM em cada loja. As alíquotas de CBS, IBS estadual e IBS municipal não ficam no produto: vêm de uma tabela geral por UF e município, com vigência.

### 9.1 Classificação tributária do produto (`classificacaoTributaria[]` em `/v3/produtos`)

| Campo | Tipo | Descrição | Exemplo |
| --- | --- | --- | --- |
| `codigo` | inteiro | Id da classificação tributária no VRMaster. É o valor de `codigoClassificacaoTributaria` no vincular | 123 |
| `cst` | string (3 dígitos) | CST do IBS/CBS (tabela da reforma) | 000 |
| `descricaoCst` | string | Descrição do CST | Tributação normal |
| `dataInicioCst` | string `dd/MM/yyyy` | Início da vigência do CST | 05/01/2026 |
| `dataFimCst` | string `dd/MM/yyyy` | Fim da vigência do CST | 31/12/2026 |
| `cClassTrib` | string (6 dígitos) | Código de Classificação Tributária do IBS/CBS, informado no item da NF-e/NFC-e | 000001 |
| `descricaoCClassTrib` | string | Descrição da classificação | Classificação Normal |
| `percentualReducao` | string formatada | Percentual de redução de alíquota | "60%" |
| `percentualDiferimento` | string formatada | Percentual de diferimento | "0%" |
| `grupoIbsCbs` | `S`/`N` | Pertence ao grupo de tributação IBS/CBS (grupo `gIBSCBS` do documento fiscal) | S |
| `grupoIbsCbsMono` | `S`/`N` | Pertence ao grupo de tributação monofásica (combustíveis) | N |
| `grupoReducao` | `S`/`N` | Pertence ao grupo com redução de alíquota | S |
| `grupoDiferimento` | `S`/`N` | Pertence ao grupo com diferimento | N |
| `grupoTribRegular` | `S`/`N` | Pertence ao grupo de tributação regular | N |
| `tipoCadastro` | `PRODUTO` ou `NCM` | Origem do vínculo: o próprio produto ou o NCM dele | PRODUTO |

Os percentuais da leitura vêm como texto com o símbolo % ("60%"); no vincular, são enviados como número (60). A lista pode ter mais de um item, um por período de vigência do CST.

### 9.2 Alíquotas gerais (`GET /IbsCbs`)

Retorna a estrutura completa de alíquotas, agrupada por UF, em `retorno`:

| Caminho | Tipo | Descrição | Exemplo |
| --- | --- | --- | --- |
| `cbs[].percentual` | número | Alíquota da CBS (Contribuição sobre Bens e Serviços, federal) | 12.5 |
| `cbs[].dataInicio` / `dataFim` | string `dd/MM/yyyy` | Vigência da alíquota | 01/01/2026 a 31/12/2026 |
| `estados[].uf` | string | Sigla da UF | SP |
| `estados[].percentual` | número | Alíquota do IBS estadual | 17.5 |
| `estados[].dataInicio` / `dataFim` | string `dd/MM/yyyy` | Vigência | 01/01/2026 a 31/12/2026 |
| `estados[].municipios[].codigoIbge` | string | Código IBGE do município | 3550308 |
| `estados[].municipios[].nome` | string | Nome do município | São Paulo |
| `estados[].municipios[].percentual` | número | Alíquota do IBS municipal | 5 |
| `estados[].municipios[].dataInicio` / `dataFim` | string `dd/MM/yyyy` | Vigência | 01/01/2026 a 31/12/2026 |

Os valores do exemplo são ilustrativos da especificação. Em 2026, ano de teste, as alíquotas legais são 0,9% de CBS e 0,1% de IBS; os valores reais vêm do cadastro do cliente.

### 9.3 Consulta de vínculos (`GET /classificacaoTributaria`)

Filtros opcionais: `cnpj`, `idProduto`, `ncm`. Cada item de `retorno` traz todos os campos da tabela 9.1 mais `lojas[]`:

| Caminho | Tipo | Descrição |
| --- | --- | --- |
| `lojas[].cnpj` | inteiro | CNPJ da loja |
| `lojas[].produtosVinculados[].codigo` | inteiro | Código do produto vinculado à classificação nessa loja |
| `lojas[].produtosVinculados[].descricao` | string | Descrição do produto, ex. COCA COLA 2LT |
| `lojas[].ncmsVinculados[].codigo` | string | NCM vinculado à classificação nessa loja |

### 9.4 Gravação (`PATCH /classificacaoTributaria/vincular`)

| Campo | Tipo | Descrição |
| --- | --- | --- |
| `codigoClassificacaoTributaria` | inteiro | Id da classificação tributária (o `codigo` da tabela 9.1) |
| `codigoProdutos` | lista de inteiros | Produtos a vincular |
| `ncms` | lista de strings | NCMs a vincular, `####.##.##` ou 8 dígitos |
| `reducaoPercentual` | número (double) | Percentual de redução a gravar na classificação |
| `diferimentoPercentual` | número (double) | Percentual de diferimento a gravar na classificação |
| `cnpj` | inteiro ou string | Loja onde o vínculo é feito e validado |
| `observacao` | string | Observação livre, ex. Atualização conforme Reforma Tributária 2026 |

```json
{"codigoClassificacaoTributaria": 123, "codigoProdutos": [100, 101, 102],
 "ncms": ["1234.56.78", "9876.54.32"], "reducaoPercentual": 60,
 "diferimentoPercentual": 50, "cnpj": 22881305000192,
 "observacao": "Atualização conforme Reforma Tributária 2026"}
```

Retorno (sempre HTTP 200, mesmo parcial):

| Campo | Descrição |
| --- | --- |
| `dataHora`, `info` | Envelope; `info` resume quantos itens foram e não foram vinculados |
| `detalhes.produtosVinculados[]` | `codigo` e `descricao` dos produtos vinculados |
| `detalhes.totalProdutos` | Quantidade de produtos vinculados |
| `detalhes.produtosNaoVinculados[]` | `codigo` e `motivo`, ex. produto não ativo na loja informada |
| `detalhes.totalProdutosNaoVinculados` | Quantidade de produtos não vinculados |
| `detalhes.ncmsVinculados[]` | NCMs vinculados |
| `detalhes.totalNcms` | Quantidade de NCMs vinculados |
| `detalhes.ncmsNaoVinculados[]` | `ncm` e `motivo`: "NCM não encontrado no cadastro" ou "NCM em formato inválido" |
| `detalhes.totalNcmsNaoVinculados` | Quantidade de NCMs não vinculados |

Regras documentadas:

- A validação de produto é por loja: produto inexistente ou excluído na loja do CNPJ não é vinculado e vai para `produtosNaoVinculados`.
- NCM inválido não gera mais HTTP 400. Ele vai para `ncmsNaoVinculados`, porque os produtos da mesma requisição já foram gravados.
- Se nenhum item for vinculado, os percentuais de redução e diferimento não são gravados, para não alterar a classificação em silêncio. A resposta continua 200.
- A API não cria classificações tributárias: só vincula a uma existente pelo código.

## 10. Grupos econômicos e lojas

`GET /gruposeconomicos` é a única fonte de lojas da API e a ponte entre o nome do grupo (leitura de PIS/COFINS) e o código do grupo (gravação). Não tem parâmetros e devolve todos os grupos em `grupoEconomico[]`.

| Campo | Tipo | Descrição | Exemplo |
| --- | --- | --- | --- |
| `codigo` | inteiro | Código do grupo econômico. É o valor usado em `gruposEconomicos[]` na gravação | 1 |
| `nome` | string | Nome do grupo. É o valor que aparece em `pisCofins[].grupoEconomico` na leitura | Lojas Serve Bem |
| `regimeTributario` | string | Regime de tributação das lojas do grupo | LUCRO REAL, LUCRO PRESUMIDO |
| `cnae` | string | CNAE do grupo | 47903 |
| `naturezaJuridica` | string | Tipo societário | SOCIEDADE ANONIMA FECHADA |
| `qualificacaoPJ` | string | Classificação da pessoa jurídica | PJ EM GERAL |
| `periodicidadeApuracao` | string | Periodicidade de apuração de IRPJ e CSLL | ANUAL, TRIMESTRAL |
| `lojas[].cnpj` | inteiro (int64) | CNPJ da loja | 22881305000192 |
| `lojas[].razaosocial` | string | Razão social do cadastro de fornecedor associado à loja | Loja Bem-te-vi |
| `lojas[].matriz` | boolean | Se a loja é o estabelecimento principal do grupo | false |

**O que a API não informa sobre a loja:** UF, município, código interno da loja e inscrição estadual. Como o ICMS é gravado por UF, a integração precisa manter a UF de cada CNPJ num cadastro próprio. Os dois primeiros dígitos do CNPJ não indicam a UF.

**CNPJ como inteiro.** Nos retornos, o CNPJ vem como número. CNPJs que começam com zero perdem o dígito. Normalize para 14 dígitos com zero-fill antes de comparar ou enviar como parâmetro.

## 11. Tabelas de apoio

As tabelas de apoio são os cadastros que o produto referencia. A integração precisa delas para transformar os valores da leitura nos ids da gravação (`idAliquota`, `idPisCofins`, `idPauta`). Os campos de cada cadastro estão nas seções 6.3, 7 e 8.2; aqui fica o que cada endpoint devolve e para que serve.

### 11.1 Cadastros de ICMS (`GET /icms`)

- Devolve `icms[]` com os campos de `ICMS_Cadastro` (seção 6.3, última coluna), incluindo o `codigo` que vira `idAliquota`.
- Sem parâmetro, lista todos os cadastros ativos. Com `uf`, lista só as alíquotas vinculadas a produtos naquela UF.
- `GET /icms/estadosOperantes` lista as UFs que têm cadastro de ICMS vinculado a produto. Serve para saber em quais UFs o cliente opera.

### 11.2 Cadastros de PIS/COFINS (`GET /piscofins`)

- Devolve `pisCofins[]` com os campos de `PIS-COFINS_Cadastro` (seção 8.2, última coluna), incluindo o `codigo` que vira `idPisCofins`.
- Não tem filtro. Cada cadastro tem `tipoOperacao` (entrada ou saída) e as alíquotas dos dois regimes.

### 11.3 Pautas fiscais (`GET /pautasfiscais`)

- Devolve `pautasFiscais[]` com `ncm`, `mva`, `mvaAjustada`, `tipoValor`, `percentualProdepe`, `recolheIcmsAntecipadamente` e os três cadastros de ICMS da pauta (seção 7).
- Filtro opcional `uf`. A lista não traz o id da pauta.

### 11.4 Códigos de benefício fiscal (`POST /cBenef/new`)

Cadastra códigos de benefício fiscal (cBenef) por UF. O corpo é uma lista. Não há endpoint de consulta de cBenef: o código usado em cada produto só aparece no campo `cBenef` dos cenários de ICMS.

| Campo | Tipo | Descrição | Exemplo |
| --- | --- | --- | --- |
| `codigo` | string | Código do benefício, no padrão da UF | SP999 |
| `uf` | string | UF do benefício | SP |
| `cst` | lista de strings | CSTs de ICMS a que o benefício se aplica | \["10"\] |
| `descricao` | string (até 200) | Descrição do benefício | Teste |
| `observacao` | string (até 5000) | Observação, opcional | Teste |
| `dataInicio` | data `yyyy-MM-dd` | Início da vigência | 2023-03-10 |
| `dataTermino` | data `yyyy-MM-dd` | Fim da vigência | 2023-03-10 |

Use antes de gravar um produto com um cBenef que ainda não existe na base. O comportamento ao repetir um código já cadastrado não está documentado.

### 11.5 Versionamento (`GET /info`)

Devolve `servico`, `major`, `minor`, `release`, `build`, `beta` e `data`. Use no início de cada execução para registrar a versão da API do cliente e detectar mudanças de contrato.

## 12. Gravação: `PATCH /v2/integracaofiscal`

O corpo é uma lista de produtos. Cada item corrige um produto: classificação fiscal no próprio produto, ICMS e pauta nas UFs de `estados`, PIS/COFINS nos grupos de `gruposEconomicos`.

### 12.1 Campos do item

| Campo | Tipo | Descrição | Escopo |
| --- | --- | --- | --- |
| `codigoProduto` | inteiro | Código do produto no VRMaster (o `codigo` da leitura) | — |
| `estados` | lista de strings | Siglas das UFs onde o ICMS e a pauta fiscal serão corrigidos | Define o escopo de `aliquotas`, `pautaFiscal` e `regraFiscal` |
| `gruposEconomicos` | lista de inteiros | Códigos dos grupos econômicos onde o PIS/COFINS será corrigido | Define o escopo de `pisCofins` |
| `classificacaoFiscal.ncm` | string | NCM, `####.##.##` | Produto (todas as lojas) |
| `classificacaoFiscal.cest` | string | CEST, `##.###.##` | Produto |
| `classificacaoFiscal.exTIPI` | inteiro | Ex-TIPI | Produto |
| `aliquotas.icmsDebito` | ICMS\_Correcao | ICMS de saída interna | UFs de `estados` |
| `aliquotas.icmsCredito` | ICMS\_Correcao | ICMS de entrada interna | UFs de `estados` |
| `aliquotas.icmsDebitoInterestadual` | ICMS\_Correcao | ICMS de saída interestadual | UFs de `estados` |
| `aliquotas.icmsCreditoInterestadual` | ICMS\_Correcao | ICMS de entrada interestadual | UFs de `estados` |
| `aliquotas.icmsConsumidorFinal` | ICMS\_Correcao | ICMS de venda a consumidor final | UFs de `estados` |
| `aliquotas.icmsBeneficioGoias` | ICMS\_Correcao | ICMS com benefício de Goiás | UFs de `estados` |
| `pautaFiscal` | Pauta\_Fiscal\_Correcao | `idPauta`, `mva`, `mvaAjustada`, `valorPercentual`, `percentualProdepe`, `recolheIcmsAntecipadamente`, `icmsDebito`, `icmsCredito`, `icmsInterestadual` (seção 7) | UFs de `estados` |
| `pisCofins.pisCofinsEntrada` | PIS-COFINS\_Correcao | PIS/COFINS de entrada (crédito) | Grupos de `gruposEconomicos` |
| `pisCofins.pisCofinsSaida` | PIS-COFINS\_Correcao | PIS/COFINS de saída (débito) | Grupos de `gruposEconomicos` |
| `regraFiscal` | RegraFiscal | Regra fiscal por operação, consumidor e CFOP (12.3) | UFs de `estados` (presumido) |

### 12.2 Objetos aninhados

**ICMS\_Correcao** (cada cenário de `aliquotas` e de `pautaFiscal`): `idAliquota`, `cst`, `csosn`, `percentual`, `percentualReducao`, `percentualDiferimento`, `percentualFCP`, `aplicaReducaoFCP`, `cBenef`, `aliquotaMonofasico`, `idMotivoDesoneracao`. Descrição de cada um na seção 6.3.

**PIS-COFINS\_Correcao** (`pisCofinsEntrada` e `pisCofinsSaida`): `idPisCofins`, `cst`, `pis`, `cofins`, `csa`, `percentualReducao`, `naturezaReceita`, `tipoCreditoTributado`, `tipoCreditoNaoTributado`. Descrição na seção 8.2.

### 12.3 Regra fiscal

A regra fiscal associa ao produto um tratamento de ICMS específico para uma combinação de operação, tipo de consumidor e CFOP. A especificação não descreve os campos além do exemplo.

| Campo | Tipo | Exemplo | Significado provável |
| --- | --- | --- | --- |
| `tipoOperacao` | string | "1 - Saída" | Entrada ou saída |
| `tipoConsumidor` | string | "1" | Tipo de destinatário (consumidor final, contribuinte etc.); domínio não documentado |
| `cfop` | string | "5309" | CFOP da operação |
| `icms.idAliquota` | inteiro | 7 | Cadastro de ICMS aplicado na regra |
| `icms.cst` | string | "01" | CST da regra |
| `icms.percentual` | número | 18 | Alíquota da regra |

`DELETE /regrafiscal/{id}` remove uma regra. O `id` vai no caminho; os cabeçalhos `uf` (2 letras) e `codigoProduto` são obrigatórios. A API não tem endpoint para listar as regras de um produto, então o `id` precisa vir de outra fonte (seção 15).

### 12.4 Exemplo completo

```json
[{
  "codigoProduto": 86922,
  "estados": ["SP"],
  "gruposEconomicos": [1],
  "classificacaoFiscal": {"ncm": "1901.90.00", "cest": "17.004.00", "exTIPI": 0},
  "aliquotas": {
    "icmsDebito":               {"idAliquota": 1, "cst": "00", "percentual": 18, "percentualReducao": 0, "percentualDiferimento": 0, "percentualFCP": 0, "aplicaReducaoFCP": false, "cBenef": "", "aliquotaMonofasico": 0, "idMotivoDesoneracao": 0},
    "icmsCredito":              {"idAliquota": 1, "cst": "00", "percentual": 18},
    "icmsDebitoInterestadual":  {"cst": "00", "percentual": 12},
    "icmsCreditoInterestadual": {"cst": "00", "percentual": 12},
    "icmsConsumidorFinal":      {"idAliquota": 1, "cst": "00", "percentual": 18}
  },
  "pautaFiscal": {"idPauta": 1, "mva": 30, "mvaAjustada": 35, "valorPercentual": false, "percentualProdepe": 0, "recolheIcmsAntecipadamente": false},
  "pisCofins": {
    "pisCofinsEntrada": {"idPisCofins": 1, "cst": 50, "pis": 1.65, "cofins": 7.6, "csa": 0, "naturezaReceita": 0, "percentualReducao": 0, "tipoCreditoTributado": 0, "tipoCreditoNaoTributado": 0},
    "pisCofinsSaida":   {"idPisCofins": 1, "cst": 1,  "pis": 1.65, "cofins": 7.6, "csa": 0, "naturezaReceita": 0, "percentualReducao": 0}
  }
}]
```

O exemplo oficial preenche `cst` e `csosn` com a lista inteira de valores do enum ("00, 10, 20, …"). Isso é a documentação dos valores possíveis, não um valor a enviar: mande um único código.

### 12.5 Retorno

| Campo | Descrição |
| --- | --- |
| `dataHora`, `info` | Envelope |
| `integracaoFiscal[].codigoProduto` | Produto processado |
| `integracaoFiscal[].status` | Categoria do resultado do processamento daquele produto (valores não documentados) |
| `integracaoFiscal[].info` | Detalhe do que a API fez com o produto |

Trate o resultado item a item: a resposta HTTP 200 não garante que todos os produtos foram gravados.

## 13. Mapeamento leitura → gravação

A leitura v3 não pode ser reenviada como está na gravação v2: as listas viram objetos, nomes viram códigos e os ids de cadastro precisam ser resolvidos nas tabelas de apoio.

| Dado | Leitura (`/v3/produtos`) | Gravação (`/v2/integracaofiscal`) | Transformação |
| --- | --- | --- | --- |
| Produto | `codigo` | `codigoProduto` | Renomear |
| NCM, CEST, Ex-TIPI | `classificacaoFiscal.*` | `classificacaoFiscal.*` | Direto |
| ICMS | `aliquotas[]`, um item por `uf` | `aliquotas` (objeto) + `estados[]` | Pegar o item da UF desejada; a UF vai para `estados` |
| Id do cadastro de ICMS | não vem | `idAliquota` em cada cenário | Procurar em `/icms?uf=` o `codigo` com mesmo CST, CSOSN, percentual, redução, diferimento e FCP |
| ICMS monofásico | não vem | `aliquotaMonofasico` | Ler `aliquotaIcmsMonofasico` do cadastro em `/icms` |
| Motivo de desoneração | não vem | `idMotivoDesoneracao` | Sem fonte na API (seção 15) |
| Pauta fiscal | `aliquotas[].pautaFiscal` | `pautaFiscal` | Pegar a pauta da UF; os três objetos ICMS seguem a regra do ICMS |
| Id e tipo de valor da pauta | não vem | `idPauta`, `valorPercentual` | `tipoValor` vem de `/pautasfiscais?uf=` pelo NCM; `idPauta` sem fonte |
| Grupo do PIS/COFINS | `pisCofins[].grupoEconomico` (nome) | `gruposEconomicos[]` (código) | Converter o nome em código por `/gruposeconomicos` |
| PIS/COFINS saída | `pisCofins[].debito` | `pisCofins.pisCofinsSaida` | `codigo` → `idPisCofins`; `pis`, `cofins`, `csa`, `reducao` do regime do grupo → `pis`, `cofins`, `csa`, `percentualReducao` |
| PIS/COFINS entrada | `pisCofins[].credito` | `pisCofins.pisCofinsEntrada` | Idem |
| Natureza da receita | `pisCofins[].naturezaReceita` (no grupo) | `naturezaReceita` em cada lado | Copiar o valor do grupo para entrada e saída |
| Classificação IBS/CBS | `classificacaoTributaria[]` | outro endpoint: `/classificacaoTributaria/vincular` | `codigo` → `codigoClassificacaoTributaria`; "60%" → 60; CNPJ da loja |
| Descrição, EAN, data | `descricao`, `codigosBarras`, `dataAlteracao` | sem campo | Somente leitura |

### 13.1 Montagem do payload

1. Ler o produto com `GET /v3/produtos/{id}?cnpj=` da loja.
2. Selecionar o item de `aliquotas[]` da UF da loja e o item de `pisCofins[]` do grupo da loja.
3. Aplicar a correção sobre esse estado atual, sem descartar os campos que não mudam.
4. Resolver `idAliquota` e `idPisCofins` nas tabelas de apoio. Se não existir cadastro compatível, não gravar: o cadastro precisa ser criado no VRMaster.
5. Preencher `estados` com a UF e `gruposEconomicos` com o código do grupo. Avisar quantas outras lojas compartilham a UF e o grupo.
6. Enviar e tratar `integracaoFiscal[]` item a item.
7. Reler o produto e comparar campo a campo com o esperado.

O passo 3 parte da hipótese de que campos omitidos no PATCH podem ser zerados. Até a homologação provar o contrário, envie sempre o produto completo.

## 14. Tabelas de domínio

Os códigos abaixo são os valores aceitos pelos enums da API, com o significado da legislação (Ajuste SINIEF, EFD-Contribuições e tabelas da reforma). A especificação da VR traz só os códigos, sem descrição.

### 14.1 CST do ICMS (regime normal)

| CST | Significado | Campos que costumam acompanhar |
| --- | --- | --- |
| 00 | Tributada integralmente | `percentual` |
| 10 | Tributada e com cobrança do ICMS por ST | `percentual`, pauta (MVA) |
| 20 | Com redução de base de cálculo | `percentual`, `percentualReducao` |
| 30 | Isenta ou não tributada e com cobrança do ICMS por ST | pauta (MVA) |
| 40 | Isenta | `idMotivoDesoneracao`, `cBenef` |
| 41 | Não tributada | `idMotivoDesoneracao`, `cBenef` |
| 50 | Suspensão | `idMotivoDesoneracao` |
| 51 | Diferimento | `percentualDiferimento` |
| 60 | ICMS cobrado anteriormente por ST | — (comum no varejo) |
| 61 | Tributação monofásica sobre combustíveis cobrada anteriormente | `aliquotaMonofasico` (ausênte do enum de gravação) |
| 70 | Com redução de base de cálculo e cobrança do ICMS por ST | `percentualReducao`, pauta |
| 90 | Outras | conforme o caso |

### 14.2 CSOSN (Simples Nacional)

| CSOSN | Significado |
| --- | --- |
| 101 | Tributada com permissão de crédito |
| 102 | Tributada sem permissão de crédito |
| 103 | Isenção do ICMS para faixa de receita bruta |
| 201 | Tributada com permissão de crédito e com cobrança do ICMS por ST |
| 202 | Tributada sem permissão de crédito e com cobrança do ICMS por ST |
| 203 | Isenção para faixa de receita bruta e com cobrança do ICMS por ST |
| 300 | Imune |
| 400 | Não tributada |
| 500 | ICMS cobrado anteriormente por ST ou por antecipação |
| 900 | Outros |

### 14.3 CST do PIS/COFINS

| CST | Significado | Lado |
| --- | --- | --- |
| 01 | Operação tributável com alíquota básica | Saída |
| 02 | Operação tributável com alíquota diferenciada | Saída |
| 03 | Operação tributável com alíquota por unidade de medida | Saída |
| 04 | Operação tributável monofásica, revenda a alíquota zero | Saída |
| 05 | Operação tributável por substituição tributária | Saída |
| 06 | Operação tributável a alíquota zero | Saída |
| 07 | Operação isenta da contribuição | Saída |
| 08 | Operação sem incidência da contribuição | Saída |
| 09 | Operação com suspensão da contribuição | Saída |
| 49 | Outras operações de saída | Saída |
| 50 a 56 | Operação com direito a crédito, vinculada a receita tributada, não tributada ou exportação (e combinações) | Entrada |
| 60 a 67 | Crédito presumido, nas mesmas vinculações | Entrada |
| 70 | Operação de aquisição sem direito a crédito | Entrada |
| 71 | Aquisição com isenção | Entrada |
| 72 | Aquisição com suspensão | Entrada |
| 73 | Aquisição a alíquota zero | Entrada |
| 74 | Aquisição sem incidência | Entrada |
| 75 | Aquisição por substituição tributária | Entrada |
| 98 | Outras operações de entrada | Entrada |
| 99 | Outras operações | Ambos |

Na API o CST do PIS/COFINS é inteiro: 1, não "01".

### 14.4 CST do IBS/CBS (principais)

A tabela completa de CST e cClassTrib é publicada no Portal Nacional da NF-e e muda por nota técnica. Os códigos mais usados no varejo são estes; confirme a lista vigente antes de mapear.

| CST | Significado |
| --- | --- |
| 000 | Tributação integral |
| 200 | Alíquota reduzida |
| 400 | Isenção |
| 410 | Imunidade e não incidência |
| 510 | Diferimento |
| 550 | Suspensão |
| 620 | Tributação monofásica |

### 14.5 UF

`aliquotas[].uf` aceita as 27 UFs e `EX` (exterior, para operações de comércio exterior).

## 15. Pontos em aberto a validar em homologação

A especificação deixa 16 comportamentos sem definição. Os quatro primeiros mudam o desenho do integrador e devem ser testados antes de qualquer outro.

- [ ] **Campos omitidos no PATCH:** um item só com `classificacaoFiscal` zera ou mantém ICMS, pauta e PIS/COFINS? (seção 13.1)
- [ ] **Gravação sem id:** sem `idAliquota`, `idPisCofins` ou `idPauta`, a API localiza um cadastro igual, cria um novo ou recusa? Consultar `/icms` e `/piscofins` antes e depois.
- [ ] **Escopo de `estados`:** a correção em SP aparece em todas as lojas de SP no VRMaster?
- [ ] **Regime do PIS/COFINS:** o `pis`/`cofins` gravado vai para Lucro Real, Lucro Presumido ou para o regime do grupo informado?
- [ ] **Formato real das respostas:** a chave de dados é `retorno` (exemplos) ou `produtos`, `icms`, `integracaoFiscal` etc. (schemas)?
- [ ] **Valores de `integracaoFiscal[].status`** e comportamento de lote com item válido e inválido misturados.
- [ ] **Idempotência:** o mesmo payload enviado duas vezes produz o mesmo estado?
- [ ] **CST 61 na gravação:** aceito ou recusado, já que falta no enum (seção 6.5)?
- [ ] **Filtro `dataAlteracao`:** "igual a" ou "a partir de"? Uma alteração de tributação atualiza essa data?
- [ ] **Paginação:** há metadados de total? Qual o máximo de `itensPorPagina`?
- [ ] **Limite e tempo do PATCH:** quantos produtos por chamada e quanto tempo leva com 1, 20, 100 e 500?
- [ ] **Fonte de `idPauta`** e do `id` da regra fiscal, que nenhuma consulta devolve.
- [ ] **Fonte de `idMotivoDesoneracao`:** o cadastro `/icms` traz só a descrição do motivo.
- [ ] **Domínio de `regraFiscal.tipoConsumidor`** e efeito da regra fiscal no cálculo.
- [ ] **Token por unidade ou geral:** o mesmo token lê outra loja (outro CNPJ) da mesma base?
- [ ] **Validade do NCM e do CEST** na gravação, e se o PATCH aceita NCM sem pontos.

## Fontes

- [VR Integração Fiscal API, referência OpenAPI 4.5.7](https://vrsoftbr.github.io/VRMasterDocsAPI/#description/introduction) e [especificação JSON](https://vrsoftbr.github.io/VRMasterDocsAPI/VRMasterDocsAPI.openapi3.json)
- [VR Integração Fiscal API: licenciamento, instalação e token](https://docs.vrsoft.com.br/vrmaster/gestao-do-conhecimento/conteudos-adicionais/vr-integracao-fiscal-api.md)
- [VRMaster, Sistema > API](https://docs.vrsoft.com.br/vrmaster/manual-do-sistema/manual-do-sistema-vr-master/manual-do-sistema-vr-master-versoes/manual-do-sistema-vr-master-ferramentas-v4-6/manual-do-sistema-vr-master-ferramentas-v4-6-sistema/api.md)

As descrições de CST, CSOSN e dos cenários de ICMS marcadas como interpretação usual vêm da legislação fiscal, não da especificação da VR.
