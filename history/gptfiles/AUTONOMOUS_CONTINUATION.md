# Continuação autónoma — R13 — 2026-09-02

A R13 muda deliberadamente a estratégia de validação manual. Microtestes do tipo “mover um vértice e repetir por objeto/LOD” deixam de ser o caminho recomendado de desenvolvimento; esse trabalho passa a ser automatizado e o utilizador só precisa executar um comando no ambiente que possui o client real + Blender.

## Evidência real incorporada

O log R12 reporta `priestess_c01_m5 / default / MsmC01` com candidate `PASS`, controlled edit automático revalidado, candidate reimportado no Blender, `HUMAN_VISUAL=PASS` para o mesmo artifact SHA-256 e `context_pass=true`. O artifact SHA reportado é `ff9bf4409d86732037776b3479743e6f82c580b21534254963763d7c15a28197`. Runtime/game e produção continuaram `false`.

Como os bytes do candidate/provenance/review `.blend` não foram enviados junto com o log, essa evidência é preservada como externa `PASS_REPORTED_REVIEWED`, não como artefacto revalidável dentro deste snapshot.

## R13: teste rigid de desenvolvimento totalmente automático

Novo comando:

```bash
python3 pt_asset.py validate rigid-profile-auto --all
```

Ou, para um profile específico:

```bash
python3 pt_asset.py validate rigid-profile-auto --profile priestess_c01_m5
```

O fluxo é isolado em:

```text
pt_build/devtest/rigid_profile_auto/<profile>/
```

Ele não usa/apaga `pt_build/blender_edits/generic_import` e não sobrescreve workspace artística.

Para cada profile canónico, o runner:

1. resolve profile → SMD + INX + SMB por identidade exata;
2. executa structural/preflight fail-closed;
3. importa o SMD rigid headless no Blender numa workspace devtest isolada;
4. aplica automaticamente uma deformação determinística distribuída a **todos** os meshes HIGH/DEFAULT/LOW do profile, sem alterar materiais/vertex groups/topologia por intenção;
5. executa `pt_blender_to_smd_free_mesh_v3.py` sequencialmente em todos os alvos sobre um único candidate combinado;
6. exige edição observada em todos os targets, zero non-target drift, zero unknown Physique bones e verifier sem erros;
7. grava provenance do candidate como `CANDIDATE_RIGID_STRESS_AUTOMATED_DEVTEST`;
8. reimporta o candidate headless em HIGH, DEFAULT e LOW;
9. verifica os meshes esperados, contagens, coordenadas finitas e presença de weights;
10. produz `result.json` por profile e `batch_result.json` agregado.

O terminal recebe somente um resumo. Os relatórios de writer/Blender ficam em `pt_build/devtest` para diagnóstico se houver FAIL.

## Segurança/maturidade

Um `PASS` desse devtest significa que o generic rigid writer sobreviveu a um stress real Blender automatizado no(s) profile(s) testado(s), incluindo os três LODs e reimport headless. Ele **não** equivale a runtime/game acceptance, não promove writer e não habilita client-write/deploy.

A revisão humana deixa de ser repetida por objeto. Ela volta a ser exigida apenas quando a pergunta for genuinamente visual/semântica ou quando se entrar no gate runtime/game/promoção.

## Próximo passo exato

Executar no ambiente real:

```bash
python3 pt_asset.py validate rigid-profile-auto --all
```

Enviar apenas o JSON final (ou `pt_build/devtest/rigid_profile_auto/batch_result.json`). Se der PASS em ambos os profiles, o próximo desenvolvimento deve usar esse resultado para decidir expansão para representatives NPC/Monster e/ou runtime/game gate; não voltar a micro-witnesses por vértice.
