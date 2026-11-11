# V31 — Seleção assistida de folhagem residual (Stage 0.72)

**Base:** V30 instalado. **Mapa de teste:** `Field/forest/fore-1.smd`.

## Motivação

No relatório V30 do utilizador: 99 instâncias experimentais LOD0, 4.817 faces antigas ocultadas, 21 candidatos de apoio em parede e 1.565 faces adicionais que partilham materiais associados à folhagem. Esse último número é apenas um *diagnóstico*: não prova que sejam todas folhas ou árvores.

## Fluxo de trabalho

1. Abrir `python3 app/pt_environment.py --map Field/forest/fore-1.smd`.
2. No painel **Modernizar ambiente**, executar **V30 → Testar todos grupos LOD0 (rever)** com *Ocultar árvores antigas* ligado.
3. Abrir **V31 → Selecionar folhas restantes**. Deixar marcado *Só materiais de folhagem* para apontar apenas a texturas suspeitas; desmarcar se for uma textura ainda desconhecida.
4. Premir **1. Clicar na face restante**; depois clicar numa folha antiga **dentro da vista 3D**. `Esc` ou botão direito cancelam a captura.
5. Em *Expandir*, escolher um dos quatro modos e premir **2. Mostrar seleção**. O objeto de destaque é uma **cópia das faces selecionadas**, não outra cópia do mapa. O Stage visível permanece a única malha V19.
6. Confirmar visualmente antes de premir **3. Ocultar selecionadas (reversível)**. Esse comando grava uma máscara V31 adicional para o Stage atual e atualiza só o modificador Geometry Nodes do proxy.
7. Se necessário, usar **Árvore extra LOD0 aqui** (apenas modos locais). Esta instância é experimental; a base poderá estar incorreta, especialmente junto às paredes. No máximo 8 instâncias adicionais por ensaio.
8. **Reverter máscaras extra V31** remove apenas as seleções V31 guardadas, sem afetar as 4.817 faces V30. **Restaurar árvores antigas** desliga a pré-visualização temporária sem apagar os JSON.

## Modos

- **Ilha do material:** componentes de faces ligadas por aresta, com a mesma textura. Bom para vegetação montada num único cartão.
- **Árvore local:** encontra faces dentro de um raio na vista, com o material selecionado ou outros materiais de folhagem indicados pela V22/confirmados na V27. **Não certifica troncos** e pode incluir duas copas próximas.
- **Textura inteira:** todas as ocorrências ainda visíveis da mesma imagem. Útil para testar material homogéneo; perigoso se reutilizado em paredes ou arbustos.
- **Folhagem inteira:** todas as ocorrências ainda visíveis dos materiais ligados à folhagem V22 ou explicitamente classificados FOLHAGEM/ARBUSTO V27. É um teste alargado, **não uma classificação definitiva**; requer clicar primeiro numa face reconhecida.

O filtro do clique usa a geometria **não modificada** do proxy, excluindo as faces já mascaradas. Clicar no modelo novo não o seleciona: o capturador procura especificamente uma face antiga no raio da câmara. Se a face visível não pertencer a uma textura V22/V27 suspeita, desligar *Só materiais de folhagem* e usar primeiro **Ilha do material**.

## Persistência e segurança

O resultado é gravado junto dos relatórios do mapa em `*.v31_residuais.json`, bloqueado ao `asset`, `source_sha256` e número de faces. Aprovações de publicação **não** são criadas. Reexecutar a pré-visualização V30 reaplica os índices extra V31 que já tenham sido explicitamente confirmados. A limpeza da V31 não apaga V22–V30.

Não existe exportação de SMD, modificação de UV, colisões, material-fonte ou escrita no cliente do jogo. A máscara é visibilidade de pré-visualização; se uma textura for usada em vários objetos, **não** a confirmar globalmente sem inspecionar o resultado.

## Limites conhecidos

- Os agrupamentos por proximidade baseiam-se nas posições 3D das faces do proxy e não provam que pertencem à mesma árvore. Uma seleção local não garante incluir o tronco.
- A máscara V31 exclui um máximo de 12.000 faces por seleção e 45.000 no total. Os limites protegem a memória do Blender.
- A operação LOD0 extra depende de `island_tree_01` preparado na V28 e da cena aberta, e não tem implantação certificada.
- A integração foi testada com Python (V21–V31), mas a interação de clique/modal e a atualização do modificador precisam de ser confirmadas no Blender Flatpak 5.2 do utilizador.
