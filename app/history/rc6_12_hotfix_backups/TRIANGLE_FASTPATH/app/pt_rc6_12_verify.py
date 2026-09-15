#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

EXPECTED = {'app/dev_tests/test_protected_tga_variants.py': '5ff635b69e120acc8aa15644f97a9452b6089603b25d484663ab4a97391e916e', 'app/history_py/pt_smd_blender_import_v3_static_armature.py': '84236c83708275c9c324204bcfeadd2af06d7c0098b7e3f9ba1c2741d76423e8', 'app/pt_asset_tool/animation_source_regression.py': '6ef9313b2c0721dc30cdf0d33632ca34d3be36f637334aa0eac9bb7f950ed1ea', 'app/pt_asset_tool/blender/bake_actions.py': '1fe1bb2199d749f2585906e4c3462308e69185a07960ce1c3ce21bf3dcbcb7ba', 'app/pt_asset_tool/motion_core.py': 'd4403c2f9a5dd35270d5527d1223bdf82d954b0d1293a7b081ce2c2daa879b9b', 'app/pt_asset_tool/multilayer_texlink.py': 'f6a3336bcae0c0a8b5df480d55cf0b9dd30a26a9e189cc4b3c395dc7a5928c4c', 'app/pt_asset_tool/registry.py': '67e81273f36713c1583f38d881d032b8bc6ae726fa750a43110b04ecfc398ef1', 'app/pt_asset_tool/rigid_context_census.py': '77a23af7c5f787746efd379b7be4d9cb582ce516974781c03aad80d4feb3d0b6', 'app/pt_asset_tool/stage072_corpus.py': 'aead188936276b0358cd7fb37e86e70d37ee8507ce4850c610fcc959db2b101d', 'app/pt_asset_tool/standalone_rigid_devtest.py': 'c9fb969c6f43c59be93f40c6deecb1c2f81b9f4a7176021b1f6bcd7ff3e925d7', 'app/pt_asset_tool/static_semantic_devtest.py': 'cfa22a308b68e0ac85cc3fe01dbd9b34127bf66408991a55f8807f757ea727c9', 'app/pt_asset_tool/texture_codec_devtest.py': 'df772afeef2ec6d5d03ce7aa3a4bc667d2906be27ad2b08baeb3be976ae19c8b', 'app/pt_asset_tool/writer_corpus_audit.py': '9ca17f3d16fae8722abb86d0605a9aaee5586c563c080a47bf91983eb5496dc6', 'app/pt_blender_to_smd_free_mesh_v3.py': 'a478d0ba036ea1e16ed92f12dad27b521aa8573593dfac4833d19a7e9a7c1448', 'app/pt_character_structural_gate_v2.py': '466180a23b29ee8c050d78ea53abce98170237a2703aed5ed9b8e8ea706a270b', 'app/pt_pikeman_smd_material_audit_v1.py': '5d8b5331f0a97aca99000ac55583710beefdf65c41eebe12ab95c3fe69314050', 'app/pt_protected_tga_v1.py': '9ce8b79596e6a45104ca93e373844bdd735af158a3c7708781b642a42e47d6a7', 'app/dev_tests/test_rc6_11_autonomous.py': '04d7426379eda932bff9a5c90d4e88d71c09aae185931c53437796a593b33a81', 'app/dev_tests/test_rc6_12_motion_batch.py': 'edce87efafc63bd145775916118597db99ae822c8be03b7a9aa950492baa355f', 'app/RUN_RC6_12_LOCAL_FOCUSED.sh': '470d968bc3d44ec2dd89610e365b94cc47b00e4841498ff097c6fcbd0e187f83'}
HISTORY = {'app/history/rc_tools/RUN_RC6_10_RIGID_CONTEXT_DELTA.sh': '754fd30bb7522a67074d6d5741d27dd3f6c4c7dfc862fa80f92a9d521907a77f', 'app/history/rc_tools/RUN_RC6_5_5_STATIC_FOCUSED.sh': 'a9dc0aceec89e4f1f34e0bee665c1d610b198ff7e6ee58c37425e5f51d1da31c', 'app/history/rc_tools/RUN_RC6_6_STATIC_FOCUSED.sh': '5dcd486dadaa3f2a8042c02277a5c5c298cc66edc25f3c364a95e66242d25b6b', 'app/history/rc_tools/RUN_RC6_7_MODEL062_FOCUSED.sh': '5c50a2a3a2494453a4f181c8505b067ce932b944880600719b58d21014ad960e', 'app/history/rc_tools/RUN_RC6_8_MODEL062_FOCUSED.sh': '3edd761fb6ef16a1c1217389204b9b5de3ea5e38f6fd50f29dfbf5672da566c4', 'app/history/rc_tools/RUN_RC6_9_MODEL062_DELTA.sh': '7695d9f028139491e0581d27cfc3548f59371654c511fa6e43cb98d242fb1210', 'app/history/rc_tools/pt_model062_delta_rc6_9.py': '09f3d8679512f6c5c5696bcaa48a4d939b9e68a6ab26a43a566d9236e81faba7', 'app/history/rc_tools/pt_model062_focused_rc6_7.py': '2da809f51da1e28d669eb7cbf1e486a7c72ec602c50ab4e4e1ead5c808c4ba88', 'app/history/rc_tools/pt_model062_focused_rc6_8.py': '5678f0d3407370f5b8b1f99c7f266eeda0b249041f2ebdc567439402e609e623', 'app/history/rc_tools/pt_model062_inventory_refresh_rc6_8.py': '8143eb79248d05d368e1e3a2c9add99f2152f35ab297f07e4771d9760d845262', 'app/history/rc_tools/pt_model062_inventory_refresh_rc6_9.py': '81c39ce6c91cf7da9a78321b53809aac8ad3f1e3f528c6745a4cadf931c0aef2', 'app/history/rc_tools/pt_rc6_10_verify.py': '1e6c50974e54033aee0bf2eb4b2df6c08afbf0930dc9ef2c420eacf02429b131', 'app/history/rc_tools/pt_rc6_5_5_recover.py': '6eafc6c64f53feb3e5b447149f3c393840d886b2aaef84678c4ae9b44d216594', 'app/history/rc_tools/pt_rc6_5_5_verify.py': '4c15da6684aed755fe169ebe3f19269dc330bf87d1d37a6ede422bab05334ced', 'app/history/rc_tools/pt_rc6_6_verify.py': 'ba7984edf88cbf088db5c30e2d25c04673894a30bf67fdaaae69dd4a9764e5fb', 'app/history/rc_tools/pt_rc6_7_verify.py': 'e03cfc6a0be7373778cd3e486cf525dfb9537c108cebccac89cf1dce11284a66', 'app/history/rc_tools/pt_rc6_8_verify.py': '65f54a3dbda371064a14abe6e2d7bb582f00512793ca625a8092f889327df0db', 'app/history/rc_tools/pt_rc6_9_verify.py': 'b65ad828ce1c9f145e3cba36e5565a6e43fd04d1b2ad33dc95f54c2caa027be8', 'app/history/rc_tools/pt_rigid_context_delta_rc6_10.py': '46237bce77b7671049c01c6eff0b27d2f55236a73dce9a3fb6fd2a06855e0f24', 'app/history/rc_tools/pt_snapshot_manifest_rc6_10.py': '409eff392b8da98be367515bef8963956b82bf4693faedb555a47e1273a4da4c', 'app/history/rc_tools/pt_snapshot_manifest_rc6_9.py': '47e1e144d9ae9ce603415be5cef74abf3e5cc6b976e521cdb8b0c0356353732e', 'app/history/rc_tools/pt_snapshot_manifest_reconcile_rc6_8.py': '06f40daf222c150a98469cf529ed5122b2358d21b12a69f455a8ed600ca05c7a', 'app/history/rc_tools/pt_static_focused_rc6_5_5.py': '486f8bf17360a8f85283088b98d2125d625fea95063a3353af0be719f13226c9', 'app/history/rc_tools/pt_static_focused_rc6_6.py': 'afd6a150b6310167e6a09ad5e45d5d03ed42919b65ef5b4474d74da9a96e7186'}
REMOVED = ['app/RUN_RC6_10_RIGID_CONTEXT_DELTA.sh', 'app/RUN_RC6_5_5_STATIC_FOCUSED.sh', 'app/RUN_RC6_6_STATIC_FOCUSED.sh', 'app/RUN_RC6_7_MODEL062_FOCUSED.sh', 'app/RUN_RC6_8_MODEL062_FOCUSED.sh', 'app/RUN_RC6_9_MODEL062_DELTA.sh', 'app/pt_model062_delta_rc6_9.py', 'app/pt_model062_focused_rc6_7.py', 'app/pt_model062_focused_rc6_8.py', 'app/pt_model062_inventory_refresh_rc6_8.py', 'app/pt_model062_inventory_refresh_rc6_9.py', 'app/pt_rc6_10_verify.py', 'app/pt_rc6_5_5_recover.py', 'app/pt_rc6_5_5_verify.py', 'app/pt_rc6_6_verify.py', 'app/pt_rc6_7_verify.py', 'app/pt_rc6_8_verify.py', 'app/pt_rc6_9_verify.py', 'app/pt_rigid_context_delta_rc6_10.py', 'app/pt_snapshot_manifest_rc6_10.py', 'app/pt_snapshot_manifest_rc6_9.py', 'app/pt_snapshot_manifest_reconcile_rc6_8.py', 'app/pt_static_focused_rc6_5_5.py', 'app/pt_static_focused_rc6_6.py']

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--current-root', type=Path, default=Path(__file__).resolve().parents[1])
    a=ap.parse_args()
    root=a.current_root.resolve()
    errors=[]
    version=(root/'app/VERSION.txt').read_text(encoding='utf-8').strip() if (root/'app/VERSION.txt').is_file() else None
    if version!='0.13.0': errors.append(f'version={version!r}')
    readiness_path=root/'CURRENT_READINESS.json'
    if not readiness_path.is_file():
        errors.append('CURRENT_READINESS.json missing')
    else:
        rd=json.loads(readiness_path.read_text(encoding='utf-8'))
        for k in ('production_authorized','client_write_authorized','server_write_authorized'):
            if rd.get(k) is not False: errors.append(f'{k} must be false')
        if rd.get('status')!='NOT_RELEASE_1_0': errors.append(f"status={rd.get('status')!r}")
    for rel, expected in EXPECTED.items():
        p=root/rel
        if not p.is_file(): errors.append(f'missing {rel}'); continue
        actual=sha256(p)
        if actual!=expected: errors.append(f'hash {rel} expected={expected} actual={actual}')
    for rel, expected in HISTORY.items():
        p=root/rel
        if not p.is_file(): errors.append(f'missing history {rel}'); continue
        actual=sha256(p)
        if actual!=expected: errors.append(f'history hash {rel} expected={expected} actual={actual}')
    for rel in REMOVED:
        if (root/rel).exists(): errors.append(f'historical top-level tool should be absent: {rel}')
    if errors:
        print('RC6_12_VERIFY=FAIL')
        for e in errors: print(' - '+e)
        return 2
    print(f'RC6_12_VERIFY=PASS key_files={len(EXPECTED)} history_files={len(HISTORY)} removed_top_level={len(REMOVED)} safety=LOCKED')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
