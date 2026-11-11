# V9 — Lotes seletivos de textura para Etervale

## Motivo

A V8 apresenta **Global Texture Enhancement** mas a operação web chama `texture-upscale run --all`, tornando difícil testar apenas uma pequena amostra. A V9 fornece um seletor por categoria e por ficheiro, sem alterar o processador de texturas existente.

## Operação

1. Client / Enrichment → Texture Enhancement.
2. Escolher uma categoria: **UI / Atlases**, World / Maps, Characters / NPCs, Items, Effects, Outros ou todas.
3. Opcionalmente filtrar pelo nome/caminho. A lista é ordenada e paginada em 100 ficheiros por página.
4. Marcar os ficheiros pretendidos ou escolher **Selecionar primeiros 4** para uma pequena amostra.
5. Selecionar o backend e, para UI/atlases, autorizar expressamente a inclusão de UI e confirmar o risco de recortes em píxeis.
6. **Gerar candidatos selecionados**: são enviados `--include-exact <caminho>` para cada ficheiro; nunca `--all`.
7. Consultar o Activity. O staging permanece em `pt_build/texture_upscale/runs`; publicação e rollback não foram alterados e continuam a exigir autorização de deploy separada.

## Garantias e limitações

- Os caminhos são fornecidos pela indexação do Catalog, em vez de nomes introduzidos livremente.
- No POST, cada caminho é revalidado quanto a existência, extensão, pertença ao catálogo e confinamento à pasta `client_root` (incluindo symlinks). É proibido enviar uma seleção vazia, repetida ou com mais de 100 ficheiros.
- A classificação de categorias é **heurística pelo caminho**, não uma certificação de que uma imagem é segura para upscale. A opção UI/Atlases é especialmente arriscada.
- A lista de ficheiros reflete o último índice Catalog. Se os ficheiros mudarem em disco, reindexar nas Settings.
- O backend Real-ESRGAN continua a exigir teste de inferência real no computador Etervale; descoberta do executável e modelos NCNN não é prova de funcionamento Vulkan.
- Nenhum ficheiro do cliente Etervale nem banco de dados é modificado pela criação do lote. Publicação continua sendo uma operação separada com backup e rollback.
- Não é um backend para pesos `.pth` DEDXT/ReFocus/UnResize, nem ativa PBR automaticamente.

## Validação executada em sandbox

- 138 testes Python passaram na regressão direcionada P0/P1/V5–V9, incluindo 5 novos testes para a seleção.
- `node --check` passou.
- Chromium (390 px, API simulada): seleção dos primeiros quatro, confirmação de risco UI e ausência de scroll horizontal passaram.
- O CLI foi exercitado em cinco PNGs sintéticos, selecionando quatro via `--include-exact`: produziu **quatro** candidatos, não o quinto, sem alterar a pasta original.
- A execução real de inferência Vulkan, publicação e UI com o cliente real depende dos testes na máquina do utilizador.

## Próxima etapa: modernização gráfica

Usar o checklist **Pipeline de Modernização Gráfica — Priston Tale + Blender** fornecido pelo utilizador. Auditar separadamente (1) dados que Blender pode produzir, (2) formato/roundtrip SMD/SMB/INX, (3) material loader C#, (4) shaders/renderer MonoGame, (5) validação em runtime. Só após reunir as provas produzir o plano de implementação; não assumir que a mera existência de texturas normais/height/PBR no disco significa suporte do renderer.
