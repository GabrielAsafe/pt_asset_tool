# Etervale V8 — Entities, previews SMD e Settings

## Alcance

Patch incremental sobre V7. Não altera os assets reais do jogo, readers C#, WorldImport nem base de dados de produção. Mantém a BD existente como fonte de verdade para textos e nomes de entidades, sem introduzir Content JSON.

### Entities — nomes in-game

- `app/pt_asset_tool/etervale_entity_names.py` consulta **somente leitura** `npcs`, `npc_texts`, `monsters` e `monster_texts` do World Catalog SQLite nativo do Etervale (M028WorldCatalog).
- Procura uma BD SQLite válida em diretórios conhecidos junto ao GameServer. Se não descobrir a BD, ou se houver várias SQLite válidas, a interface exige indicar o caminho em **Settings → Nomes in-game · BD Etervale**. A configuração fica apenas em `app/pt_build/state/etervale_entity_names_db.json`.
- Um modelo pode ser utilizado por vários NPCs. `char/npc/TN-008` permanece como identificador físico; o cartão mostra os **nomes provenientes da BD** (quando comprovados) e a pesquisa aceita nome/código.
- Não tenta inferir nomes pelo nome da pasta nem por listas Summit/Content JSON. Não altera schema; bases PostgreSQL ainda não são suportadas por este leitor da UI.
- Bases `baseline.sqlite` e `candidate.sqlite` criadas por auditorias temporárias são **provas descartáveis**, não devem ser configuradas como a BD autoritativa.

### Previews SMD

- Corrige o índice mantido pelo servidor web, que anteriormente não observava novas gravações de `index.json` feitas pelo processo do lote. Agora valida a assinatura (inode/tamanho/mtime) e recarrega o índice; escrita atómica com bloqueio entre processos no Linux.
- Retira a invalidação generalizada de previews já `READY` durante `Reindexar`: só uma alteração verdadeira nas dependências deve invalidar o cache durante a classificação e renderização.
- Persistência incremental durante o planeamento (`planning_processed`, `total_candidates`, `selected_so_far`, `phase`) e apresentação de status/log do último job.
- O worker continua a produzir `preview.png`, `model.blend` e `preview.json` sob `app/pt_build/previews/smd_catalog/`; o índice de estado é `index.json`; o lote é descrito em `batch_state.json`. Um job interrompido pode ser retomado: Generate SMD previews não precisa regenerar previews cujo cache segue válido.
- **Não se afirma** que os milhares de modelos funcionam em Blender: se algum falhar, consulte **Diagnóstico do lote e erros** e os `import.log`/`render.log` do respetivo workspace.

### Manutenção e relatórios

- `Run Doctor` e `Reindexar` movidos para Settings; todos os IDs e handlers preservados.
- Removida a página iframe duplicada “Etervale Validation”; os resultados P0/P1 aparecem em Settings (somente leitura), além de Reports.
- O endpoint `/etervale-readiness` permanece funcional para retrocompatibilidade de links existentes, mas deixa de ser um destino da navegação principal.

## Validação do patch

- 132 testes Python nas suítes P0/P1/V5/V6/V7/V8 (fixtures isoladas).
- Testes de SMD com duas instâncias do gestor, simulando a separação servidor web/worker batch.
- Lote sintético: `READY` preservado, `MISSING` gerado, contadores persistidos.
- Chromium 390 px com fetch simulado: consulta de nomes, contadores, Settings, remoção do iframe.
- `node --check` passou para o `app.js`.

## Limitações

Nenhum teste do lote completo com 4.791 SMD nem do caminho real para a base SQLite/PostgreSQL do utilizador foi realizado no ambiente isolado. O recurso de nomes depende de o campo `model` do catálogo da BD apontar para a pasta de modelo correspondente. Não se modifica a BD de produção.
