# PATCH NOTES v4 — runtime dependency closure

## Correções

1. **Analyzer v3 false gap**: o Markdown dizia que não havia `.ini` mesmo quando `by_ext` já contava arquivos `.ini`. A seção era hardcoded da análise anterior. Agora os gaps são calculados do corpus real.
2. **Modelo lógico não significa arquivo físico `.INI`**: confirmado no source atual que `smModelDecode(logical.ini, ...)` chama `smFindFile(..., "inx")`. Assim, `foo.INI` pode ser apenas o nome lógico; `foo.INX` é o runtime cache válido mesmo sem `foo.INI` físico.
3. **INX agora é parseado por campos tipados** nas duas ABIs comprovadas (95,268 / 67,084): `szModelFile`, `szMotionFile`, `szSubModelFile`, `szLinkFile`, `szTalkLinkFile`, `szTalkMotionFile`.
4. **Fechamento runtime**:
   - `.INI` / `.IN` lógico → `.INX`;
   - `INX.szModelFile (.ASE)` → `.SMD`;
   - `INX.szMotionFile (.ASE)` → `.SMB`;
   - `INX.szTalkMotionFile` → `.SMB`;
   - `INX.szLinkFile` / `szTalkLinkFile` → `.INX`.
5. O coletor grava `closure_report.json` com cada edge `RESOLVED` ou `MISSING`.
6. O analisador cria auditoria de bundles monster/NPC e distingue **authoring source** de **runtime dependency**.

## Uso

```bash
python3 collect_reverse_samples.py --config summit_paths.json --per-type 3 --max-followed 600 --out summit_reverse_samples_v4.zip
python3 analyze_reverse_samples.py summit_reverse_samples_v4.zip --out-dir reverse_analysis_v4
```

O objetivo desta rodada é obter pelo menos um bundle com:

`Monster/NPC server definition -> INX -> SMD + SMB -> textures`

O `.INI/.IN` físico é desejável como evidência de authoring, mas não é bloqueador de runtime se o `.INX` correspondente estiver presente.
