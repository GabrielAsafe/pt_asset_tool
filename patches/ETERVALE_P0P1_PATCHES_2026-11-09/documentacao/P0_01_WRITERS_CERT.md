# P0/01 — Certificação dos writers (SMD/SMB/INX)

**Sem alterar o repositório Etervale.** O comando gera um candidato verdadeiro com os writers do Asset Tool em `app/pt_build/etervale/writer_probes/`, reabre internamente o SMD ou verifica o escopo de edição SMB/INX, e opcionalmente executa o `PristonTale.AssetDump` de dentro do Etervale.

```bash
cd ~/Transferências/pt_asset_tool
python3 app/pt_asset.py etervale writer-certify --mode stage --execute --build
python3 app/pt_asset.py etervale writer-certify --mode model --execute
# Escolha caminhos existentes, relativos a Etervale-git/assets:
python3 app/pt_asset.py etervale writer-certify --mode inx --source 'char/.../arquivo.inx' --execute
python3 app/pt_asset.py etervale writer-certify --mode smb --source 'char/.../arquivo.smb' --execute
```

- `stage`: gera cenário sintético de um triângulo via `compile_stage072`.
- `model`: gera modelo estático 0.62 via `compile_static_model062`.
- `inx`: altera somente um campo `repeat` de MotionInfo existente, com `patch_motion`.
- `smb`: altera um único componente de key existente com `patch_key`; não insere novos keys.
- O manifest `PT_ASSET_ETERVALE_CANDIDATE_BATCH_V1` pode ser passado a `etervale validate-batch`.
- `--execute` confirma apenas **aceitação do leitor C#**, não fidelidade visual nem execução de animações. A publicação permanece bloqueada.

Limitações: no ZIP do Etervale não vieram os assets reais; os testes nativos com `--execute` precisam ser feitos no seu checkout. A compatibilidade de variantes complexas (Physique, animações raras, multimaterial) não é inferida deste probe mínimo.
