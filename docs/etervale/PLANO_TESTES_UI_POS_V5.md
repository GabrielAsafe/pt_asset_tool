# Próxima etapa — Validação integral da UI

Este documento é um plano, não uma certificação. A V5 gera `migration_audit/*.surfaces.json` com a lista observável de CLI e endpoints `/api/`.

## Critérios por página e ação

- Tela abre sem erro, feedback real para opções e estados vazios/sem configuração.
- Ação GET não escreve em assets, no repositório C# ou banco de produção.
- Ação POST de staging é confinada ao `pt_build`; recusa path traversal e symlinks.
- Ação de publicação exige aprovação de plano, prova, hash e rollback, ou é desabilitada com justificativa.
- Compatibilidade de formatos legado Summit é apresentada explicitamente sem insinuar suporte no Etervale.
- Alterações de root `Etervale-git` refletem na UI e CLI; não fazer fallback silencioso para servidor Summit antigo.
- Erros de dependências (ex.: `tem_wall04.bmp`) são apresentados sem ocultação.
- Navegação, labels, acessibilidade, serialização e eventos testados em desktop e mobile.

## Ordem proposta

1. Enumerar as páginas/telas e rotas reais, vinculando às chamadas Python.
2. Testes unitários de APIs e repositórios simulados.
3. Testes e2e do frontend com browser e ambiente descartável.
4. Testes com assets reais somente leitura em Etervale e WorldImport descartável.
5. Certificar ou bloquear cada ação de edição/publicação com relatório de cobertura.

## Depois: Content JSON

Adaptador read-only primeiro. Nunca substituir dados nativos nem misturar fontes de verdade sem matriz de IDs e regras de resolução.
