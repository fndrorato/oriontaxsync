# Gerar e homologar a release 2.0.0

## Pré-requisitos

- alterações revisadas e commitadas na branch `erp/sysmo-version`;
- pull request aprovado para `main`;
- Actions habilitado no repositório público `fndrorato/oriontaxsync`;
- permissão de escrita do `GITHUB_TOKEN` para criar releases;
- máquina Windows de homologação para executar o instalador;
- banco Sysmo e API OrionTax de homologação, sem dados de produção.

## 1. Testar o instalador sem publicar release

No GitHub:

1. abrir **Actions**;
2. selecionar **Build Windows Installer**;
3. escolher **Run workflow**;
4. selecionar a branch `erp/sysmo-version`;
5. aguardar testes, PyInstaller e Inno Setup;
6. baixar o artifact `OrionTaxSync-Installer-2.0.0`.

O artifact deverá conter:

```text
OrionTaxSync_Setup_2.0.0.exe
update-manifest.json
```

Essa execução manual não cria GitHub Release e não é vista pelos clientes.

## 2. Homologar o instalador

Em uma máquina Windows sem produção:

1. copiar o SQLite e a pasta atual para backup;
2. instalar `OrionTaxSync_Setup_2.0.0.exe`;
3. confirmar atalhos e inicialização;
4. abrir o sistema e confirmar versão 2.0.0;
5. confirmar que instalação existente inicia como Intersolid;
6. executar a regressão Intersolid do plano de testes;
7. selecionar Sysmo, reiniciar e configurar homologação;
8. executar envio e recebimento manuais;
9. comparar dados campo a campo;
10. testar reinstalação do mesmo pacote e preservação das configurações.

## 3. Publicar a release

Somente depois da homologação e do merge em `main`:

```bash
git switch main
git pull --ff-only
git tag -a v2.0.0 -m "OrionTax Sync 2.0.0"
git push origin v2.0.0
```

A tag dispara o workflow e cria a release pública com os dois arquivos.

O aplicativo consulta automaticamente:

```text
https://github.com/fndrorato/oriontaxsync/releases/latest/download/update-manifest.json
```

Não é necessário configurar essa URL em cada cliente. A verificação ocorre
cinco segundos após abrir e depois a cada doze horas. Falha de internet não
interrompe o funcionamento normal.

## 4. Validação depois da publicação

- abrir a URL estável do manifesto no navegador;
- conferir `version`, `installer_url`, `size` e `sha256`;
- baixar o instalador e comparar SHA-256;
- abrir uma versão anterior e confirmar a oferta de atualização;
- aceitar a atualização e confirmar reinício na 2.0.0;
- confirmar que SQLite, credenciais, clientes e agendamentos foram preservados;
- conferir logs de inicialização e sincronização.

## 5. Rollback

Se a homologação falhar, não criar a tag. Se a release já estiver publicada:

1. marcar a release problemática como pre-release ou removê-la do canal latest;
2. corrigir o código e publicar uma versão superior, por exemplo `2.0.1`;
3. não reutilizar nem mover a tag `v2.0.0`;
4. restaurar o backup local somente se houver incompatibilidade de schema/dados.

O atualizador bloqueia downgrade; rollback automático não faz parte da versão
2.0.0 e deve ser executado de forma supervisionada.
