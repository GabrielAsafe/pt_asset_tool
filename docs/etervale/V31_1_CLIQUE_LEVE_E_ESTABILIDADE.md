# Etervale V31.1 — clique assistido e revisão leve

## Compatibilidade

Correção incremental sobre V31. Mantém integralmente os JSON V21–V31, os 99 grupos V30, o mapa Stage 0.72 e os modelos-fonte. Não cria nem altera ficheiros do jogo. Nenhuma publicação de modelos no cliente Etervale.

## Porquê

Com 99 árvores LOD0 (~10 milhões de faces desenhadas), a cena é pesada, sobretudo em material preview. O operador V31 utilizava um único raio em cada clique e reconstruía o modificador Geometry Nodes ao confirmar qualquer seleção. O Blender também copiava os materiais e UVs de todas as faces destacadas. Isto prejudicava a usabilidade e aumentava o trabalho repetitivo. **Não há diagnóstico forense do crash** sem o ficheiro de falha nativo do Blender.

## Mudanças

- `Ocultar árvores 3D (modo leve)` e `Mostrar árvores 3D novamente`: apenas alternam a visibilidade das coleções temporárias V26/V28/V29/V30/V31, sem remover as instâncias, mudar o seu LOD ou tocar no Stage.
- Por defeito, ao clicar na face restante, a V31 oculta as árvores modernas para que as folhas antigas sejam mais fáceis de apontar. Para desativar, desmarca `Ocultar 3D novo ao selecionar`.
- `Tolerância clique (px)` de 0 a 20; o raio central tem sempre preferência, e depois são tentados raios próximos por ordem de distância. Valores altos podem escolher a folha vizinha; confirma a seleção destacada antes de ocultar.
- Destaque geométrico sem material nem UV: reduz alocações durante seleções grandes. Não cria uma cópia do Stage inteiro.
- A geometria de pesquisa é guardada em cache na sessão enquanto a malha não muda.
- Ao confirmar uma seleção, o JSON é escrito **antes** da atualização de máscara da cena. A operação apenas acrescenta os índices de faces a um atributo Boolean já existente, sem eliminar/recriar o Geometry Nodes. Se houver exceção Python, restaura o JSON anterior e o atributo afetado.

## Ordem de teste

1. Fazer cópia de segurança dos JSON da V31 antes de abrir (opcional; o instalador não os escreve).
2. Abrir com `python3 app/pt_environment.py --map Field/forest/fore-1.smd`.
3. Executar V30 (cobertura completa), se ainda não estiver ativo na sessão. O plano V30 reaplica automaticamente as máscaras V31 guardadas.
4. Abrir **Modernizar ambiente → V31**, clicar `Clicar perto da face restante`. As instâncias pesadas ficam escondidas, não apagadas.
5. Se o clique falhar, usar `Tolerância clique` 10–16px e desmarcar `Só materiais de folhagem` apenas se necessário.
6. Confirmar a seleção destacada, ocultar, repetir. Para comparar, clicar `Mostrar árvores 3D novamente`.
7. Se a vista ficar lenta, usar **Solid**, desligar overlays pesados e evitar renderizações com as 99 árvores LOD0.

## Crash

Os JSON da V31 são guardados a cada confirmação. Mesmo que o Blender feche abruptamente, não é necessário repetir as seleções já gravadas. Uma falha nativa do Blender pode deixar o estado visual não guardado; reexecuta V30 para reaplicar as seleções do JSON.

Se o crash persistir, recolhe o fim do terminal e procura `*.crash.txt` em `/tmp` ou na pasta configurada pelo Blender para relatórios de falha. **A V31.1 reduz riscos previsíveis, mas não garante ausência de falhas da GPU/driver/Blender.**
