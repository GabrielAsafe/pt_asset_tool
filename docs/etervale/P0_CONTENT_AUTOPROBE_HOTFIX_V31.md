# Hotfix P0/02 V3.1 — Seleção automática de conteúdo para WorldImport

## Motivo

O P0 V3 passou nos 4 probes binários e nos 75 testes, mas a verificação conjunta de conteúdo real falhou com:

- `ENTITY_NOT_SELECTED_IN_CATALOG:OpenItem/2_WA108.txt` — o importador não usa aquela variante para o catálogo de runtime.
- `NO_GAMEPLAY_CATALOG_CHANGE:NPC` — alterar `*NAME` em `NPC/adventure-artes.NPC` não alterou as tabelas do catálogo (nome sujeito à resolução do `EnglishNames.Npc`).

A seleção automática agora imita a regra `ParseItems` do `WorldImport` (agrupar por código e preferir nome de arquivo correspondente ao código; caso contrário, primeiro arquivo por nome ordinal). Para NPCs, utiliza campo numérico tipado (`*레벨`, `*이동범위`, `*모델크기`) ou acrescenta `*모델크기 1.25` somente em arquivos sem cadeia `*연결파일`. O `SourceTextReader.ReadChain` para a leitura do arquivo atual ao encontrar essa diretiva, por isso um append depois dela seria ignorado. Fontes independentes são priorizadas.

## Não inclui

- Mudanças no Etervale C#, schema, assets, conteúdo do catálogo ou banco real.
- Modificações em nenhuma receita anterior, manifesto, relatório ou backup.
- Publicação automática: probes continuam marcados `probe_only` e são bloqueados pela publicação.

## Instalação

No diretório `~/Transferências/pt_asset_tool`:

```bash
unzip -o "$HOME/Transferências/ETERVALE_P0_CONTENT_AUTOPROBE_V31_2026-11-09.zip" -d .
python3 patches/aplicar_p0_content_autoprobe_v31.py --project-root "$PWD" --dry-run
python3 patches/aplicar_p0_content_autoprobe_v31.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_p0_content_probe_hotfix.py app/dev_tests/test_etervale_p0_closure.py
```

Execute **sem** `--auto` se precisar fazer uma escolha específica de arquivos; o parser conserva as flags `--item`, `--monster`, `--npc`, `--field` e `--execute`.

## Certificação no checkout real

```bash
python3 app/pt_asset.py etervale p0-content-probe --auto --execute --build
python3 app/pt_asset.py etervale p0-closure-audit
python3 app/pt_asset.py etervale ui-board
```

Esperado para conteúdo: `PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED` com alterações reais nas tabelas `OpenItem`, `Monster`, `NPC` e `Field`, zero novas referências inválidas, zero erros semânticos. Esperado no fechamento: `P0_AUTHORING_GATES_PASSED_NOT_RUNTIME_CERTIFIED`. **Esses estados não estão certificados antecipadamente pelo patch**; dependem da importação real no checkout do usuário.

As 81 verificações Python incluem 75 testes de regressão prévios mais 6 novos testes de seleção.
