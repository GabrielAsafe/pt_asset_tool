# Asset Quarantine Workflow

## Objetivo

O workflow de quarantine existe para retirar temporariamente do client apenas assets com evidência forte de não-utilização/integridade inválida, mantendo restore completo e sem transformar ausência de evidência em autorização de delete.

A autoridade continua sendo `asset_retention`. O quarantine não cria um segundo manifest de assets e nunca define `deletion_authorized=true`.

## Níveis

### Q0_HIGH_CONFIDENCE_INVALID_ORPHAN

Elegível para aplicação automática somente quando todas as condições são verdadeiras:

- `state == ORPHAN_CANDIDATE`;
- `graph_linked == false`;
- `root_reachable == false`;
- sem `entity_bundle`;
- sem evidência positiva de retenção;
- `cook_status == error`;
- `cook_documented_outlier == true`;
- `integrity_action == INVALID_UNREACHABLE_QUARANTINE_REVIEW`;
- `deletion_authorized == false`.

O plano grava tamanho e SHA-256 do arquivo físico. A aplicação recusa qualquer asset cujo conteúdo tenha mudado desde a criação do plano.

### Q1_COMPONENT_REVIEW

Componentes `URC-*` graph-linked e não alcançados por strong roots aparecem em uma fila de revisão por componente. Q1 nunca é aplicado automaticamente. No V2.7 ele recebe somente uma prioridade de revisão A/B/C; componentes com evidência positiva ficam `BLOCKED`.

Se qualquer membro do componente possui estado `PROTECTED_*`, `entity_bundle` ou outra evidência positiva além do próprio `CONTRACT_GRAPH_EDGE`, o componente aparece como `Q1_BLOCKED_POSITIVE_EVIDENCE`.

### Ranking Q1 V2.7

O score é **prioridade de revisão**, não confiança de delete. Fatores positivos incluem membro inválido/documented outlier, componente pequeno, ausência de edges externos e poucos entry nodes. O ranking nunca altera `deletion_authorized=false`.

```bash
python3 app/pt_asset.py quarantine review --band A --limit 50
python3 app/pt_asset.py quarantine review --component URC-02537
```

Bandas:

- `A`: revisar primeiro; normalmente há asset inválido e isolamento estrutural.
- `B`: revisão intermediária.
- `C`: baixa prioridade; ausência de sinais fortes de integridade inválida.
- `BLOCKED`: possui evidência positiva/entity bundle/proteção e não é candidato a quarantine.


### Quarantine manual Q1 V2.8

V2.8 mantém Q1 fora de qualquer automação. Um componente pode ser movido somente por comando explícito e somente se o plano atual registrar `manual_quarantine_eligible=true`. O gate é independente do score e exige cumulativamente:

- banda de revisão `A`;
- no máximo 10 membros;
- zero `PROTECTED_*`;
- zero `entity_bundle`;
- zero evidência positiva além de `CONTRACT_GRAPH_EDGE`;
- zero edges externos de entrada e saída;
- pelo menos um membro inválido documentado;
- todos os membros em `REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE`;
- todos graph-linked e não root-reachable;
- todos os arquivos físicos presentes, sem symlink, dentro do client;
- bytes + SHA-256 capturados no plano e revalidados imediatamente antes do move.

Mesmo quando elegível, `action` do ranking continua `REVIEW_ONLY`. A autorização operacional vem apenas do comando separado com o ID exato do componente e token de confirmação. Não existe wildcard, `--band A` apply, batch Q1 ou delete.

```bash
python3 app/pt_asset.py quarantine apply-component \
  --component URC-02537 \
  --confirm MOVE_Q1_COMPONENT_TO_QUARANTINE
```

A transação usa o mesmo storage reversível e `quarantine restore` restaura todos os membros do componente usando os SHA-256 registrados.


## Comandos

Gerar plano sem mover arquivos:

```bash
python3 app/pt_asset.py audit quarantine-plan
```

Ver estado:

```bash
python3 app/pt_asset.py quarantine status
```

Aplicar somente Q0:

```bash
python3 app/pt_asset.py quarantine apply \
  --confirm MOVE_Q0_TO_QUARANTINE
```

Aplicar manualmente exatamente um Q1 elegível:

```bash
python3 app/pt_asset.py quarantine apply-component \
  --component URC-02537 \
  --confirm MOVE_Q1_COMPONENT_TO_QUARANTINE
```

Restaurar a transação mais recente:

```bash
python3 app/pt_asset.py quarantine restore \
  --confirm RESTORE_QUARANTINE
```

`--plan` e `--transaction` permitem apontar explicitamente para manifests específicos.

## Storage e transação

Os arquivos movidos saem do client e são preservados em:

```text
pt_build/quarantine_store/QTN-*/files/<relative-client-path>
```

Cada transação mantém `transaction.json` com path original, path de quarantine, bytes e SHA-256.

Antes de aplicar, o tool valida:

1. SHA-256 do `asset_retention/result.json` usado no plano;
2. SHA-256 do `asset_retention/assets.tsv` usado no plano;
3. presença do arquivo físico;
4. bytes e SHA-256 do asset;
5. ausência de symlink/path escape.

Se o retention report mudou, o plano precisa ser regenerado.

## Delete

V2.8 não implementa delete. Quarantine é reversível e obrigatória antes de qualquer política futura de `DELETE_ELIGIBLE`. Q1 só pode ser movido manualmente por componente estritamente elegível; não existe auto-move/batch por score.
