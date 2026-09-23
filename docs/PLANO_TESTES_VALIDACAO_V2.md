# Plano de testes e validação — OrionTax Sync 2.0

## Escopo automatizado

Executar em todo pull request e no workflow de instalador:

```bash
python -m unittest discover -s tests -v
```

A suíte cobre migração multi-ERP, persistência criptografada, mapeamentos Sysmo,
paginação/deduplicação da API e segurança básica do atualizador.

## Portões de qualidade

1. `python -m unittest discover -s tests -v` sem falhas.
2. `python -m compileall` sem erros de sintaxe.
3. `git diff --check` sem whitespace inválido.
4. build PyInstaller concluído no Windows.
5. build Inno Setup concluído no workflow manual.
6. instalação limpa em Windows 10 e 11.
7. atualização sobre a versão 1.0.5 preservando SQLite, logs e agendamentos.
8. regressão manual completa da Intersolid Oracle e Firebird.
9. homologação Sysmo com rollback e reconciliação das contagens.

## Matriz manual Intersolid

| Cenário | Resultado esperado |
|---|---|
| Abrir base local antiga | Perfil Intersolid selecionado automaticamente |
| Oracle thin/thick | Teste e sincronização mantêm comportamento anterior |
| Firebird 2.5 | Teste e sincronização mantêm comportamento anterior |
| Enviar/Buscar manual | Dados e logs equivalentes à versão 1.x |
| Agendamento | Execução única e registro correto |
| Cancelamento | Conexão interrompida e operação marcada como cancelada |

## Matriz manual Sysmo

| Cenário | Resultado esperado |
|---|---|
| Configuração incompleta | Operação permanece desabilitada/bloqueada |
| Schema/tabela ausente | Teste informa exatamente a tabela ausente |
| Produto inválido | Produto/campo aparecem no erro; lote não é enviado |
| POST 201 | Job fica como aceito, nunca como concluído |
| HTTP 400 | Sem retentativa automática |
| Timeout de POST | Sem retentativa automática até existir idempotência |
| GET com várias páginas | Todas são reunidas antes da escrita |
| Falha em página intermediária | Tabela Sysmo anterior é preservada |
| Fotografia vazia | DELETE é impedido |
| Erro durante INSERT | Rollback preserva fotografia anterior |
| Dois jobs concorrentes | Segundo job é recusado |

## Validação de atualização

- release manual produz artifact sem alterar `build.yml`;
- tag `v2.0.0` exige `APP_VERSION=2.0.0`;
- instalador mantém o mesmo `AppId`;
- manifesto possui URL HTTPS, tamanho e SHA-256 corretos;
- hash divergente impede execução;
- versão menor/igual não é oferecida;
- sincronização ativa impede instalação;
- recusa de UAC mantém a versão atual operacional;
- atualização concluída reinicia na versão publicada.

## Pendências que bloqueiam produção automática Sysmo

- endpoint read-only de saúde/autenticação da API;
- endpoint de consulta do `job_id`;
- idempotência no POST para retentativa segura;
- snapshot/ack ou correção do efeito colateral do GET paginado;
- schema Sysmo real de homologação e validação dos limites de coluna;
- assinatura Authenticode do instalador.

Enquanto essas pendências existirem, a versão 2.0 deve operar em homologação ou
modo manual supervisionado para clientes Sysmo.
