from pathlib import Path

from pt_asset_tool.source_catalog import SourceTree, iter_source_files
from pt_asset_tool.source_evidence import scan_source_evidence


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def test_shared_gameplay_client_inl_is_runtime_and_pt_backups_are_ignored(tmp_path: Path):
    current = tmp_path / 'current'
    _write(current / 'Shared/gameplay/skills/SkillSub_legacy_client.inl', '''
void PlaySkillAttack()
{
    switch (SkillCode)
    {
    case SKILL_T5_RUPTURE:
        SummitT5StartParticle("MC5RuptureHit", lpChar);
        SkillPlaySound(0x4855, pX, pY, pZ);
        break;
    }
}
''')
    _write(current / '.pt_t5_av_patch_backups/old/SrcGame/game/Backup.cpp', '''
void CRuptureHandler::Old()
{
    StartParticle("SHOULD_NOT_BE_SCANNED");
}
''')

    files = [x.relative_to(current).as_posix() for x in iter_source_files(current)]
    assert 'Shared/gameplay/skills/SkillSub_legacy_client.inl' in files
    assert not any('.pt_t5_av_patch_backups/' in x for x in files)

    ev = scan_source_evidence(
        SourceTree('CURRENT_SOURCE', 'TARGET_RUNTIME_SOURCE', current),
        skill_catalog=[{'class': 'Mechanician', 'skill_name': 'Rupture'}],
    )
    rows = [x for x in ev['skill_cases'] if x.get('skill_name') == 'Rupture']
    assert len(rows) == 1
    row = rows[0]
    assert row['layer'] == 'CLIENT_RUNTIME'
    assert row['scope_basis'] == 'RUNTIME_CASE_SKILL_ALIAS'
    assert 'MC5RuptureHit' in row['effect_tokens']
    assert row['sounds'][0]['code'] == 0x4855
    effect_probes = ev['runtime_effect_call_probes']
    audio_probes = ev['runtime_audio_call_probes']
    assert any(x.get('source_file', '').endswith('SkillSub_legacy_client.inl') and x.get('callee') == 'SummitT5StartParticle' for x in effect_probes)
    assert any(x.get('source_file', '').endswith('SkillSub_legacy_client.inl') and x.get('callee') == 'SkillPlaySound' for x in audio_probes)
    assert not any('.pt_t5_av_patch_backups/' in x.get('source_file', '') for x in effect_probes + audio_probes)
