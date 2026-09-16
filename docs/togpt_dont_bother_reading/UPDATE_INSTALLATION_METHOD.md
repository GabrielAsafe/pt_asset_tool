# Método de instalação das atualizações RC

## Raiz ativa

A linha RC é instalada sobre `~/Transferências/current`.

`current/app` é a aplicação ativa. O cliente e o servidor reais são fontes
read-only durante esta fase e não recebem writes dos instaladores.

## Fluxo transacional

Cada hotfix/checkpoint segue a mesma sequência:

1. identificar `current` e confirmar a versão/safety esperada;
2. executar `app/pt_rc6_12_verify.py`;
3. executar `VERIFY_PACKAGE.sh`;
4. comparar hashes de precondition dos ficheiros estáveis que o patch espera;
5. falhar fechado em qualquer drift não explicado;
6. criar backup dos ficheiros que serão substituídos em
   `~/Transferências/asset_tool_armazem/<PATCH>_BACKUP_<timestamp>/`;
7. copiar somente o payload da atualização para `current`;
8. comparar hashes de postcondition;
9. executar novamente verifier + package verify;
10. se um postcheck falhar, restaurar o backup e reverificar;
11. uma repetição sobre o mesmo estado final retorna
    `IDEMPOTENT_ALREADY_INSTALLED`.

## Checkpoints

Checkpoints consolidados comparam a árvore ativa com um snapshot estável e
copiam apenas diferenças. Eles preservam explicitamente:

- `app/pt_build/` — staging, reports e evidência local;
- `app/certifications/assets.jsonl` — journal de certificação mutável;
- `app/pt_asset_app_config.json` — configuração local do utilizador, quando
  presente, não é distribuída por FULL releases.

## Ficheiros efêmeros fora do contrato de integridade

O snapshot não certifica conteúdo que muda apenas por executar Python/tests:

- `__pycache__/`;
- `*.pyc`;
- `.pytest_cache/`;
- `app/pt_build/`.

Os fontes `.py`, scripts, dados, manifests e ficheiros críticos continuam
hash-certificados. `VERIFY_PACKAGE.sh` rejeita manifests que tentem voltar a
incluir bytecode/cache efêmero.

## Segurança

Durante esta linha de desenvolvimento:

- `production_authorized=false`;
- `client_write_authorized=false`;
- `server_write_authorized=false`.

Nenhuma instalação RC concede autorização implícita de produção.

## Assets recuperados de donors

A camada Asset Contracts/Superset não instala assets diretamente no cliente ou
servidor. `RECOVER`, `RECOVER_DEDUPED` e `RECOVER_PREFERRED_VARIANT` são
materializados apenas em `app/pt_build/aggregate/...` para review. A passagem
desses artefactos para o cliente é um passo externo/manual do utilizador e não
é efetuada pelo instalador da aplicação.
