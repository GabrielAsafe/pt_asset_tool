from __future__ import annotations

import csv
import json
from pathlib import Path

from pt_asset_tool.summit_asset_audit_refinement import (
    FORMAT,
    audit_summit_asset_refinement,
    build_canonical_owner_index,
    refine_migration_rows,
    refine_ui_rows,
)


def _write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _migration_row(**overrides: str) -> dict[str, str]:
    row = {
        "priority": "P0", "state": "SOURCE_ONLY_MISSING", "scope": "EFFECT",
        "client_path": "flare.tga", "client_exists": "False", "resolution": "MISSING",
        "effect_loader_root": "False", "canonical_strong": "False", "canonical_review": "False",
        "cook_action": "", "cook_state": "", "source_file": "fx.cpp", "source_line": "1",
        "raw_literal": "flare.tga",
    }
    row.update(overrides)
    return row


def test_refinement_classifies_loader_alias_template_and_exact_oracle_duplicate(tmp_path: Path):
    src = tmp_path / "SourceCode"
    src.mkdir()
    (src / "fx.cpp").write_text(
        'x = AssaSearchRes("flare.tga");\n'
        'sprintf(path, "%s/Hit/HitYellow%d.tga", root, n);\n',
        encoding="utf-8",
    )
    oracle = src / "Shared/legacy_oracle"
    oracle.mkdir(parents=True)
    (oracle / "fx.cpp").write_text('x = AssaSearchRes("flare.tga");\n', encoding="utf-8")

    rows = [
        _migration_row(),
        _migration_row(source_file="fx.cpp", source_line="2", client_path="%s/Hit/HitYellow%d.tga", raw_literal="%s/Hit/HitYellow%d.tga"),
        _migration_row(source_file="Shared/legacy_oracle/fx.cpp"),
    ]
    out = refine_migration_rows(rows, source_root=src)
    assert out[0]["semantic_review_class"] == "ASSA_RESOURCE_CATALOG_ALIAS"
    assert out[1]["semantic_review_class"] == "DYNAMIC_PRINTF_TEMPLATE"
    assert out[2]["oracle_duplicate_evidence"] == "True"
    assert out[2]["actionable_primary_evidence"] == "False"


def test_refinement_ui_safe_filters_preserve_review_candidates(tmp_path: Path):
    src = tmp_path / "SourceCode"
    src.mkdir()
    (src / "ui.cpp").write_text(
        '#include "systems/network/client/netplay.h"\n'
        'DrawText("Quest completed");\n',
        encoding="utf-8",
    )
    tests = src / "tests"
    tests.mkdir()
    (tests / "fixture.cpp").write_text('const char* x = "Fixture label";\n', encoding="utf-8")
    rows = [
        {"source_file": "ui.cpp", "source_line": "1", "text": "systems/network/client/netplay.h", "has_format_token": "False", "state": "UI_TEXT_REVIEW", "recommended_target": "x"},
        {"source_file": "ui.cpp", "source_line": "2", "text": "Quest completed", "has_format_token": "False", "state": "UI_TEXT_REVIEW", "recommended_target": "x"},
        {"source_file": "tests/fixture.cpp", "source_line": "1", "text": "Fixture label", "has_format_token": "False", "state": "UI_TEXT_REVIEW", "recommended_target": "x"},
    ]
    out = refine_ui_rows(rows, source_root=src)
    assert out[0]["refined_class"] == "FALSE_POSITIVE_SOURCE_INCLUDE"
    assert out[0]["actionable_primary_evidence"] == "False"
    assert out[1]["refined_class"] == "REVIEW"
    assert out[1]["actionable_primary_evidence"] == "True"
    assert out[2]["refined_class"] == "TEST_FIXTURE_NON_RUNTIME"


def test_canonical_owner_index_is_exact_and_evidence_only(tmp_path: Path):
    root = tmp_path / "canonical"
    (root / "model_configs").mkdir(parents=True)
    (root / "model_configs/index.json").write_text(
        json.dumps({"a": "char/npc/npc-04.ini", "nested": ["Effect/Foo.ini"]}),
        encoding="utf-8",
    )
    index = build_canonical_owner_index(root)
    assert index["char/npc/npc-04.ini"] == ["model_configs/index.json"]
    assert index["effect/foo.ini"] == ["model_configs/index.json"]
    assert "npc-04.ini" not in index


def test_end_to_end_preserves_raw_rows_and_keeps_canonical_missing_blocking(tmp_path: Path):
    baseline = tmp_path / "audit"
    source = tmp_path / "SourceCode"
    canonical = tmp_path / "Content/canonical"
    source.mkdir(parents=True)
    canonical.mkdir(parents=True)
    (source / "x.cpp").write_text('x = AssaSearchRes("flare.tga");\n', encoding="utf-8")
    (canonical / "index.json").write_text(json.dumps({"asset": "char/npc/npc-04.ini"}), encoding="utf-8")

    migration_fields = [
        "priority", "state", "scope", "client_path", "client_exists", "resolution",
        "effect_loader_root", "canonical_strong", "canonical_review", "cook_action", "cook_state",
        "source_file", "source_line", "raw_literal",
    ]
    migration_rows = [
        _migration_row(source_file="x.cpp"),
        _migration_row(
            state="CANONICAL_RUNTIME_ASSET_MISSING", scope="CHARACTER_MODEL",
            client_path="char/npc/npc-04.ini", raw_literal="char/npc/npc-04.ini",
            source_file="", source_line="", canonical_strong="True",
        ),
    ]
    ui_fields = ["source_file", "source_line", "text", "has_format_token", "state", "recommended_target"]
    ui_rows = [{"source_file": "x.cpp", "source_line": "1", "text": "Player text", "has_format_token": "False", "state": "UI_TEXT_REVIEW", "recommended_target": "x"}]
    _write_tsv(baseline / "migration_queue.tsv", migration_fields, migration_rows)
    _write_tsv(baseline / "ui_text_candidates.tsv", ui_fields, ui_rows)

    result = audit_summit_asset_refinement(
        baseline,
        source_root=source,
        canonical_root=canonical,
        output_dir=tmp_path / "out",
    )
    assert result["format"] == FORMAT
    assert result["status"] == "PASS"
    assert result["state"] == "REVIEW_REQUIRED"
    assert result["baseline"]["migration_queue"] == 2
    assert result["baseline"]["CANONICAL_RUNTIME_ASSET_MISSING"] == 1
    assert result["refinement"]["canonical_missing_with_exact_owner"] == 1
    assert result["policy"]["canonical_missing_not_downgraded"] is True
    with (tmp_path / "out/migration_queue_refined.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == 2
    canonical_row = next(row for row in rows if row["state"] == "CANONICAL_RUNTIME_ASSET_MISSING")
    assert canonical_row["semantic_review_class"] == "CANONICAL_RUNTIME_ASSET_MISSING"
    assert canonical_row["canonical_owner_files"] == "index.json"


def test_client_server_mirror_dedup_suppresses_only_server_copy(tmp_path: Path):
    src = tmp_path / "SourceCode"
    client_file = src / "SrcGame/src/systems/ui/messages/legacy_sin/sinMsg.cpp"
    server_file = src / "SrcServer/src/systems/ui/messages/legacy_sin/sinMsg.cpp"
    client_file.parent.mkdir(parents=True)
    server_file.parent.mkdir(parents=True)
    client_file.write_text('Draw("Same text");\nDraw("Same text");\n', encoding="utf-8")
    server_file.write_text('Draw("Same text");\n', encoding="utf-8")
    rows = [
        {"source_file": "SrcGame/src/systems/ui/messages/legacy_sin/sinMsg.cpp", "source_line": "1", "text": "Same text", "has_format_token": "False", "state": "UI_TEXT_REVIEW", "recommended_target": "x"},
        {"source_file": "SrcGame/src/systems/ui/messages/legacy_sin/sinMsg.cpp", "source_line": "2", "text": "Same text", "has_format_token": "False", "state": "UI_TEXT_REVIEW", "recommended_target": "x"},
        {"source_file": "SrcServer/src/systems/ui/messages/legacy_sin/sinMsg.cpp", "source_line": "1", "text": "Same text", "has_format_token": "False", "state": "UI_TEXT_REVIEW", "recommended_target": "x"},
    ]
    out = refine_ui_rows(rows, source_root=src)
    assert out[0]["actionable_primary_evidence"] == "True"
    assert out[1]["actionable_primary_evidence"] == "True"
    assert out[2]["mirror_duplicate_evidence"] == "True"
    assert out[2]["actionable_primary_evidence"] == "False"


def test_canonical_pack_backed_missing_remains_original_state_but_gets_pack_requirement(tmp_path: Path):
    baseline = tmp_path / "audit"
    source = tmp_path / "SourceCode"
    canonical = tmp_path / "Content/canonical"
    runtime = source / "Shared/content/v1/text_resource/content"
    runtime.mkdir(parents=True)
    (runtime / "TextResourceRuntime.h").write_text(
        'inline bool TextResourceStrictMode(){ return true; }\n'
        'ResolveRuntimePackPath("text_resources.sres");\n'
        's->Load(path,bytes,0,0,0);\n', encoding="utf-8")
    (runtime / "CompiledTextResourceSource.h").write_text('memcmp(p,"SRES",4);\n', encoding="utf-8")
    tools = source / "tools/content_port"; tools.mkdir(parents=True)
    (tools / "compile_text_resources.py").write_text('legacy_payload_base64\nbase64.b64decode\n', encoding="utf-8")
    (tools / "quarantine_legacy_runtime_content.py").write_text('text_resources.sres\nvalidate_pack_presence\n', encoding="utf-8")
    resource = canonical / "text/resources/cliente/help"
    resource.mkdir(parents=True)
    import base64, hashlib
    raw = b"hello\r\n"
    (resource / "x.msg.json").write_text(json.dumps({
        "schema": "summit.canonical-text-resource/v1", "id": "text.x", "kind": "message_catalog",
        "runtime_paths": ["cliente/help/x.msg", "help/x.msg"],
        "source": {"legacy_path": "cliente/help/x.msg", "legacy_size": len(raw), "legacy_sha256": hashlib.sha256(raw).hexdigest()},
        "compatibility": {"legacy_payload_base64": base64.b64encode(raw).decode("ascii")},
    }), encoding="utf-8")
    migration_fields = [
        "priority", "state", "scope", "client_path", "client_exists", "resolution",
        "effect_loader_root", "canonical_strong", "canonical_review", "cook_action", "cook_state",
        "source_file", "source_line", "raw_literal",
    ]
    _write_tsv(baseline / "migration_queue.tsv", migration_fields, [_migration_row(
        state="CANONICAL_RUNTIME_ASSET_MISSING", scope="UI", client_path="help/x.msg", raw_literal="help/x.msg",
        source_file="", source_line="", canonical_strong="True")])
    ui_fields = ["source_file", "source_line", "text", "has_format_token", "state", "recommended_target"]
    _write_tsv(baseline / "ui_text_candidates.tsv", ui_fields, [])
    result = audit_summit_asset_refinement(baseline, source_root=source, canonical_root=canonical, output_dir=tmp_path / "out")
    assert result["refinement"]["canonical_missing_sres_pack_backed"] == 1
    assert result["actionable_views"]["canonical_physical_missing_requiring_recovery"] == 0
    with (tmp_path / "out/migration_queue_refined.tsv").open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle, delimiter="\t"))
    assert row["state"] == "CANONICAL_RUNTIME_ASSET_MISSING"
    assert row["canonical_runtime_class"] == "SRES_PACK_BACKED_LEGACY_PATH"
    assert row["release_requirement"] == "VERIFY_TEXT_RESOURCES_SRES_SOURCE_PACK_AND_DEPLOYMENT"


def test_glob_and_audio_scope_are_not_literal_effect_missing(tmp_path: Path):
    src = tmp_path / "SourceCode"
    path = src / "SrcGame/src/systems/audio/effects/legacy/effectsnd.cpp"
    path.parent.mkdir(parents=True)
    path.write_text('lstrcat(szFindPath, "*.wav");\n', encoding="utf-8")
    row = _migration_row(source_file="SrcGame/src/systems/audio/effects/legacy/effectsnd.cpp", source_line="1", client_path="*.wav", raw_literal="*.wav")
    out = refine_migration_rows([row], source_root=src)[0]
    assert out["refined_scope"] == "AUDIO"
    assert out["semantic_review_class"] == "DYNAMIC_GLOB_PATTERN"


def test_residual_source_evidence_classifies_build_gate_test_helper_ignored_argument_and_optional_script(tmp_path: Path):
    src = tmp_path / "SourceCode"
    ho = src / "SrcGame/src/systems/rendering/effects/legacy_ho/core/HoEffect.cpp"
    ho.parent.mkdir(parents=True)
    ho.write_text(
        '#ifdef Making_SKILL_TORNADO3\n'
        'AnimDataMgr.ImageLoad("Effect//ImageData//SkillTornado3.ini");\n'
        '#endif\n'
        '// LoadScript() already fails safely if a particular optional asset is missing.\n'
        'g_NewParticleResMgr.LoadScript("game//scripts//particles//MG5OrbMastery.part");\n',
        encoding="utf-8",
    )
    util = src / "Shared/rendering/effects/AssaUtilLegacyCommon.inl"
    util.parent.mkdir(parents=True)
    util.write_text(
        'int AssaTestEffectImage()\n{\n char *szFilePath = "image//Sinimage//AssaEffect//AssaTest.INI";\n return 0;\n}\n',
        encoding="utf-8",
    )
    wave = src / "Shared/rendering/effects/SinAssaParticleLegacyCommon.inl"
    wave.write_text(
        'void caller(){ AssaParticle_Wave(&p, "water3.tga", 1); }\n'
        'int AssaParticle_Wave(POINT3D *pPosi, char *FileName, int Size)\n{\n return Size;\n}\n',
        encoding="utf-8",
    )
    particle = src / "Shared/rendering/effects/particles/HoNewParticleMgrLegacyCommon.inl"
    particle.parent.mkdir(parents=True)
    particle.write_text(
        'bool HoNewParticleResMgr::LoadScript(char *scr)\n{\n FILE *fp=fopen(scr,"rb");\n if(fp == NULL) { return false; }\n return true;\n}\n',
        encoding="utf-8",
    )
    rows = [
        _migration_row(source_file="SrcGame/src/systems/rendering/effects/legacy_ho/core/HoEffect.cpp", source_line="2", client_path="Effect/ImageData/SkillTornado3.ini", raw_literal="Effect/ImageData/SkillTornado3.ini"),
        _migration_row(source_file="Shared/rendering/effects/AssaUtilLegacyCommon.inl", source_line="3", client_path="image/Sinimage/AssaEffect/AssaTest.INI", raw_literal="image/Sinimage/AssaEffect/AssaTest.INI"),
        _migration_row(source_file="Shared/rendering/effects/SinAssaParticleLegacyCommon.inl", source_line="1", client_path="water3.tga", raw_literal="water3.tga"),
        _migration_row(source_file="SrcGame/src/systems/rendering/effects/legacy_ho/core/HoEffect.cpp", source_line="5", client_path="game/scripts/particles/MG5OrbMastery.part", raw_literal="game/scripts/particles/MG5OrbMastery.part"),
    ]
    out = refine_migration_rows(rows, source_root=src)
    assert [row["semantic_review_class"] for row in out] == [
        "BUILD_GATED_UNDEFINED_MACRO",
        "UNREFERENCED_TEST_HELPER",
        "IGNORED_LEGACY_ARGUMENT",
        "OPTIONAL_PARTICLE_SCRIPT_SAFE_FAIL",
    ]


def test_model_config_server_cache_is_recovery_candidate_not_proven_present(tmp_path: Path):
    src = tmp_path / "SourceCode"; src.mkdir()
    rows = [_migration_row(
        state="CANONICAL_RUNTIME_ASSET_MISSING", scope="CHARACTER_MODEL",
        client_path="char/npc/phl/phl.ini", raw_literal="char/npc/phl/phl.ini",
        source_file="", source_line="", canonical_strong="True",
    )]
    model_index = {
        "char/npc/phl/phl.ini": {
            "owner_file": "model_configs/models/phl.json", "source_status": "unresolved",
            "legacy_cache": "char/npc/phl/phl.inx", "server_present": True, "client_present": False,
        }
    }
    out = refine_migration_rows(rows, source_root=src, model_config_index=model_index)[0]
    assert out["canonical_runtime_class"] == "MODEL_CONFIG_SERVER_CACHE_RECOVERY_CANDIDATE"
    assert out["release_requirement"] == "RECOVER_CLIENT_MODEL_CONFIG_FROM_SERVER_CACHE_AND_VALIDATE"


def test_source_sres_pack_payload_and_runtime_deployment_can_be_verified(tmp_path: Path):
    import base64
    import hashlib
    import struct

    baseline = tmp_path / "audit"
    source = tmp_path / "repo/SourceCode"
    canonical = source / "Content/canonical"
    resource = canonical / "text/resources/cliente/help"
    resource.mkdir(parents=True)
    raw = b"hello\r\n"
    (resource / "x.msg.json").write_text(json.dumps({
        "schema": "summit.canonical-text-resource/v1", "id": "text.x", "kind": "message_catalog",
        "runtime_paths": ["cliente/help/x.msg", "help/x.msg"],
        "source": {"legacy_path": "cliente/help/x.msg", "legacy_size": len(raw), "legacy_sha256": hashlib.sha256(raw).hexdigest()},
        "compatibility": {"legacy_payload_base64": base64.b64encode(raw).decode("ascii")},
    }), encoding="utf-8")
    runtime = source / "Shared/content/v1/text_resource/content"; runtime.mkdir(parents=True)
    (runtime / "TextResourceRuntime.h").write_text('TextResourceStrictMode(){ return true; } ResolveRuntimePackPath("text_resources.sres"); s->Load(path,bytes,0,0,0);', encoding="utf-8")
    (runtime / "CompiledTextResourceSource.h").write_text('memcmp(p,"SRES",4);', encoding="utf-8")
    tools = source / "tools/content_port"; tools.mkdir(parents=True)
    (tools / "compile_text_resources.py").write_text('legacy_payload_base64 base64.b64decode', encoding="utf-8")
    (tools / "quarantine_legacy_runtime_content.py").write_text('text_resources.sres validate_pack_presence', encoding="utf-8")

    def make_pack(path: Path) -> None:
        header = struct.Struct('<4sHH10I32s'); record = struct.Struct('<6I')
        strings = b'help/x.msg\0text.x\0'
        record_blob = record.pack(0, len(b'help/x.msg\0'), 6, 1, 0, len(raw))
        ro = header.size; so = ro + record.size; po = so + len(strings)
        body = record_blob + strings + raw
        packed = header.pack(b'SRES', 2, 0, 1, ro, record.size, so, len(strings), po, len(raw), 0, 0, 0, hashlib.sha256(body).digest()) + body
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(packed)

    source_pack = source / "Content/packs/text_resources.sres"; make_pack(source_pack)
    for root in (tmp_path / "repo/cliente", tmp_path / "repo/Servidor"):
        target = root / "Content/packs/text_resources.sres"; target.parent.mkdir(parents=True); target.write_bytes(source_pack.read_bytes())

    fields = ["priority", "state", "scope", "client_path", "client_exists", "resolution", "effect_loader_root", "canonical_strong", "canonical_review", "cook_action", "cook_state", "source_file", "source_line", "raw_literal"]
    _write_tsv(baseline / "migration_queue.tsv", fields, [_migration_row(state="CANONICAL_RUNTIME_ASSET_MISSING", scope="GENERAL", client_path="help/x.msg", raw_literal="help/x.msg", source_file="", source_line="", canonical_strong="True")])
    _write_tsv(baseline / "ui_text_candidates.tsv", ["source_file", "source_line", "text", "has_format_token", "state", "recommended_target"], [])
    result = audit_summit_asset_refinement(baseline, source_root=source, canonical_root=canonical, output_dir=tmp_path / "out")
    assert result["refinement"]["canonical_missing_sres_runtime_deployed_verified"] == 1
    assert result["actionable_views"]["canonical_pack_backed_paths_requiring_pack_deployment_validation"] == 0
    assert result["text_resource_pack_deployment"]["all_runtime_deployments_match_source"] is True
    with (tmp_path / "out/migration_queue_refined.tsv").open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle, delimiter="\t"))
    assert row["canonical_runtime_class"] == "SRES_PACK_DEPLOYED_VERIFIED"
    assert row["canonical_source_pack_payload_match"] == "True"
