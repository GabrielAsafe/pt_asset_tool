# Etervale V8 — Instalação

Pré-requisito: patch V7 instalado. Pare/reinicie o servidor web do Asset Tool para que o código Python novo seja carregado. Se um lote Blender estiver ativo, termine/cancele esse job antes de reiniciar o servidor.

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V8_WEB_ENTITIES_SMD_SETTINGS_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v8.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v8.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_v8_web_entities_smd.py
```

Se ocorrer `LOCAL_FILE_CONFLICT`, **não** use `--force` ou sobrescreva ficheiros de produção. Envie o log e verifique as modificações locais.

## O que testar na UI

1. Reinicie o servidor web; faça `Ctrl+Shift+R` no browser.
2. **Settings → Nomes in-game:** se a BD não for descoberta automaticamente, configure o caminho para o **SQLite existente do World Catalog** e clique “Validar e guardar BD”. Não use `baseline.sqlite`/`candidate.sqlite` de auditoria. Se a BD for PostgreSQL, o status informa que este leitor não é compatível.
3. **Entities → NPC:** procure `TN-008` e verifique se os nomes provenientes da BD aparecem acima do código. Quando o modelo tiver múltiplos NPCs, o cartão mostra vários nomes.
4. **Catalog → Previews SMD → Refresh status:** observe `READY`/`MISSING` e os logs. Em “Generate SMD previews”, o planeamento deve avançar e os `READY` não devem ser renderizados de novo sem alteração dos ficheiros. Se o contador não avançar, abra “Diagnóstico do lote e erros” e partilhe `Job`/`import.log`/`render.log`, sem presumir sucesso do Blender.
5. **Settings:** Run Doctor / Reindexar e evidências P0/P1; a aba “Etervale Validation” duplicada foi retirada.

Detalhes: `docs/etervale/V8_WEB_ENTITIES_SMD_SETTINGS.md`.

Este patch altera código/configuração do Asset Tool, não os assets Etervale nem a BD de produção.
