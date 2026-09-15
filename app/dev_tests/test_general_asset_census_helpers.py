from __future__ import annotations

from pathlib import Path

from pt_asset_tool.general_asset_census import _server_definition_names, _spm_actor_names


def test_spm_parser_accepts_cp949_actor_alias_and_tabs(tmp_path):
    p = tmp_path / "x.spm"
    p.write_bytes('*출연자\t"Hopy"\t100\n*출연자두목 "Boss" "Slave" 1 20\n'.encode('cp949'))
    assert _spm_actor_names(p) == [
        ('ACTOR', 'Hopy'),
        ('BOSS_ACTOR', 'Boss'),
        ('BOSS_ACTOR', 'Slave'),
    ]


def test_server_definition_name_index_accepts_korean_name_token(tmp_path):
    server = tmp_path / 'server'
    p = server / 'GameServer' / 'Monster' / 'internal.inf'
    p.parent.mkdir(parents=True)
    p.write_bytes('*이름 "Hopy"\n'.encode('cp949'))
    idx = _server_definition_names(server)
    assert idx['hopy'] == ['GameServer/Monster/internal.inf']


def _t5_graph(*, resolution_status: str = 'RECOVERABLE_REFERENCE'):
    return {
        'nodes': [
            {
                'node_id': 'SKILL:Fighter:SKILLID_SeismicImpact',
                'node_type': 'SKILL',
                'label': 'Seismic Impact',
                'attributes': {'class_name': 'Fighter', 'tier': 5, 'skill_id': 'SKILLID_SeismicImpact'},
            },
            {
                'node_id': 'EFFECT_TOKEN:t5seismicimpact',
                'node_type': 'EFFECT_TOKEN',
                'label': 'T5SeismicImpact',
                'attributes': {},
            },
            {
                'node_id': 'ASSET:t5seismicimpact.part',
                'node_type': 'ASSET',
                'label': 'T5SeismicImpact.part',
                'attributes': {
                    'logical_path': 'Effect/Particle/Script/T5SeismicImpact.part',
                    'asset_role': 'EFFECT_PARTICLE_SCRIPT',
                    'resolution': {
                        'status': resolution_status,
                        'logical_path': 'Effect/Particle/Script/T5SeismicImpact.part',
                        'source_label': 'OFFICIAL' if resolution_status != 'PRESENT_TARGET' else 'SUMMIT_CLIENT',
                        'physical_path': '',
                    },
                },
            },
        ],
        'edges': [
            {
                'source': 'SKILL:Fighter:SKILLID_SeismicImpact',
                'target': 'EFFECT_TOKEN:t5seismicimpact',
                'relation': 'USES_EFFECT_TOKEN',
                'evidence': 'CURRENT_HANDLER:SkillEffect.cpp',
                'status': 'CURRENT_RUNTIME_TOKEN',
            },
            {
                'source': 'EFFECT_TOKEN:t5seismicimpact',
                'target': 'ASSET:t5seismicimpact.part',
                'relation': 'RESOLVES_PARTICLE_SCRIPT',
                'evidence': 'PARTICLE_REGISTRY_BASENAME',
                'status': resolution_status,
            },
        ],
    }


def test_t5_readiness_requires_closed_recovery_bundle_for_missing_runtime_effect():
    from pt_asset_tool.general_asset_census import _t5_effect_readiness

    graph = _t5_graph()
    path = 'Effect/Particle/Script/T5SeismicImpact.part'
    candidates = [{
        'side': 'CLIENT',
        'path': path,
        'decision': 'RECOVERABLE_REACHABLE_CANDIDATE',
    }]
    bundles = [{
        'side': 'CLIENT',
        'root_path': path,
        'status': 'CLOSED',
    }]
    result = _t5_effect_readiness(graph, candidates, bundles, [])

    assert result['status'] == 'PASS'
    assert result['skill_count'] == 1
    assert result['current_runtime_effect_skill_count'] == 1
    assert result['recoverable_closed_root_count'] == 1
    assert result['scoped_import_ready'] is True
    assert result['recoverable_closed_roots'][0]['path'] == path
    row = result['rows'][0]
    assert row['status'] == 'CURRENT_T5_ASSETS_RECOVERABLE_CLOSED'
    assert row['bindings'][0]['state'] == 'RECOVERABLE_CLOSED'


def test_t5_readiness_donor_only_gap_is_not_import_authority():
    from pt_asset_tool.general_asset_census import _t5_effect_readiness

    result = _t5_effect_readiness(_t5_graph(), [], [], [])

    assert result['current_runtime_effect_skill_count'] == 1
    assert result['recoverable_closed_root_count'] == 0
    assert result['scoped_import_ready'] is False
    row = result['rows'][0]
    assert row['status'] == 'CURRENT_T5_ASSETS_BLOCKED'
    assert row['bindings'][0]['state'] == 'DONOR_PRESENT_NOT_RECOVERY_ROOT'
    assert result['policy']['donor_gap_is_not_import_authorization'] is True


def test_t5_readiness_reference_only_effect_is_not_runtime_proof():
    from pt_asset_tool.general_asset_census import _t5_effect_readiness

    graph = _t5_graph()
    graph['edges'][0]['status'] = 'REFERENCE_ONLY_TOKEN'
    graph['edges'][0]['evidence'] = 'REFERENCE_HANDLER:SkillEffect.cpp'
    result = _t5_effect_readiness(graph, [], [], [])

    assert result['current_runtime_effect_skill_count'] == 0
    assert result['no_current_runtime_effect_proof_count'] == 1
    assert result['scoped_import_ready'] is False
    assert result['rows'][0]['status'] == 'NO_CURRENT_T5_ASSET_CALL_PROOF'


def test_t5_audio_leaf_closed_bundle_is_scoped_import_ready():
    from pt_asset_tool.general_asset_census import _t5_effect_readiness

    path = 'wav/Effects/Skill/Tempskron/Seismic Impact.wav'
    graph = {
        'nodes': [
            {'node_id': 'SKILL:Fighter:SKILLID_SeismicImpact', 'node_type': 'SKILL', 'label': 'SeismicImpact', 'attributes': {'class_name': 'Fighter', 'tier': 5, 'skill_id': 'SKILLID_SeismicImpact'}},
            {'node_id': 'ASSET:' + path.casefold(), 'node_type': 'ASSET', 'label': 'Seismic Impact.wav', 'attributes': {'logical_path': path, 'asset_role': 'SKILL_AUDIO', 'resolution': {'status': 'RECOVERABLE_REFERENCE', 'physical_path': ''}}},
        ],
        'edges': [
            {'source': 'SKILL:Fighter:SKILLID_SeismicImpact', 'target': 'ASSET:' + path.casefold(), 'relation': 'REQUIRES_ASSET', 'evidence': 'CURRENT_HANDLER:SkillEffect.cpp:10', 'status': 'RECOVERABLE_REFERENCE'},
        ],
    }
    candidates = [{'side': 'CLIENT', 'path': path, 'decision': 'RECOVERABLE_REACHABLE_CANDIDATE'}]
    bundles = [{'side': 'CLIENT', 'root_path': path, 'status': 'CLOSED'}]
    result = _t5_effect_readiness(graph, candidates, bundles, [])
    row = result['rows'][0]
    assert result['current_runtime_audio_skill_count'] == 1
    assert result['recoverable_closed_audio_root_count'] == 1
    assert result['scoped_import_root_count'] == 1
    assert result['scoped_import_ready'] is True
    assert row['status'] == 'CURRENT_T5_ASSETS_RECOVERABLE_CLOSED'
    assert row['audio_bindings'][0]['state'] == 'RECOVERABLE_CLOSED'


def test_t5_partial_skill_bundle_is_not_scoped_import_authorized():
    from pt_asset_tool.general_asset_census import _t5_effect_readiness

    graph = _t5_graph()
    graph['nodes'].append({'node_id': 'SOUND_SYMBOL:skill_sound_seismic', 'node_type': 'SOUND_SYMBOL', 'label': 'SKILL_SOUND_SEISMIC', 'attributes': {'code': 123}})
    graph['edges'].append({
        'source': 'SKILL:Fighter:SKILLID_SeismicImpact',
        'target': 'SOUND_SYMBOL:skill_sound_seismic',
        'relation': 'PLAYS_SOUND',
        'evidence': 'CURRENT_SOURCE:SkillEffect.cpp:11',
        'status': 'CURRENT_RUNTIME_SYMBOL_UNRESOLVED',
    })
    path = 'Effect/Particle/Script/T5SeismicImpact.part'
    candidates = [{'side': 'CLIENT', 'path': path, 'decision': 'RECOVERABLE_REACHABLE_CANDIDATE'}]
    bundles = [{'side': 'CLIENT', 'root_path': path, 'status': 'CLOSED'}]
    result = _t5_effect_readiness(graph, candidates, bundles, [])
    row = result['rows'][0]
    assert result['recoverable_closed_root_count'] == 1
    assert result['scoped_import_root_count'] == 0
    assert result['scoped_import_ready'] is False
    assert row['status'] == 'CURRENT_T5_ASSETS_BLOCKED'
    assert row['unresolved_audio_bindings'][0]['state'] == 'UNRESOLVED_SOUND_SYMBOL'
