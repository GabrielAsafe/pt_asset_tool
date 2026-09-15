# Patch notes v7 — Fix 136 skill asset audit

## Objetivo

Adaptar o Summit Asset Enrichment ao Fix 136: localizar e reconciliar assets de skills EU em múltiplas bases históricas, incluindo roots configurados acima da pasta real do client.

## Alterações

- novo `audit_fix136_skill_assets.py` para auditoria multi-source recursiva;
- configuração dedicada `fix136_paths.json` com as três fontes pedidas:
  1. `/home/gabriel/armazem/priston/servidor_cliente_PT_EU/Files` (prioridade 10);
  2. `/home/gabriel/old/velho` (prioridade 20);
  3. `/home/gabriel/armazem/priston/ExMachina` (prioridade 30);
- **todas** as fontes são verificadas, mesmo depois de existir um candidato selecionado;
- resolução em três níveis: `EXACT`, `SUFFIX` recursivo e `BASENAME`;
- `CaseIndex.find_suffix()` resolve referências como `image/...` quando o donor real está em `backup/client/image/...`;
- o migrador genérico também aceita um `SUFFIX` único antes do fallback por basename;
- inventário Fix 136 incorporado em `audit_data/fix136/`;
- 485 assets físicos únicos na primeira matriz: 400 BMPs, 51 TGAs explícitos únicos e 34 literals únicos dos handlers;
- comparação SHA-256 entre todos os candidatos e deteção de variantes/conflitos;
- `.part` adicionado aos tipos de asset reconhecidos;
- expansão recursiva das dependências textuais de `.part` (até 8 níveis por padrão);
- staging opcional missing-only para árvore separada; o comando **nunca escreve diretamente no client Summit**;
- testes para suffix matching, normalização dos paths EU com `\\`, closure de `.part` e staging.

## Execução

```bash
python3 audit_fix136_skill_assets.py \
  --config fix136_paths.json \
  --out-dir manifests/fix136_skill_assets
```

Para criar um patch separado depois da auditoria:

```bash
python3 audit_fix136_skill_assets.py \
  --config fix136_paths.json \
  --out-dir manifests/fix136_skill_assets \
  --stage-dir generated/fix136_patch
```

O staging ignora assets já presentes no target, candidatos ambíguos/conflitantes e referências basename-only cujo destino físico não esteja provado.
