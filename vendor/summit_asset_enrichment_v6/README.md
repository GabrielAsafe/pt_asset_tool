# Summit Asset Enrichment

Pacote audit-driven para reconciliar/migrar assets para o Summit, mapear dependências cliente/servidor e montar um corpus pequeno para reverse engineering.

## Princípios

- **PLAN FIRST**: nenhum arquivo é alterado pelo comando `plan`.
- **missing-only por padrão**: arquivo existente não é sobrescrito.
- **proveniência**: SHA-256, origem, destino, perfil e justificativa ficam no manifest.
- **AUTO / REVIEW / BLOCKED**: somente `AUTO` é aplicado.
- **bytes preservados**: textos legados não são convertidos em massa para UTF-8.
- **sem cópia cega por extensão**: INX/SPP/SPC/SMD têm validações estruturais.
- **doadores permanecem intactos**: a operação é cópia, não remoção/move físico.

## 1. Ajuste os caminhos

Edite `summit_paths.json` se algum root mudou.

## 2. Gere o plano recomendado

```bash
python3 migrate_assets.py --config summit_paths.json plan \
  --out manifests/migration_plan.csv
```

Perfis default:

- `client-confirmed`
- `source-armors`
- `server-monsters`
- `server-npcs`
- `server-fields`

Veja também o resumo JSON criado ao lado do CSV.

## 3. Revise e aplique somente AUTO

```bash
python3 migrate_assets.py --config summit_paths.json apply \
  manifests/migration_plan.csv
```

`apply` recalcula SHA-256, valida novamente o formato e não sobrescreve arquivo existente por padrão.

## 4. Reconciliação histórica missing-only (opcional)

Use somente para reavaliar conteúdo faltante nos doadores históricos confiáveis (`previous_client`, `ptbr_antigo`, `ptbr_novo`):

```bash
python3 migrate_assets.py --config summit_paths.json plan \
  --profiles historical-missing-only \
  --out manifests/historical_missing_only.csv
```

Esse perfil não transforma ExMachina/Priston em fonte de bulk-copy.

## 5. OpenItem faltante (somente REVIEW)

```bash
python3 migrate_assets.py --config summit_paths.json plan \
  --profiles server-openitems-review \
  --out manifests/openitems_review.csv
```

Os 14 itens do lote antigo auditado aparecem como revisão; conflitos e itens sem prova não são autoaplicados.

## 6. Grafo de dependências

```bash
python3 build_dependency_graph.py --config summit_paths.json \
  --out-dir dependency_graph
```

Saídas:

- `dependency_graph/nodes.csv`
- `dependency_graph/edges.csv`
- `dependency_graph/graph.json`
- `dependency_graph/summary.json`

Para uma passagem rápida, sem varrer todo o cliente:

```bash
python3 build_dependency_graph.py --config summit_paths.json \
  --skip-client-scan --out-dir dependency_graph_fast
```

## 7. Corpus de reverse engineering

```bash
python3 collect_reverse_samples.py --config summit_paths.json \
  --per-type 3 --out summit_reverse_samples.zip
```

O ZIP inclui amostras pequenas por filetype, hashes, proveniência e relatório de `reverse_inspect.py`. O objetivo é comparar gerações/estruturas sem zipar árvores inteiras.

Inspeção individual:

```bash
python3 reverse_inspect.py /caminho/arquivo.inx
```

## 8. Writer seguro já conhecido: SPP

```bash
python3 create_known_files.py spp --json start_points.json --out mapa.spp
python3 create_known_files.py inspect mapa.spp
```

SPP Summit canônico = 200 registros de 12 bytes (`state`, `x`, `z`) = 2.400 bytes. O writer não tenta criar SPC, INX ou Stage SMD porque esses formatos exigem mais semântica/validação.

## Documentação

- `docs/MIGRATION_POLICY.md`
- `docs/FILETYPE_RELATIONSHIPS.md`
- `docs/CREATING_NEW_CONTENT.md`
- `docs/WRITER_REVERSE_MATRIX.md`
- `docs/SOURCE_FINDINGS.md`
- `docs/GAPS_AND_BUGFIX_CANDIDATES.md`

## Segurança operacional

Antes do primeiro `apply`, faça snapshot/backup dos roots Summit. O próprio migrador é conservador, mas runtime continua sendo o árbitro final para conteúdo legado.

## Correções v2 (pós-primeiro apply)

- `collect_reverse_samples.py`: a seleção agora é indexada por **label + side + root + extensão**. Isso evita misturar o `exmachina/client` com `exmachina/server` quando ambos usam o mesmo label.
- `migrate_assets.py apply`: o destino é reconstruído a partir de `target_rel` e do root configurado, preservando o casing real das pastas existentes (`tmABCD` em vez de criar/usar `tmabcd`).
- cópia de asset agora prioriza identidade de bytes e usa escrita temporária + replace; metadados antigos incompatíveis com o filesystem não tornam a cópia fatal.
- em caso de erro, o `apply` imprime `errors_by_side`, `errors_by_profile`, `errors_by_detail` e até 12 exemplos.
- novo comando para diagnosticar um log anterior:

```bash
python3 migrate_assets.py --config summit_paths.json diagnose \
  manifests/migration_plan.apply.csv
```

É seguro reexecutar o mesmo manifest em modo missing-only: arquivos já copiados aparecem como `PRESERVE_EXISTING` e não são sobrescritos.

## Reverse corpus v3

A v3 adiciona análise de ABI e coleta por referências. Para gerar um corpus melhor que o primeiro ZIP:

```bash
python3 collect_reverse_samples.py --config summit_paths.json \
  --per-type 3 --max-followed 250 --out summit_reverse_samples_v3.zip
```

O coletor agora inclui `.ini`/`.in`, segue referências literais e tenta incluir o INX de mesmo stem de cada model INI resolvido.

Para resumir qualquer corpus:

```bash
python3 analyze_reverse_samples.py summit_reverse_samples_v3.zip \
  --out-dir reverse_analysis
```

O relatório separa INX `LEGACY_120`/`MODERN_172`, SPP 50/200 records e decodifica SPC/SPM.

## v4 — runtime dependency closure

A v4 distingue **nome lógico de authoring** e **arquivo físico de runtime**. No source Summit atual, `smModelDecode("foo.ini")` tenta `foo.inx`; por isso a ausência física de `foo.ini` não significa bundle quebrado.

O coletor v4 segue também os aliases de runtime provados pelo source:

- `foo.ini` / `foo.in` -> `foo.inx`
- `INX.szModelFile = foo.ASE` -> `foo.smd`
- `INX.szMotionFile = motion.ASE` -> `motion.smb`
- `INX.szLinkFile` / `szTalkLinkFile` -> `.inx`
- `INX.szTalkMotionFile` -> `.smb`
- `SMD/SMB` -> texturas referenciadas

Use:

```bash
python3 collect_reverse_samples.py --config summit_paths.json --per-type 3 --max-followed 600 --out summit_reverse_samples_v4.zip
python3 analyze_reverse_samples.py summit_reverse_samples_v4.zip --out-dir reverse_analysis_v4
```

O ZIP gerado inclui `closure_report.json`, que registra cada dependência como `RESOLVED` ou `MISSING`.

## v5 — authoring scaffold + runtime validator

O corpus v4 fechou o gate: 21/25 definições analisadas têm a cadeia visual essencial `INX -> SMD/SMB` presente. A partir daqui, o fluxo deixa de ser coleta aleatória e passa a ser authoring controlado.

A v5 inclui `character_bundle_tool.py`.

Gerar um spec de exemplo:

```bash
python3 character_bundle_tool.py example --kind monster --out monster.json
python3 character_bundle_tool.py example --kind npc --out npc.json
```

Criar o scaffold server-side a partir de um `.INF/.NPC` conhecido e funcional:

```bash
python3 character_bundle_tool.py scaffold monster.json --out generated/my_monster
```

Isso gera a definição server-side, `.zhoon`, contrato visual e, quando configurado, fragmento SPM ou request de SPC. O script **não** renomeia nem sintetiza INX/SMD/SMB; esses binários continuam no pipeline certificado do PT Asset Tool.

Validar os assets visuais nas duas árvores Summit:

```bash
python3 character_bundle_tool.py validate monster.json \
  --config summit_paths.json \
  --out generated/my_monster/validation.json
```

O validator exige INX `MODERN_172`, resolve as dependências SMD/SMB e verifica texturas BMP/TGA/DDS/JPG/JPEG/PNG embutidas.

A v5 também corrige a resolução de `.zhoon`: `*연결파일` é relativo ao diretório do `.INF/.NPC`, exatamente como `GetDirectoryFromFile()` faz no source atual.

## v6 — texture closure, SPC clone writer e instalação transacional

O corpus v5 fechou 16 bundles realmente utilizáveis como referência nativa Summit. Reanalise o corpus com o gate novo:

```bash
python3 analyze_reverse_samples.py summit_reverse_samples_v5.zip \
  --out-dir reverse_analysis_v6
```

O resumo diferencia:

- `basic_runtime_complete`: root INX + SMD/SMB;
- `runtime_texture_complete`: toda a cadeia INX recursiva + texturas;
- `summit_ready_complete`: closure completo + localization + todos os INX em `MODERN_172`.

### Fluxo recomendado para um personagem novo

1. Gere o scaffold:

```bash
python3 character_bundle_tool.py scaffold npc.json --out generated/MyNpc
```

2. Coloque os outputs do PT Asset Tool em `generated/MyNpc/client/`, preservando os paths de runtime.

3. Espelhe somente a cadeia visual comprovadamente necessária para o servidor:

```bash
python3 character_bundle_tool.py mirror-visuals npc.json \
  --bundle-dir generated/MyNpc
```

4. Para NPC fixo em mapa, gere uma cópia patchada do SPC. **O target Summit ainda não é alterado nesta etapa**:

```bash
python3 character_bundle_tool.py spc-patch npc.json \
  --config summit_paths.json \
  --bundle-dir generated/MyNpc
```

Modo automático usa somente slot completamente zerado. Para reutilizar conscientemente um registro `code==0` que ainda contém dados históricos, informe `spc.slot_index` no spec.

5. Valide o staging completo:

```bash
python3 character_bundle_tool.py validate-stage npc.json \
  --bundle-dir generated/MyNpc \
  --out generated/MyNpc/stage_validation.json
```

6. Gere o plano de instalação:

```bash
python3 character_bundle_tool.py install-plan npc.json \
  --config summit_paths.json \
  --bundle-dir generated/MyNpc \
  --out generated/MyNpc/install_plan.json
```

O plano só recebe `safe=true` se toda a cadeia visual e os arquivos server-side passarem. Arquivo já existente com SHA diferente vira `CONFLICT`; a única substituição admitida automaticamente é o SPC produzido pelo próprio `spc-patch`, desde que o SHA-256 do target ainda seja exatamente o hash base registrado.

7. Aplique:

```bash
python3 character_bundle_tool.py install-apply \
  generated/MyNpc/install_plan.json \
  --out-log generated/MyNpc/install_apply.json
```

8. Rollback, se necessário:

```bash
python3 character_bundle_tool.py rollback \
  generated/MyNpc/install_apply.json
```

O rollback remove somente arquivos cujo SHA ainda é o instalado pela transação e restaura o backup do SPC somente se ele também não foi modificado depois.
