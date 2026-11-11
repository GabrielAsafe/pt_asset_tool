# PT Asset Tool / Etervale — V7: superfícies nativas, AI_enhcance e partículas

**Alvo:** patch incremental após V6, `~/Transferências/pt_asset_tool`.
**Alterações no Etervale:** nenhuma. Não altera `Etervale-git`, arquivos do jogo, leitores C#, bases SQLite/Postgres, nem dados operacionais.

## Problema observado

A V6 deixou componentes históricos Summit acessíveis como workflows aparentemente obrigatórios: Audit 10 classes, Read source contracts, Client/Server General Census, agregado Summit, donors externos, World Closure Summit e editor Canonical. O backend `/api/contracts/analyze` realmente exige `source_root` e `reference_source_root` históricos. Isso **não é condição para a source Etervale**. Os 61 contratos do registry são um inventário heterogêneo, não provas de compatibilidade com o reader C#.

Ao mesmo tempo, o resolvedor Real-ESRGAN ignorava `AI_enhcance/realesrgan`, embora essa seja a pasta da instalação local. A execução batch forçava o modo Real-ESRGAN, com `--include-ui`, sem dar escolha clara ao operador. O editor de partículas usava um grid fixo inadequado a telas estreitas, inseria toda a resposta da lista numa única tabela e não controlava corridas entre requisições de inspeção.

## Mudanças V7

1. **Workspaces nativos**: Client/Server já não exibem os atalhos Summit `Audit 10 classes`, `Read source contracts` e `Census & Recovery`. Os elementos históricos são preservados no código para compatibilidade, mas ficam fora da navegação normal. A seleção antiga de workflow `census` guardada no `localStorage` volta à aba padrão válida.
2. **Fontes/donors**: o formulário `Source & evidence donors` foi movido para `Management Legacy > Fontes externas e donors — recuperação histórica opcional` (fechado por defeito). O `server_root` Etervale continua visível em `Server > Configuration`.
3. **Summit Canonical**: painel com detalhes fechados por defeito e os botões de publicação Summit desabilitados no HTML do contexto Etervale. Esta **não é uma alteração de autorização de backend**; ainda se deve rever endpoints históricos antes de expô-los na UI.
4. **World Closure legado**: aba e explorador Summit deixam de ser workflow normal, com preservação do código histórico. A edição Item/Monster/NPC/SPM/SPP/SPC permanece no Management Legacy. `Etervale Validation` continua a superfície de provas P0/P1 e WorldImport.
5. **Contract Registry**: identificado explicitamente como inventário histórico/avançado; `61/61` não é certificação da engine nem do WorldImport.
6. **Real-ESRGAN**: descoberta do binário em `AI_enhcance/realesrgan/realesrgan-ncnn-vulkan`, exigindo permissão de execução; descoberta de pares `.bin` + `.param` em `AI_enhcance/realesrgan/models`. O backend e CLI passam `--model-dir` ou resolvem o diretório automaticamente, quando disponível. Um novo `GET /api/enhancement/backend-status` mostra paths/modelos encontrados, sem alegar inferência Vulkan executada.
7. **Texture Enhancement global**: selector de backend Auto/Real-ESRGAN/Lanczos, seleção de modelo NCNN e opção explícita `include_ui`, desligada inicialmente. `Auto` pode usar fallback Lanczos; não é garantia de IA em todos os arquivos. O executável detectado e o modelo existente **não provam** driver Vulkan/compatibilidade do peso nem saída de qualidade.
8. **DEDXT/ReFocus/UnResize 1×**: os ficheiros `.pth` e pares `.ncnn` foram reconhecidos no layout mostrado, mas **não foram conectados ao executável Real-ESRGAN por presumida compatibilidade de arquitetura**. Material Lab pode continuar em staging, com autorização de publicar mapas bloqueada até a certificação do shader. Esses backends especializados continuam pendentes.
9. **Partículas `.part`**: CSS responsivo a 390px; listagem paginada 100 itens, contagem total, debounce de busca, prévia de carregamento e proteção contra respostas antigas; visualização limita a 150 linhas de propriedades por inspeção (editação avançada continua possível fora da lista); ETag para PNGs renderizados. A amostragem Blender é **uma sequência de imagens**, não a simulação nativa de emissores/gravidade/blend do Etervale.

## Provas disponíveis

- 120 testes anteriores P0/P1/V5/V6 **PASS** na reconstrução da toolchain; 5 testes novos V7 **PASS**: total **125**.
- `node --check app/pt_asset_tool/ui_static/app.js` **PASS**.
- Teste de browser Chromium com APIs simuladas e conteúdo local **PASS**: Web UI JS sem exceções, navegação, descoberta Real-ESRGAN, donors opcionais, paginação de 205 `.part`, viewport 390px sem overflow no grid de partículas.
- Nenhum executável Real-ESRGAN, Vulkan ou Blender da máquina do usuário foi testado pelo patch local. Sem teste de runtime do cliente Etervale.

## Critérios de validação na sua source

1. Instale o patch V7 via `--dry-run`, depois aplique-o. Execute pytest e reinicie a UI.
2. `python3 app/pt_texture_upscale.py capabilities` deve mostrar o executável local se ele for realmente executável; caso contrário use `chmod +x` **apenas após validar a origem do binário e com autorização**. Não se altera permissão automaticamente neste patch.
3. Verifique `/api/enhancement/backend-status` pela nova UI e confirme que o nome selecionado tem `.bin/.param`. Teste primeiro uma única textura pelo Catalog, em staging, antes de iniciar batch de milhares de arquivos. Não publique sem inspecionar o resultado.
4. `Server > Configuration` não deve exigir Summit/EU. `Management Legacy` apresenta fontes históricas apenas como opção avançada.
5. Em Particles, pesquise um `.part`, navegue páginas, inspecione, gere `Preview Plan`, confira se o Blender está configurado. `Generate Blender preview` continua sujeito ao tempo e às capacidades do Blender; não é playback runtime.

## Pendências reais

- API antiga de `contracts/analyze` ainda existe, explicitamente isolada do workflow normal, mas **não foi removida**. Revisar segurança antes de apagar/reabilitar operações históricas.
- Validação real em browser com backend Etervale, incluindo todos os 233 comandos e endpoints restantes, não foi feita; a V7 foca nos problemas relatados.
- Reorganização semântica completa de World Closure contra BD Etervale, ligação de novos assets a schema/identidades e player de partículas real no engine são projetos separados.
- A textura `tem_wall04.bmp` permanece como exceção documentada no cenário Ricarten. O patch não a cria, altera ou oculta.
