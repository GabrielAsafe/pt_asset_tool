# Summit Content Workbench v1

Objetivo: criar um inventário técnico completo e comparável do conteúdo Summit.

## O que cataloga

- arquivos de `SourceCode`, `cliente`, `Servidor`;
- modelos, texturas, áudio, partículas, mapas/stages, packs;
- JSON canonical de monsters/NPCs/items/quests/maps;
- todos os records dentro de packs `SCFG`;
- referências de assets encontradas em fontes/configs/modelos;
- tentativas da `runtime_asset_probe`;
- roots externos/donors, mantendo provenance separado;
- duplicados por SHA-256 e mesmo path com conteúdos diferentes.

## Saídas

`catalog.sqlite3` é a fonte principal para futuras ferramentas/editor.

Também gera:

- `assets.csv`
- `entities.csv`
- `scfg_records.csv`
- `runtime_assets.csv`
- `runtime_failures.csv`
- `donor_path_conflicts.csv`
- `duplicate_assets.csv`
- `category_summary.csv`
- `overview.json`
- `index.html`
- `balance_overrides.template.json`

## Scan do projeto atual

```bash
python3 SourceCode/tools/content_workbench/summit_content_workbench.py   --repo-root .   --out .summit_content_catalog
```

Para procurar referências internas também em todos os binários (mais lento):

```bash
python3 SourceCode/tools/content_workbench/summit_content_workbench.py   --repo-root .   --binary-strings   --out .summit_content_catalog
```

## Donors

Nunca misture o donor fisicamente com o projeto. Monte/extraia cada donor em uma pasta separada e declare:

```bash
python3 SourceCode/tools/content_workbench/summit_content_workbench.py   --repo-root .   --donor "donor_a=/dados/donors/server_a"   --donor "donor_b=/dados/donors/server_b"   --donor "client_old=/dados/donors/client_old"   --binary-strings   --out .summit_content_catalog
```

Assim cada arquivo e entidade conserva a origem.

## Arquitetura pretendida

O Workbench separa quatro camadas:

1. **Evidence** — donor/runtime/legacy são somente leitura.
2. **Catalog** — SQLite normaliza entidade, asset, hash, origem e uso.
3. **Overrides** — balanceamento/edições deliberadas vivem fora do donor.
4. **Compiler** — futuramente aplica overrides ao canonical e recompila packs.

A regra importante é: *donor não é canonical*. Donor é evidência/source material.

## Próximos módulos naturais

- editor visual de monsters/NPCs/items;
- diff de stats entre donors;
- grafo monster -> model -> textures -> sounds -> spawn maps -> quests -> drops;
- auditoria "asset existe mas nunca é usado";
- auditoria "runtime tentou carregar e não existe";
- importer assistido donor -> canonical;
- balance simulator;
- build/deploy com preview de diff e rollback.
