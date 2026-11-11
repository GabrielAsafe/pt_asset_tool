# P0/02 — Adaptação do conteúdo canônico sem alterar leitores

**Decisão fixada:** o Etervale NÃO carrega diretamente `.scfg`, `.smap`, `.sres`, `.sfld` e demais packs Summit. Não alterar readers, não publicar packs, não executar `WorldImport import` contra a base real como teste.

`content-compat` registra o mapa de contratos. `content-draft` é um pequeno adaptador **explícito** JSON → texto nativo do `assets/GameServer` (não é conversor automático de packs Summit):

```bash
cd ~/Transferências/pt_asset_tool
python3 app/pt_asset.py etervale content-compat
python3 app/pt_asset.py etervale content-draft --spec /caminho/para/minha_definicao.json
```

Exemplo de arquivo JSON:

```json
{
  "format": "PT_ASSET_ETERVALE_NATIVE_AUTHORING_V1",
  "files": [{
    "path": "Monster/Exemplo.inf",
    "directives": [
      {"key": "*이름", "values": ["Exemplo"]},
      {"key": "*모양파일", "values": ["char/monster/Exemplo.smd"]},
      {"key": "*레벨", "values": [12]}
    ]
  }]
}
```

As saídas em CP949 e CRLF são gravadas **somente** em `app/pt_build/etervale/native_content/<id>/`. Destinos permitidos: `OpenItem/*.txt`, `Monster/*.inf`, `NPC/*.npc`, `Field/*.spm`. O arquivo de exemplo é **ilustrativo e incompleto**, não uma definição de monstro funcional. Para inserir uma entidade funcional ainda é necessário validar identidade, relações, textos, modelos, campos e importação do mundo em **banco descartável**. Packs Summit originais não têm conversão automática. Nenhum código C# é alterado.

A compatibilidade total do conteúdo canônico é **pendência ainda aberta**: este patch cria um caminho seguro de autoria incremental e a matriz de migração, não uma migração integral dos schemas.
