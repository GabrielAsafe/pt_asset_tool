> **HISTÓRICO:** este documento é anterior à certificação 1.0.0. Para estado atual use `START_HERE.md`, `CURRENT_READINESS.json` e `docs/RELEASE_1_CERTIFICATION.md`.

> **STATUS NOTE — 2026-09-14:** este documento é um checkpoint histórico de 2026-09-12. O smoke manual posterior abriu `RUNTIME-PK-T1T4-01` e `UI-ALIAS-MECHA-01`; use `START_HERE.md`, `VALIDATION_STATUS.md` e `docs/CURRENT_STATUS_2026-09-14.md` como estado corrente.

Summit Asset Enrichment • estado autoritativo após RC6.17.2

Data de consolidação: 12 de setembro de 2026

| Versão ativa        | 0.13.0                                                   |
|---------------------|----------------------------------------------------------|
| Status              | NOT_RELEASE_1_0                                          |
| Estado offline      | READY FOR FINAL MANUAL SMOKE WITH DOCUMENTED LIMITATIONS |
| Árvore autoritativa | ~/Transferências/current                                 |
| Próximo passo       | 1 sessão manual de smoke → gate final → pacote 1.0.0     |

**Objetivo deste documento: permitir retomar o projeto em outro chat sem reabrir investigação já encerrada.**

# 1. Estado autoritativo atual

| **Área**         | **Estado**     | **Observação**                                                          |
|------------------|----------------|-------------------------------------------------------------------------|
| Produto          | READY PRE-1.0  | PT Asset Tool R14 / Summit Asset Enrichment; versão ativa 0.13.0.       |
| RC6.16           | PASS           | Gate consolidado pré-1.0 passou; 12 recoveries certificados em staging. |
| Documentação     | PASS / CURRENT | RC6.17.2 atualizou o current e preservou o schema do verifier.          |
| Housekeeping     | PASS           | 139 itens de arquivo, 7 itens da raiz e 351 caches removidos.           |
| Cliente/Servidor | UNCHANGED      | Nenhum gate de certificação escreveu no cliente ou servidor real.       |
| Release 1.0      | PENDING        | Falta smoke manual final e um único gate final de certificação/package. |

**Fonte única de verdade:** /home/gabriel/Transferências/current

- Snapshot autoritativo criado após a limpeza: /home/gabriel/Transferências/asset_tool_armazem/current_0.13.0_pre_1_0_authoritative_2026-09-11.zip

- SHA-256 do snapshot: 2fc313f965acaf73b7ae4486818844d7018493a2ac8aae575c2682527bf812a6

- CURRENT_READINESS.json mantém status=NOT_RELEASE_1_0 e as três autorizações de escrita/produção em false.

# 2. Caminhos e roots relevantes

| **Uso**                   | **Path**                                                              |
|---------------------------|-----------------------------------------------------------------------|
| Current autoritativo      | /home/gabriel/Transferências/current                                  |
| App                       | /home/gabriel/Transferências/current/app                              |
| Build/staging             | /home/gabriel/Transferências/current/app/pt_build                     |
| Arquivo/snapshot          | /home/gabriel/Transferências/asset_tool_armazem                       |
| Cliente real — read-only  | /home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente |
| Servidor real — read-only | /home/gabriel/Área de Trabalho/summit/Servidor                        |
| Source atual              | /home/gabriel/Área de Trabalho/summit/SourceCode                      |
| Referência EU source      | /home/gabriel/armazem/priston/PristonTale-EU-main-master              |
| Donor PT_EU client        | /home/gabriel/armazem/priston/servidor_cliente_PT_EU/Files/Game       |
| Donor PT_EU server        | /home/gabriel/armazem/priston/servidor_cliente_PT_EU/Files/Server     |
| Donor Official            | /home/gabriel/old/velho                                               |
| Donor ExMachina server    | /home/gabriel/armazem/priston/ExMachina/server                        |

# 3. O que foi feito e fechado

## 3.1 Base RC6.12–RC6.14

- RC6.12 consolidou a base de rigid/texture/motion e passou o focused portable gate 33/33.

- Rigid históricos foram fechados, incluindo StylishUniform, muspel, Phoenix, LizardDoor, Enzo e ar0nDrac.

- ar0nDrac foi finalmente fechado por binding MULTI_CONTEXT_BOUND, com authoring genérico fail-closed.

- Player scale witness, Blender importer/writer e deployment mechanics em staging foram provados sem alterar o cliente.

- fpt-01.tga foi corrigido com o caso TGA20 extension area off-by-one. ch_tree1.tga e m_fury.tga permaneceram deferidos.

- Motion27 terminou com 8 anomalias semânticas/bounds deferidas e explicitamente não “forçadas” a PASS.

## 3.2 Política de escopo

- Mixed Physique foi decidido como NOT_CERTIFIED / OUT_OF_SCOPE para Release 1.0, release_1_blocking=false e backlog pós-1.0.

- Assassin/Shaman foram mantidos fora do escopo do 1.0 atual: runtime principal continua com oito classes ativas.

- O produto permaneceu 0.13.0 durante toda a certificação; versões 0.14.x/0.17.x serviram apenas como fonte seletiva de contratos/cobertura.

## 3.3 RC6.15 — contratos, classes e runtime

- Integração seletiva dos Asset Contracts: source contracts/paths, contract graph, skill census, player-class motion contract, agregação/superset e parser fields.

- Player-class aggregate: CORE_READY_STAGING_WITH_OPTIONAL_GAPS; core_unresolved_count=0; optional_review_count=112.

- Assassin/Shaman: 40 skills auditadas; branch deferido porque runtime atual não implementa as duas classes e MAX_JOBNUM=8.

- Legacy8: 160 skills auditadas. As 4 lacunas recuperáveis eram apenas 8 BMPs dos botões de Mechanician.

- Deep Audit Legacy8 inicialmente marcou 117 runtime edges como missing; a investigação de loader/registry provou que eram falsos positivos. Reconciliation final: 117/117 fechados, 0 blockers de asset runtime comprovados.

## 3.4 Loader/registry: provas técnicas que fecharam falsos blockers

- AssaSearchRes usa busca por resName e primeiro match em ordem ascendente de AssaRes; LoadAssaRes carrega primeiro image//Sinimage//AssaEffect e depois Effect//AssaEffect.

- 11 gaps de ASE eram falsos: o runtime usa fallback smASE/SMD; todos os SMD derivados existiam. Não gerar/converter ASE.

- star06B_04.bmp foi fechado como later divergent copy shadowed/nonblocking usando precedência de registry, não por igualdade de bytes.

- Duas referências full-path provaram que literais curtos como flare.tga/Star.tga podem ser chaves de registry e não paths diretos.

## 3.5 Missing19 → Recover4 → Missing11

- Missing19 encontrou 19 rows / 15 texturas únicas: 4 recoveries exatos PT_EU e 11 texturas lógicas restantes.

- Recover4 overlay foi fisicamente provado: 4 transições FAIL→PASS, donor hash = staged hash, target real inalterado.

- Model Texture Exact Path Chain provou a cadeia SMD material → smTexture.Add → ReadTextures → new_smCreateTexture → PathFileExists/fopen usando o Name preservado. Conclusão: exact path é obrigatório.

- Missing11 Reachability classificou 2 strong exact references, 2 basename-reference review e 7 sem evidência estática atual. Ausência estática NÃO foi tratada como unreachable.

- Strong2 lineage mostrou que não havia substituição automática segura para Ribbonhopy/Packjjangpy.tga nem Tfhd02t/TfhD02b.bmp.

## 3.6 ExMachina / DDS

- Ao tratar /ExMachina/server como donor root explícito, os dois modelos apareceram como variantes diferentes do target e migradas para DDS.

- Tfhd02t ExMachina referencia TfhD02a.dds + TfhD02b.dds; bundle estruturalmente completo 2/2 e loader atual tem suporte DDS.

- Ribbonhopy ExMachina referencia Packjjangpy.dds + Monhobi.dds + Ribbonhopy_1.dds; só 2/3 existiam no root esperado. Packjjangpy.dds teve candidatos de basename, mas sem lineage certificada.

- Decisão para 1.0: NÃO adotar troca especulativa de SMD/DDS. Esses casos entram como known limitation, sem inventar recovery.

## 3.7 RC6.16 — consolidação pré-1.0

- Um único gate consolidado substituiu a sequência de micro-audits.

- Foram staged 12 recoveries já certificados: 4 Historical Recover4 + 8 Mechanician UI8.

- Classificação final offline: OFFLINE_READY_FOR_FINAL_MANUAL_SMOKE_WITH_DOCUMENTED_LIMITATIONS.

- Cliente/servidor reais permaneceram inalterados.

## 3.8 RC6.17.2 — documentação e limpeza

- Foi detectado que a documentação de current ainda refletia 6/9; RC6.17.2 atualizou-a para o estado RC6.16 preservando o schema do verifier.

- As tentativas RC6.17 e RC6.17.1 falharam de forma segura e fizeram rollback antes de qualquer delete: primeiro por README_SNAPSHOT.md não rastreado no manifest, depois por substituição indevida do schema de CURRENT_READINESS.json.

- RC6.17.2 passou: 139 itens de archive removidos, 7 itens PT Asset na raiz removidos e 351 caches removidos.

- Snapshot autoritativo novo foi criado antes da exclusão externa.

- pt_build foi depois limpo manualmente, mantendo apenas o que ainda tem utilidade funcional ou de release.

# 4. Estado atual de pt_build após a limpeza

> pt_build/  
> ├── aggregate/  
> ├── asset_contracts/  
> ├── deploy_transactions/  
> ├── devtest/ \# volátil; pode ser recriado  
> ├── pre_1_0_consolidated_gate/  
> ├── pre_1_0_consolidated_gate.zip  
> ├── pt_asset_tool/  
> ├── rc6_12_install.json  
> ├── rc6_17_2_authoritative_docs_housekeeping/  
> └── ui_jobs/

- aggregate/, asset_contracts/, pt_asset_tool/ e ui_jobs/ foram preservados porque podem participar do estado/build operacional.

- deploy_transactions/ foi preservado como evidência da mecânica transactional/rollback.

- pre_1_0_consolidated_gate/ é a fotografia consolidada que sustenta o release candidate.

- rc6_17_2_authoritative_docs_housekeeping/ registra a limpeza bem-sucedida.

- devtest/ é volátil e pode reaparecer após verificadores/processos; não confundir com regressão do housekeeping.

# 5. Recoveries que entram no candidato 1.0

## 5.1 Historical Recover4 — 4 ficheiros

- char/tmABCD/LLhead.tga

- field/forest/07-g9 copy.bmp

- char/monster/Kakoa/Kakoa_BB copy.tga

- Char/Monster/Monrebion/Mon-Rebion-1.bmp

## 5.2 Mechanician UI8 — 8 ficheiros

- image/Sinimage/skill/Mecha/Button/TM100 Rupture.bmp

- image/Sinimage/skill/Mecha/Button/TM100 Rupture\_.bmp

- image/Sinimage/skill/Mecha/Button/TM103 Parasit_Shot.bmp

- image/Sinimage/skill/Mecha/Button/TM103 Parasit_Shot\_.bmp

- image/Sinimage/skill/Mecha/Button/TM106 Hardening_Shield.bmp

- image/Sinimage/skill/Mecha/Button/TM106 Hardening_Shield\_.bmp

- image/Sinimage/skill/Mecha/Button/TM110 Magnetic_Discharge.bmp

- image/Sinimage/skill/Mecha/Button/TM110 Magnetic_Discharge\_.bmp

**Importante:** esses 12 ficheiros foram provados em staging, mas ainda não foram escritos/deployados no cliente real pelo fluxo de certificação.

# 6. Known limitations e fora de escopo para 1.0

| **Área**        | **Estado**                   | **Observação**                                                                                          |
|-----------------|------------------------------|---------------------------------------------------------------------------------------------------------|
| Missing11       | KNOWN LIMITATION             | 11 exact-path texture gaps; sem recovery seguro certificado. Não promover basename/variant por palpite. |
| ch_tree1.tga    | DEFERRED                     | Sem header/container plausível ou sibling transform exato.                                              |
| m_fury.tga      | DEFERRED                     | 8236 bytes zerados; nenhum patch codec justificado.                                                     |
| INX x8          | DEFERRED                     | 8 casos semantic/bounds; tolerâncias não foram relaxadas.                                               |
| Mixed Physique  | NOT_CERTIFIED / OUT_OF_SCOPE | Explicitamente não bloqueia 1.0; backlog pós-1.0.                                                       |
| Assassin/Shaman | OUT_OF_SCOPE                 | Não implementados na linha atual das oito classes; não bloquear 1.0.                                    |
| ExMachina DDS   | KNOWN LIMITATION             | Tfhd02t bundle completo e Ribbonhopy incompleto; replacement não adotado sem runtime validation.        |

# 7. O que falta para 1.0

1.  Executar uma única sessão manual de smoke no cliente real, feita pelo utilizador.

2.  Se o resultado for FINAL_SMOKE_PASS, executar um único gate final de certificação/package.

3.  Gerar um pacote independente 1.0.0 com checksums, release notes, known limitations, escopo e snapshot/freeze final.

4.  Somente depois do gate final alterar versão/status para 1.0.0 / Release 1.0.

**Checklist do smoke manual:**

- Cliente abre e login/start funciona.

- Mundo carrega sem crash ou regressão visual global.

- As oito classes ativas carregam normalmente.

- Movimento + ataque básico nas oito classes.

- Pelo menos uma skill comum por classe, observando efeito e som.

- Mechanician: observar a área de Rupture, Parasit Shot, Hardening Shield e Magnetic Discharge quando o release candidate com os 12 recoveries for aplicado/testado.

- Não é obrigatório caçar Ribbonhopy/Caravana ou Tfhd02t; se aparecerem naturalmente, observar corrupção visual.

> FINAL_SMOKE_PASS
>
> FINAL_SMOKE_FAIL: \<descrição curta do problema\>

# 8. Regras operacionais e de segurança usadas no projeto

- production_authorized=false.

- client_write_authorized=false.

- server_write_authorized=false.

- Nenhuma escrita direta no cliente/servidor real durante auditoria/certificação.

- Staging, drafts, cache e reports ficam sob app/pt_build.

- Nunca relaxar tolerância para obter PASS.

- Nunca promover REVIEW, NON_TRS, basename-only, candidate ou ambiguidade para PASS sem prova.

- O assistente nunca lança, clona para execução, instrumenta, anexa debugger, strace/ptrace ou executa o cliente/jogo. Todo teste runtime/game é manual do utilizador.

- Ausência em scan estático não é prova de unreachable.

- O runtime/source atual da Summit é autoridade para as oito classes ativas; referência EU serve como evidência/donor, não como verdade superior quando existe drift.

- Donor recovery exige path/lineage/equivalência adequada; mesmo basename não basta.

- Não gerar/converter asset apenas para “fazer passar” quando o loader já prova fallback ou quando não existe equivalência.

- Antes de apagar housekeeping histórico, criar snapshot autoritativo e passar verifier/package.

- CURRENT_READINESS.json é também contrato consumido por verifier: preservar top-level keys/safety/status e acrescentar extensões de forma compatível.

- SNAPSHOT_SHA256SUMS.txt só deve ser atualizado para ficheiros realmente rastreados; README_SNAPSHOT.md pode não estar no manifest.

- Não instalar/exigir pytest no ambiente; preferir gates portáteis sem dependências externas.

# 9. Preferências de execução/comunicação aprendidas

- O utilizador quer alta autonomia: investigar e consolidar sem pedir confirmação desnecessária.

- Só pedir teste físico quando ele for realmente necessário para fechar uma hipótese que não pode ser resolvida offline.

- Evitar sequência de micro-ZIPs/micro-audits; preferir gates consolidados que reduzam trabalho manual.

- Quando fornecer comandos, o bloco deve conter somente a parte iniciando com bash; nunca incluir gabriel@host\$ no bloco.

- Não repetir perguntas cuja resposta já existe no histórico/logs.

- Tratar current como fonte única de verdade após housekeeping.

- Pacotes importantes devem incluir RESUME_NEXT_CHAT.md, PROJECT_STATE_DUMP.json, TEST_SUMMARY.md e SHA256SUMS.json.

- Não chamar algo de Release 1.0 antes do smoke final + gate final + pacote independente 1.0.0.

# 10. Principais aprendizados técnicos deste chat

| **Aprendizado**                                       | **Implicação**                                                                                                                                                                                           |
|-------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Scanner não é runtime                                 | O Legacy8 mostrou que um scanner pode marcar 117 “missing” e ainda assim nenhum ser blocker real. Loader semantics e registry behavior têm prioridade sobre heurística textual.                          |
| Exact path realmente importa                          | Para materiais SMD, a cadeia atual preserva o path em Name e abre esse path diretamente. Isso tornou os Missing11 gaps reais no nível de ficheiro, embora nem todos sejam reachability/runtime blockers. |
| Registry keys podem parecer paths                     | AssaSearchRes usa resName e resFullName; basename literals podem ser chaves para recursos preloaded, por isso não se deve tratá-los automaticamente como direct filesystem opens.                        |
| ASE aparente pode cair em SMD                         | smASE cache fallback provou que 13/13 casos tinham SMD suficiente. Criar ASE teria sido correção errada.                                                                                                 |
| Precedência fecha duplicata divergente                | star06 demonstrou que byte divergence posterior pode ser irrelevante quando first-match registry precedence está provada.                                                                                |
| Donor root importa                                    | ExMachina/server precisava ser tratado como root lógico; scan amplo de ~/armazem/priston mascarava relações de path.                                                                                     |
| Formato alternativo exige bundle, não arquivo isolado | ExMachina migrou modelos para DDS. Um DDS isolado sem modelo/lineage não é recovery seguro; model + referências + companions formam o bundle.                                                            |
| Schema de readiness é API interna                     | CURRENT_READINESS.json não é só texto humano. Alterar sua estrutura quebrou o verifier; a atualização correta preserva contrato e acrescenta extensão.                                                   |
| Housekeeping deve ser transacional                    | As duas primeiras tentativas falharam antes do delete e fizeram rollback. A ordem correta é: backup docs → editar → rehash tracked → verify → snapshot → delete → verify final.                          |
| Estado pré-release precisa ser simples                | Depois de dezenas de probes, o valor maior veio de consolidar decisões, documentar limitations e reduzir o restante a smoke + certificação final.                                                        |

# 11. Itens que NÃO devem ser reabertos antes do 1.0

- Mixed Physique — decisão de escopo já tomada.

- Assassin/Shaman — não implementar antes do 1.0 salvo mudança explícita de escopo.

- Os 8 INX deferidos — manter limitation; não relaxar parser/tolerância.

- ch_tree1.tga e m_fury.tga — manter limitation se o smoke não revelar impacto crítico.

- star06 — já fechado por precedência; não voltar a comparar cópias como blocker.

- ASE “faltantes” cobertos por smASE/SMD fallback — não gerar ASE.

- Os 117 Legacy8 runtime missing originais — já reconciliados 117/117.

- Replacement ExMachina SMD/DDS — não adotar para 1.0 sem evidência runtime adicional; atual política é limitation.

- Micro-audits de cada Missing11 — encerrados como investigação pré-1.0; só reabrir se smoke ou bug real apontar para um deles.

# 12. Pacotes/checkpoints de maior importância histórica

| **Marco**                   | **Pacote**                                                                           | **SHA-256**                                                      |
|-----------------------------|--------------------------------------------------------------------------------------|------------------------------------------------------------------|
| RC6.12 Cumulative           | PT_Asset_Tool_R14_RC6_12_CUMULATIVE_2026-09-05.zip                                   | 7dd1384e2d72fe8870d97eca3f61829bfcb9c907a587e6a7cbb5533ea1bb089c |
| RC6.12 Portable Focused     | PT_Asset_Tool_R14_RC6_12_PORTABLE_FOCUSED_GATE_2026-09-06.zip                        | af7f3fd9e694ec77404c255664ee1fed12e9ed489380026fc42584eea6446a1e |
| RC6.14 Offline Checkpoint   | PT_Asset_Tool_R14_RC6_14_OFFLINE_CHECKPOINT_2026-09-06.zip                           | d3c9ee01991eb9ad492e1a99b36d6780b9567dab27f6abb1b9c0340c4f455ac2 |
| RC6.15 Asset Contracts      | PT_Asset_Tool_R14_RC6_15_ASSET_CONTRACTS_INTEGRATION_2026-09-06.zip                  | 422dcee48da07383db45e5c5fa7e73fc2d723cf2de021b2532f03edc01684320 |
| Legacy8 Reconciliation      | PT_Asset_Tool_R14_RC6_15_LEGACY8_RUNTIME_CLOSURE_RECONCILIATION_2026-09-11.zip       | 058cd4428d7ab7ffd67e44826704344a4d50a3ca00922e1865f53cba47ac0cd3 |
| Recover4 Overlay            | PT_Asset_Tool_R14_RC6_15_RECOVER4_OVERLAY_PROOF_2026-09-11.zip                       | 7e138a1363eba128f117af24b35931fab280b23e210c4b17ea042af56c5de581 |
| Strong2 Lineage             | PT_Asset_Tool_R14_RC6_15_STRONG2_TEXTURE_LINEAGE_AUDIT_2026-09-11.zip                | 64e10a6024808de29e6e7ee520fd5a9af9158b0e7ea3f71fe5cdb4364cab27ae |
| RC6.16 Pre-1.0 Consolidated | PT_Asset_Tool_R14_RC6_16_PRE_1_0_CONSOLIDATED_GATE_2026-09-11.zip                    | 85a93fcbc8e8ab51359ab7bf160f9bcf22011474c8bf032ff37cdaa31b31833e |
| RC6.17.2 Housekeeping       | PT_Asset_Tool_R14_RC6_17_2_AUTHORITATIVE_DOCS_HOUSEKEEPING_SCHEMA_FIX_2026-09-11.zip | 99675450de35c23a4880e62d9c9f477eaa5000f20b0e6763973097105566548a |

**Nota:** o housekeeping removeu muitos pacotes históricos externos. Esta tabela serve como registro documental, não como garantia de que todos esses ZIPs ainda existam no filesystem após a limpeza.

# 13. Bugs/nuances ainda conhecidos no código

- CLI default de player-class audit ainda tem bug histórico: sem --class usa Assassin/Shaman em vez de TARGET_CLASSES. Pode ser corrigido no freeze final se ainda existir no current, mas não justificar nova investigação ampla.

- REFERENCE registry drift para as classes legacy é explicitamente nonblocking quando o current runtime está estabelecido.

- P2 discovery/source gaps não devem ser promovidos para PASS automaticamente, mas também não são blocker sem evidência runtime atual.

# 14. Procedimento recomendado para o próximo chat

1\. Ler primeiro START_HERE.md, CURRENT_READINESS.json e VALIDATION_STATUS.md do current autoritativo.

2\. Assumir que todas as decisões “não reabrir antes do 1.0” deste documento continuam válidas.

3\. Se o utilizador ainda não fez o smoke final, pedir apenas o resultado consolidado; não gerar novo audit offline por padrão.

4\. Se FINAL_SMOKE_PASS: preparar imediatamente o gate final de certificação/package e o pacote independente 1.0.0.

5\. No gate final, manter fail-closed: os 12 recoveries entram apenas por proveniência já certificada; known limitations entram documentadas; nada especulativo é promovido.

6\. Se FINAL_SMOKE_FAIL: investigar somente o sintoma reportado, sem reabrir branches independentes.

# 15. Bloco curto de retomada para copiar para outro chat

> Projeto: PT Asset Tool R14 / Summit Asset Enrichment.  
> Current autoritativo: /home/gabriel/Transferências/current  
> Versão ativa: 0.13.0; status NOT_RELEASE_1_0.  
> RC6.16 consolidado: PASS, offline ready for final manual smoke with documented limitations.  
> RC6.17.2 housekeeping: PASS; docs current atualizados, schema do verifier preservado, snapshot autoritativo criado e lixo externo removido.  
> 12 recoveries certificados em staging: Recover4 (4) + Mechanician UI8 (8). Ainda não escritos no cliente real pelo fluxo de certificação.  
> Legacy8 runtime missing originais: 117/117 reconciliados; 0 blockers current-runtime comprovados.  
> Mixed Physique = NOT_CERTIFIED/OUT_OF_SCOPE; Assassin/Shaman fora do escopo do 1.0 atual.  
> Known limitations: Missing11, 2 TGA deferidos, 8 INX deferidos, ExMachina replacement DDS não adotado.  
> Não reabrir micro-audits antes do 1.0 salvo bug real no smoke.  
> Regras: production/client/server writes=false; assistant nunca executa/instrumenta o jogo; runtime tests são manuais do utilizador; não relaxar tolerâncias; basename/candidate/REVIEW não vira PASS sem prova.  
> Falta: 1 smoke manual consolidado. Se FINAL_SMOKE_PASS -\> 1 gate final -\> pacote independente 1.0.0.  
> Comandos enviados ao utilizador devem aparecer em bloco contendo somente \`bash ...\`, sem prompt shell.

**Fim do handoff. O objetivo agora é convergir para 1.0, não continuar expandindo a investigação pré-release.**
