# Fix 136 — diagnóstico da execução v7

Este relatório foi derivado dos CSV/JSON produzidos pela execução real enviada em 2026-09-05. Não inventa resultados das três árvores; os números abaixo vêm do run v7.

## Resultado observado

- Assets auditados: **543** (485 base + 58 dependências `.part`).
- Target idêntico: **352**; target em conflito: **3**; encontrados fora do target: **184**; ausentes em todas as sources: **4**.
- Staging v7: **130 staged** e **54 recuperáveis retidos** por regras conservadoras.
- Proveniência do target: dos 352 `PRESENT_TARGET_IDENTICAL`, **todos os 352** têm bytes presentes em `previous_client_base`; **351** são exclusivos dessa source e **1** hash também existe em `pt_eu_files`. Isto torna `/home/gabriel/old/velho` o baseline de compatibilidade mais forte para assets legados deste target.

## Os 54 retidos pela v7

- **32** botões Mechanician T1–T4: falso nível de ambiguidade causado pelo alias físico `Mechanician` → `Mecha` nas donors, combinado com variantes de bytes EU/old. V8 seleciona old pela linhagem do target e mantém o destino runtime canónico `Mechanician`.
- **4** scripts `.part` (`MigalEnd`, `MigalMember`, `MigalStart`, `ShadowBomb`): existem por path exato no old e têm variantes nas outras donors. V8 mantém o bundle old, coerente com a linhagem do target.
- **17** recursos transitivos de `.part`: a v7 inventava implicitamente destinos ao lado do script para refs soltas como `flare.tga`. V8 seleciona o recurso do mesmo donor do `.part`, privilegia `Effect/Particle` quando há colisões e usa o path físico runtime da donor, removendo wrappers configurados como `Game/`.
- **1** TGA `As2_VENOM.tga`: o destino é inferido dos peers Assassin já presentes no target como `image/Sinimage/skill/keep/As2_VENOM.tga`.

## Conflitos já existentes no target — preservar

- `Mc2_MAXIMIZE.tga` — target SHA-256 `5288fe35c9d1e2c66585646aeb292ec0b3efebbfa2802b2da75d5acb9751d170`; PT_EU selecionado pela v7 `df5f7302987c73db1641752edae680bec49be18d5174ce51a3fd4530d9ff44b7`. Como o target já contém bytes que não coincidem com nenhuma donor localizada, V8 não sobrescreve automaticamente.
- `Mc4_COMPULSION.tga` — target SHA-256 `0cdaff4029c65f4090639475fced42e75c253b5e5333168e7137adb7659280bd`; PT_EU selecionado pela v7 `c87231ce7df61505660503819a35474f8dcdf1aa19b988759b52868eadcfc5c1`. Como o target já contém bytes que não coincidem com nenhuma donor localizada, V8 não sobrescreve automaticamente.
- `Pr4_R_FIELD.tga` — target SHA-256 `0cdaff4029c65f4090639475fced42e75c253b5e5333168e7137adb7659280bd`; PT_EU selecionado pela v7 `3eee71d9de7a20fc16cf49ad7743ca2a9d55b2fd7407ba819d7cfa2b9cc76b1d`. Como o target já contém bytes que não coincidem com nenhuma donor localizada, V8 não sobrescreve automaticamente.

## Assets ainda realmente ausentes

- `image/Sinimage/skill/Fighter/Button/TF26 WarCry_.bmp`
- `image/Sinimage/skill/Fighter/Button/TF26 WarCry.bmp`
- `game/scripts/particles/BipPhantomRain.part`
- `game/scripts/particles/R5StoneSkin.part`

A v8 gera `fix136_near_matches.csv` para estes quatro casos, procurando nomes semelhantes recursivamente nas três sources. As sugestões fuzzy são apenas evidência e nunca são staged automaticamente.

## Expectativa para a próxima execução v8

Mantendo as mesmas árvores e os mesmos ficheiros físicos, a v8 deve converter os **54 bloqueios recuperáveis** em decisões de staging fundamentadas. Assim, o total esperado é **184 assets recuperáveis staged** e apenas os **4 verdadeiros missing** permanecem sem source. O número exato deve ser confirmado pelo novo run porque a closure dos `.part` é recalculada a partir dos ficheiros reais.
