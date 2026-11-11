# P1 — checklist manual de runtime (não automatizado)

Aprovação pelo leitor C# não implica aprovação visual, física ou temporal. Executar em uma cópia de testes do Etervale (client + server) e guardar evidências de forma identificável (screenshot/vídeo/log com hash e data). Comparar com baseline; não publicar probes.

| Cenário | Observação mínima necessária | Prova |
|---|---|---|
| Ricarten `village-2.smd` | Textura base, segunda camada em piso/água, blend/transparência, UV, iluminação em materiais de referência | Captura e log; notar explicitamente `tem_wall04.bmp` |
| Acero | `Stand`, `Walk`, `Attack`, `Damage`, `Dead`; juntas, orientação, bind pose e ausência de deslizamento indevido | Vídeo curto de animações e frame/time |
| Arcuda | Repetir movimento principal, validar `marcuda.smb` versus `arcuda.smb` e associações corretas | Capturas/registro |
| BMP/TGA protegidas | Confirmar decodificação visual, alpha/opacity e ausência de fallback branco em assets usados | Captura antes/depois |
| Colisão e terreno | Checar paredes/solo do campo, colisão física e navegação; leitura das 319 faces de colisão não é prova de física | Vídeo e posição do avatar |
| Efeitos `.part` | Ao menos um efeito de partículas visível com texturas/tempo/BlendType corretos | Captura e log; export/import de `.part` não certificado pelo AssetDump |
| Performance | Registrar hardware, FPS e loading sob mesmas condições da baseline | Medição e logs comparáveis |

Somente após análise dessas observações, corrigir regressões detectadas e documentar aceite manual pode-se declarar qualidade visual em jogo. Sem essas provas, estado correto: `NOT_CERTIFIED`.

O Asset Tool deve continuar a preservar os bytes opacos (incluindo tail do Acero SMB), as identidades de entidades, o `Physique` e os formatos legados. Uma migração Blender/PBR é projeto separado.
