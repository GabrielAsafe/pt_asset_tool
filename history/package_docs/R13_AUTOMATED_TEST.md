# R13 — teste automático a executar

Na pasta `app` do snapshot R13, execute **um único comando**:

```bash
python3 pt_asset.py validate rigid-profile-auto --all
```

Não é preciso abrir/editar Blender manualmente. O comando usa Blender em background e testa todos os profiles canónicos, todos os meshes HIGH/DEFAULT/LOW e o reimport dos três LODs.

Quando terminar, envie o JSON mostrado no terminal ou o arquivo:

```text
pt_build/devtest/rigid_profile_auto/batch_result.json
```

Esperado em caso de sucesso:

```text
status=PASS
automatic_only=true
failed_profiles=[]
production_authorized=false
client_write_authorized=false
client_modified=false
```

Não execute deploy/apply nem copie candidates para o client.
