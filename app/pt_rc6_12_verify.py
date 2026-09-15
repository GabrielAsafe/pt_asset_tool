#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

EXPECTED = {'VERIFY_PACKAGE.sh': '6d889d5b9268917f3a20c1b1348463b4f42a0237a0eab8b9a85f91816a62dfed',
 'app/RUN_RC6_12_LOCAL_FOCUSED.sh': '470d968bc3d44ec2dd89610e365b94cc47b00e4841498ff097c6fcbd0e187f83',
 'app/dev_tests/test_client_manifest_evidence.py': 'd77ea87d9e40b199fb5a68400b10b03f33a0cad2ea50d822901fc562b5ebc39a',
 'app/dev_tests/test_general_asset_census.py': '36c89a882784f4a6520279a2fd4771ad59604e8d32767aeb7686d3f3c66e2d98',
 'app/dev_tests/test_general_asset_census_helpers.py': '9743c357426b8e50d35cea5358201a8f9b44bbb90f09eeb7672ded70c2f56fa8',
 'app/dev_tests/test_general_asset_recovery.py': '7e611c7cc24e4f4261283c9b2f33f69c6042c074c2ac0ebd4e553508eb6f32b3',
 'app/dev_tests/test_model062_legacy_import_compat.py': '15113c1db659a5d1dbfb2de3a4a028c246b5de9a7e35578ad77a2bbe87f20c13',
 'app/dev_tests/test_protected_tga_variants.py': '6d6583f84d27455937dd9a0172aebd7bbba486847990b0a75ca728e0dfca3b15',
 'app/dev_tests/test_rc6_11_autonomous.py': 'e90c005488f8fce4927e171c4a29e2e56cf5c0a1b23780a7c6b692881829e897',
 'app/dev_tests/test_rc6_12_motion_batch.py': 'edce87efafc63bd145775916118597db99ae822c8be03b7a9aa950492baa355f',
 'app/dev_tests/test_registry_multi_context_binding.py': '126b9f2404c0dd44d5edb2aef382d4916c4e093c7def2c5ff402ff684162df53',
 'app/dev_tests/test_release_1_auto.py': '84b683ad62f08b274bfda30bb4166e8fe37650d8bbe47917083ce9840f6a1b08',
 'app/dev_tests/test_release_1_coverage.py': 'eb9cb7281abd8f7a46f1524a48eb3d11fea8cdba071b268a4ab0344dc2615771',
 'app/dev_tests/test_rigid_context_census.py': 'a7928a2e8c3baa8c997b958bd8c16babe796ea5b3158e20b08e24169beda97c0',
 'app/dev_tests/test_server_bundle_census.py': '052100fdf03f75eb01e2d5ab6fb5a5bcf4f7d708ec5a378e1c2d1b07e1c34fc4',
 'app/dev_tests/test_server_lifecycle.py': '6e35f18101206e00d4da8405f3cc8b0e91281b9f3873127cfab238b48b8dac49',
 'app/dev_tests/test_server_ui_integration.py': '8bfbd6ab7047b924a93ba4410e98ebe48afe0daf4fb12d9be60b8df9a28332cb',
 'app/dev_tests/test_ui_semantic_taxonomy.py': '5c4fffe1188e5a695e5d09dee3649dfbd8b0df7b64f0d8a7a8ff34d9db5643b9',
 'app/dev_tests/test_vendor_spm_semantics.py': 'beb8474aefc85be80642e91ad3ccd89b36a7ac29bbb4d5723e4bc1a8625987a9',
 'app/history_py/pt_smd_blender_import_v3_static_armature.py': 'dc705a86e6bb0552cca3f8a378dca7268396709c376dfa8ec7f722e0b6e8ca88',
 'app/pt_asset_tool/aggregation.py': '237bacdcbadadb8987e4ccaabd86c7818172000b83fff9a455513a177afd9382',
 'app/pt_asset_tool/animation_source_regression.py': '6ef9313b2c0721dc30cdf0d33632ca34d3be36f637334aa0eac9bb7f950ed1ea',
 'app/pt_asset_tool/app_config.py': 'f7b6ca716fa5b21c3538b75c1ea42959e121b180c94e5a552be3bac99f62ca8d',
 'app/pt_asset_tool/authoring.py': 'be5bd13b176c4c78955028c06daf591627273c5e4d0f7e0740506a70e7f02b6a',
 'app/pt_asset_tool/blender/apply_rigid_profile_devtest.py': '7d4de232a13f0195a10bdc79e895d4bda82c894f866daa6977a8eda6e213a164',
 'app/pt_asset_tool/blender/authoring_session_save.py': '47d7c623c9b19ae7d34e3a59c5d5362afc34f1ef9a1574f4bd21fb621f75ab21',
 'app/pt_asset_tool/blender/bake_actions.py': '1fe1bb2199d749f2585906e4c3462308e69185a07960ce1c3ce21bf3dcbcb7ba',
 'app/pt_asset_tool/blender/check_rigid_profile_devtest.py': 'fc3fb8a3d45ff0a076436bb49de18898880cf4883523d1d867c203aee4f659cd',
 'app/pt_asset_tool/class_ui_alias_audit.py': 'e36e949104a62a37f693981987931955bef974b46b8e23bc7ffbe730c288386d',
 'app/pt_asset_tool/class_ui_alias_canonicalize.py': '99cd6282bf22e4436ac8af4cfdbbad8b449e44acd509abb9076882edf963c73f',
 'app/pt_asset_tool/cli.py': '2dad64ed1d6b367fc31a0ce2d1a2bf482226fbb4e84a1d6f0ab85b4a2ce213b8',
 'app/pt_asset_tool/client_manifest_evidence.py': 'b2a95a1a77e65540623a7b19c0de1627683dbf795f64d55af5a059382a38edfc',
 'app/pt_asset_tool/contract_graph.py': 'c6804c1c6d272b6740563383dd6d085c6af956290100ee4ae9f8a711d2312fba',
 'app/pt_asset_tool/general_asset_census.py': '3d7a5eb3950e03701ec85b1fc3b05c82fdd0be5f4faec627b204240b9ff63c96',
 'app/pt_asset_tool/general_asset_recovery.py': '7a37b7e3059a0dcc665873946866a2e8025f6b0ff001c0455d2dc68ccf24a12a',
 'app/pt_asset_tool/motion_core.py': 'd4403c2f9a5dd35270d5527d1223bdf82d954b0d1293a7b081ce2c2daa879b9b',
 'app/pt_asset_tool/multilayer_texlink.py': 'f6a3336bcae0c0a8b5df480d55cf0b9dd30a26a9e189cc4b3c395dc7a5928c4c',
 'app/pt_asset_tool/player_class_motion_contract.py': 'c7bedf863a89312e3878d7d85ab721a62836538f428b56a2befae2af61fecd42',
 'app/pt_asset_tool/player_scale_witness.py': '7846e2f2b32e6b9b916cda5f6e2e4fd060899abb04e301b4d8459f01b825ac84',
 'app/pt_asset_tool/registry.py': '0594c427909633afc7ed488a2f18d892f3a9c5cae8ca193dde0f32c7c081a779',
 'app/pt_asset_tool/release_1_auto.py': '9c3f7ac5d604a8b9d25ba4484fd86af5cb141fba90428e81462675df23a959f3',
 'app/pt_asset_tool/release_1_coverage.py': 'bd208d73ff9aaf0034ceb84a5b267e31e12b269c7f672a4ac9ab6cc3220740b9',
 'app/pt_asset_tool/release_scope.py': '3446627acbc2c007f825352350acc3afd9553c64efbb7f7ca89402d087b14f1e',
 'app/pt_asset_tool/rigid_authoring_candidate.py': 'a86a1595a5122bc4e190ffc8b8bb92b2ec7381f12e57ea7a16f32952513d88ee',
 'app/pt_asset_tool/rigid_authoring_stress.py': '63046179cdc2787fdf177b654375897e15b904ac91415773b5fa8be5b84e30bf',
 'app/pt_asset_tool/rigid_context_census.py': '9d71ba52cc7eccf0786bd9473c20a8ffee632fd4003618ae3e151dee3c7100bb',
 'app/pt_asset_tool/server_bundle_census.py': '9d46ba30c33c20021098ef7520bef98325e20ee6c2c2e06904645a65bfb1d078',
 'app/pt_asset_tool/server_lifecycle.py': '210d069a88e243e0919b8152d460decf1cb5c33d11769edd65192370574ef3b4',
 'app/pt_asset_tool/skill_contract_census.py': '6fa2f57b18fc1b326bb55436ece9c6355c54a7fb73d6e9a150e984fda74e0590',
 'app/pt_asset_tool/source_catalog.py': 'b9903452e0d19a9f3a22766fbd9d018e9ed02db70570b2336473001ccd2e8033',
 'app/pt_asset_tool/source_contract_census.py': '279c922df2a9250a9a9e01bbe2cd4570a9b080c68a0b031e3b1c60adcc9d4e8e',
 'app/pt_asset_tool/source_evidence.py': 'bd02b2bac722300e8125bed967632e0f13f29a575478b58fe609e5d184419c40',
 'app/pt_asset_tool/stage072_corpus.py': 'aead188936276b0358cd7fb37e86e70d37ee8507ce4850c610fcc959db2b101d',
 'app/pt_asset_tool/standalone_rigid_devtest.py': '4373c7bd00bd4eb8f5057e13659049520765b8127ec214fa532e9b14eb391d89',
 'app/pt_asset_tool/static_semantic_devtest.py': 'cfa22a308b68e0ac85cc3fe01dbd9b34127bf66408991a55f8807f757ea727c9',
 'app/pt_asset_tool/superset_aggregation.py': 'd046978a447882963a6d1524695dcf7e794999ba397558f1d531b432aa596d5b',
 'app/pt_asset_tool/texture_codec_devtest.py': 'f0d4b2dec316565d6edf10e11457f437f10a4bda19c397450bf659db5d714a49',
 'app/pt_asset_tool/texture_overlay.py': '7717a7cccfc5a7f3855a16439030cf18ce62bff4a4814d6524bd89d1503cd23a',
 'app/pt_asset_tool/ui_actions.py': 'ae57b20afa83011348b38a6aeb8ab3959125b3c09101a21ab6d8f9034e912193',
 'app/pt_asset_tool/ui_app.py': '85593af4015c9399ebe9c1feeff019ff0d88eaba6c29de70c63697d5d29fd009',
 'app/pt_asset_tool/ui_catalog.py': 'ebff218f17e74a4e0a25f6b68972e6d224903958b7f29df6874bb5586ee473a4',
 'app/pt_asset_tool/ui_static/app.css': 'a8c9f58eeea0bb6058b85d7fbd675ed46e7f9a71c63bde0dd696c495c4b12efb',
 'app/pt_asset_tool/ui_static/app.js': '3dd439bf64b21fc92cb461b58a4011d7c4e3b587f55cf670c2ba317bb624136d',
 'app/pt_asset_tool/ui_static/index.html': 'a4283e4469f5811dec8cd1547b319bd0ac33c5e47d91abfb8dd5eb8b8a5976ac',
 'app/pt_asset_tool/validation.py': '5c002cd9471e06de5cdc52a972af75cacf3d00a809a5d40d4cbbd4a982901a57',
 'app/pt_asset_tool/writer_corpus_audit.py': '8cd917878bbc8ac85b57386617c3d13397770ed46d0c7947f345459db064f2a5',
 'app/pt_blender_to_smd_free_mesh_v3.py': '2a9b876c376449aa1fe6702824ab4eb76d5a52be32cba6b4731b4ea2ba5cf426',
 'app/pt_character_structural_gate_v2.py': '466180a23b29ee8c050d78ea53abce98170237a2703aed5ed9b8e8ea706a270b',
 'app/pt_inx_motion_core_v2.py': '82a53a00fccfcbbab4370eb7be25b9bcfe3d4820588a94f394ef2a25df11ac2c',
 'app/pt_pikeman_smd_material_audit_v1.py': '26e899fbb73dc89bf53f2311242e76711deb0f74ddc1f4b8219d9228a6bdaee6',
 'app/pt_protected_tga_v1.py': '548ffc2b9bcdb42c9e28d3b33af0ba1b3dd4489835e57cb85332704a99465a82',
 'app/tests/test_class_ui_alias_audit.py': 'c0b9ff614f1ca9924aaa57fa826f0fd7ff2c51bd50f376743cfa48dab007f9c6',
 'app/tests/test_class_ui_alias_canonicalize.py': 'a903b21ccc8568aee3a3e14f828bba43e815270ffffaf06397f7b4a8e4e45e6b',
 'app/tests/test_source_contracts.py': '3c059dcb10e1cf1f12b42268a25c36204a3b9539c824c0db35284b0a25d62ff5',
 'app/tests/test_superset_aggregation.py': '9c4aa3a56c1d6df3e5691d002ee93d8e9ef037f67eb31c9a1610e716ee9fff8d',
 'docs/ASSET_CONTRACTS_RC6_15_INTEGRATION.md': '1b09d359056e291fcb48fe98f4d89b40b203c64dd5aabdd081acb7a32270197a',
 'docs/SNAPSHOT_MANIFEST_POLICY.md': 'd09b8a21a3157a4ad57fc1b06e61328821904e29b8f5b3c97213fcd1da2e3544',
 'docs/UPDATE_INSTALLATION_METHOD.md': 'edbee2cda161862c3cdecc4b982d721953c5519a2c75f7324f6aaeb5b097f58f',
 'vendor/summit_asset_enrichment_v6/asset_common.py': 'f824d96f544af230557c687ab60b598fe620df347d63fd514f256b3b2552fb8e',
 'vendor/summit_asset_enrichment_v6/build_dependency_graph.py': 'f25e053bd55f379914b94cb21990798de9815c708ad73eb8b48a8fe26f918a2b',
 'vendor/summit_asset_enrichment_v9/asset_common.py': 'dd85ef7e5042cbbf06e9deb564f743e2fe33f6c73e29bfd6f6ddeeb8bdb7670e',
 'vendor/summit_asset_enrichment_v9/build_dependency_graph.py': 'f25e053bd55f379914b94cb21990798de9815c708ad73eb8b48a8fe26f918a2b'}
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
    if version!='1.0.0': errors.append(f'version={version!r}')
    readiness_path=root/'CURRENT_READINESS.json'
    if not readiness_path.is_file():
        errors.append('CURRENT_READINESS.json missing')
    else:
        rd=json.loads(readiness_path.read_text(encoding='utf-8'))
        for k in ('production_authorized','client_write_authorized','server_write_authorized'):
            if rd.get(k) is not False: errors.append(f'{k} must be false')
        if rd.get('status')!='RELEASE_1_0_CERTIFIED_SAFETY_LOCKED': errors.append(f"status={rd.get('status')!r}")
        if rd.get('release_1_0') is not True: errors.append('release_1_0 must be true')
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
