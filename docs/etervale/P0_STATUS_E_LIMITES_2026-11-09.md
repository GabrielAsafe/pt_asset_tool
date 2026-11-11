# Registro das provas e do que não pode ser declarado concluído

Provas disponíveis antes da instalação V3:

- 51 testes Python originais P0/P1 aprovados no checkout do usuário.
- 10 testes adicionais de autoria nativa aprovados no checkout do usuário.
- `WorldImport` real aceitou e persistiu alteração `Field/Dcave.ase.spm`: `PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED`, sem novos `unresolved refs`.
- C# AssetDump original aceitou INX, SMD, SMB e TGA de Acero/Arcuda; prova de **leitura**, não de escritor.
- A auditoria binária encontrou um SMB Acero com ~211 KiB de bytes finais opacos que não podem desaparecer num writer.

Provas testadas no ambiente de montagem V3:

- 75 testes Python com todos os patches instalados.
- Operações cirúrgicas em Ricarten Stage e Acero/Arcuda Model, INX e SMB, verificando a integridade das regiões não editadas.
- Instalador reexecutável com pré-validação de hashes e backup.

Ainda exige execução no checkout de destino:

1. Reader C# sobre candidatos *alterados* gerados pela V3: SMD Stage, SMD Model, INX e SMB.
2. `WorldImport` para um item, um monstro, um NPC e um Field reais modificados apenas no overlay.
3. `p0-closure-audit` consolidando as provas.
4. Se for desejado publicar, plano autorizado e rollback testado primeiro numa cópia de teste, nunca com mutações experimentais de gameplay.

A criação de identidades novas e a edição livre de geometria/rigging não foram declaradas suportadas. Este patch não deve marcar o P0 como "runtime concluído" sem provas que ainda não possuímos.
