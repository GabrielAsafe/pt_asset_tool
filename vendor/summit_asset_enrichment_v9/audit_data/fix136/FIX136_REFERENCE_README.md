# Fix 136 — Auditoria global de assets de skills (EU → Summit)

## Estado

**AUDITORIA ABERTA — SEM PATCH FUNCIONAL**

Este diretório não modifica a árvore ativa. O objetivo é levantar, localizar, reconciliar e posteriormente restaurar os assets de skills para **todas as classes e todas as tiers**, usando a source EU como referência primária.

Não marcar como RESOLVIDO enquanto os ficheiros físicos não forem localizados/deployados e validados no client.

## Problema observado

Durante os testes da Tier 5:

- Fighter/Pikeman/Archer precisaram usar ícones fallback porque os assets T5 canónicos não estavam disponíveis na base Summit;
- a Archer apresenta gameplay parcialmente funcional, mas sem os assets T5 próprios;
- a source Summit histórica não continha várias referências que existem na EU;
- Assassin e Shaman precisam ser incluídos na reconciliação, não apenas as oito classes originais.

## Escopo

Classes auditadas:

1. Mechanician
2. Fighter
3. Pikeman
4. Archer
5. Assassin
6. Knight
7. Atalanta
8. Priestess
9. Magician
10. Shaman

Tiers auditadas: **1, 2, 3, 4 e 5**.

Categorias de assets:

- ícones de skill `Button/*.bmp` e `Button/*_.bmp`;
- TGAs explicitamente associados a skills em `shared/skill.h`;
- ícones/timers adicionais referenciados em handlers;
- scripts de partículas `.part`;
- dependências transitivas dos `.part` (textures/models/etc.) — fase seguinte;
- roots e WAVs de efeitos por classe — associação fina por skill na fase seguinte;
- backgrounds/layout de páginas de skill quando aplicável.

## Primeira etapa — auditoria da source EU

### 1. Tabela canónica de skills

A EU possui uma tabela central em:

`shared/skill.h`

O inventário inicial encontrou:

- **10 classes**;
- **5 tiers por classe**;
- **4 skills por tier**;
- **200 skills** no total;
- **400 BMPs esperados** apenas para botões (normal + hover);
- **52 referências TGA explícitas** na tabela (`51` nomes únicos).

O client EU constrói os ícones com o padrão observado em `game/game/HUDController.cpp`:

`image\Sinimage\skill\<Classe>\Button\<button_base>.bmp`

`image\Sinimage\skill\<Classe>\Button\<button_base>_.bmp`

### 2. Tier 5 canónica

`results/EU_T5_EXPECTED_ASSETS.md` contém os 40 skills T5 e os 80 BMPs normais/hover esperados.

Observação importante:

- Mechanician/Fighter/Pikeman/Archer/Knight/Atalanta/Priestess/Magician usam T5 na faixa `100/103/106/110`;
- Assassin usa `TS80/TS83/TS86/TS90`;
- Shaman usa `MS80/MS83/MS86/MS90`.

### 3. Partículas/timers explicitamente referenciados

`results/EU_SKILL_EFFECT_ASSET_LITERALS.csv` contém a primeira varredura dos handlers de classe e handlers especializados de skill.

Foram encontradas **43 referências literais** (`34` caminhos únicos) nessa primeira passada, incluindo exemplos T5 como:

- `game\scripts\particles\MC5RuptureHit.part`
- `game\scripts\particles\MC5RuptureFinalHit.part`
- `game\scripts\particles\PS5RingOfSpears.part`
- `game\scripts\particles\Ac5FierceWind.part`
- `game\scripts\particles\Ac5FierceWindKeep.part`
- `game\scripts\particles\Ac5FierceWindProjectile.part`
- `game\scripts\particles\Ac5LethalSight.part`
- `game\scripts\particles\Ac5LethalSightKeep.part`
- `game\scripts\particles\R5SesmicImpact.part`
- `game\scripts\particles\R5StoneSkin.part`
- `Effect\Particle\Script\ShadowBomb.part`
- `game\scripts\particles\KS5HolyConviction.part`
- `game\images\skills\timers\Kn5_HolyConviction.tga`
- `game\images\skills\timers\Ac5_LethalSight.tga`
- `game\images\skills\timers\Ata5_SummonTiger.tga`
- `game\images\skills\timers\Pr5_IceElemental.tga`

Isto **não é ainda a lista completa de dependências físicas**: cada `.part` pode referenciar outras texturas/modelos/scripts internamente e precisa ser analisado recursivamente quando os ficheiros forem localizados.

### 4. Assassin e Shaman

A EU inclui as duas classes na mesma infraestrutura central de skill buttons. A T5 esperada é:

Assassin:

- `TS80 J_Bomb`
- `TS83 R_Slash`
- `TS86 V_Stab`
- `TS90 Storm`

Shaman:

- `MS80 Creed` (`Sh5_CREED.tga` também aparece explicitamente)
- `MS83 P_Deity`
- `MS86 G_Nail`
- `MS90 H_Regene`

Também existem handlers/partículas específicos para ambas, por exemplo `ShadowBomb.part`, efeitos `Alas/Inpes` para Assassin e `Migal*`, `BipPhantomRain.part`, `CreedStart/CreedKeep` para Shaman.

## Fase seguinte para a pesquisa de assets

1. Executar `scripts/check_client_assets.py` contra cada client/base histórica disponível.
2. Produzir matriz `PRESENT / MISSING / FOUND_ELSEWHERE` para os 400 botões.
3. Procurar os 52 TGAs explícitos por basename, sem assumir pasta.
4. Procurar todos os `.part` da primeira varredura.
5. Abrir cada `.part` localizado e extrair recursivamente texturas/modelos/scripts referenciados.
6. Auditar sons: partir dos roots em `results/EU_CLASS_SOUND_ROOTS.md` e associar os IDs/chamadas de `SkillPlaySound` a ficheiros físicos.
7. Comparar Summit atual, client histórico, EU e outras bases de referência por SHA-256 e dimensões.
8. Só depois criar patch/deploy de assets; não substituir ficheiros existentes sem verificar se são variantes intencionais.

## Evidência / resultados incluídos

- `results/EU_SKILL_BUTTON_ASSETS.csv` — 200 skills, todas as tiers/classes, dois caminhos BMP esperados por skill e TGA explícito quando presente.
- `results/EU_T5_EXPECTED_ASSETS.md` — resumo human-readable da T5 das 10 classes.
- `results/EU_SKILL_EFFECT_ASSET_LITERALS.csv` — assets literais encontrados nos handlers auditados.
- `results/EU_CLASS_SOUND_ROOTS.md` — roots de áudio das 10 classes.
- `scripts/audit_eu_skill_assets.py` — reextrai o inventário da source EU.
- `scripts/check_client_assets.py` — verifica um client físico contra o inventário.
- `evidence/source_reference.sha256` — hashes dos principais ficheiros EU usados como evidência.

## Critério de conclusão do Fix 136

O bugfix só pode sair de `AUDITORIA ABERTA` quando:

- os 400 botões esperados forem classificados;
- TGAs/timers forem classificados;
- partículas e dependências transitivas forem classificadas;
- sons relevantes forem classificados;
- as divergências Summit × EU forem documentadas;
- existir pacote de deploy separado e reversível;
- o client for testado com as 10 classes e páginas/timers/efeitos sem referências quebradas.
