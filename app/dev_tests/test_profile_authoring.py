from types import SimpleNamespace

from pt_asset_tool.profile_authoring import plan_profile_authoring_context


def _profile():
    return SimpleNamespace(
        profile_id="hero_c01_m1",
        profile_version=2,
        roundtrip_target="char/test/body.smd",
        lod_groups={"high":["BodyHi"], "default":["Body"], "low":["BodyLo"]},
        geometry_status={"all_lods_runtime_proven": False},
    )


def _verification(model_info="char/test/body.inx", skeleton="char/test/body.smb"):
    return {
        "status":"PASS",
        "components":[
            {"role":"model_info", "status":"PASS", "logical_path":model_info},
            {"role":"skeleton", "status":"PASS", "logical_path":skeleton},
        ],
    }


class Profiles:
    def __init__(self, verification=None):
        self.profile = _profile()
        self.verification = verification or _verification()
    def get(self, profile_id):
        assert profile_id == self.profile.profile_id
        return self.profile
    def verify(self, profile_id, resolver, asset_registry=None):
        return self.verification


class Assets:
    def __init__(self):
        self.asset = SimpleNamespace(
            asset_id="AST-HERO", primary_path="char/test/body.smd",
            family="SMD_MODEL_062_RIGID_PHYSIQUE",
            configs=[{
                "inx":"char/test/body.inx", "motion_smb":"char/test/body.smb",
                "lod_groups":{"high":["BodyHi"], "default":["Body"], "low":["BodyLo"]},
            }],
        )
    def resolve(self, target):
        assert str(target).casefold() == self.asset.primary_path.casefold()
        return self.asset


def test_profile_authoring_plan_requires_exact_registry_context_and_selects_lod():
    result = plan_profile_authoring_context(Profiles(), "hero_c01_m1", SimpleNamespace(), Assets(), lod="high")
    assert result["status"] == "READY"
    assert result["model_info_inx"] == "char/test/body.inx"
    assert result["skeleton_smb"] == "char/test/body.smb"
    assert result["lod"] == "high"
    assert result["selected_lod_nodes"] == ["BodyHi"]
    assert result["selection_basis"]["profile_id"] == "hero_c01_m1"
    assert result["import_context_authorized"] is True
    assert result["writer_authorized"] is False
    assert result["production_authorized"] is False


def test_profile_authoring_plan_does_not_accept_basename_only_semantic_match():
    profiles = Profiles(_verification(model_info="other/path/body.inx"))
    result = plan_profile_authoring_context(profiles, "hero_c01_m1", SimpleNamespace(), Assets(), lod="auto")
    assert result["status"] == "BLOCKED"
    assert "PROFILE_EXACT_REGISTRY_CONTEXT_NOT_UNIQUE" in result["errors"]
    assert result["writer_authorized"] is False


def test_profile_registry_semantic_check_requires_unique_associated_inx_basename(tmp_path):
    import json
    from pt_asset_tool.profile_registry import CharacterProfileRegistry

    profiles_dir=tmp_path / "profiles"; profiles_dir.mkdir()
    (profiles_dir / "hero.json").write_text(json.dumps({
        "profile_id":"hero", "profile_version":1, "model_smd":"body.smd",
        "skeleton_smb":"body.smb", "model_info_inx":"body.inx",
        "roundtrip_target":"char/test/body.smd",
        "lod_groups":{"high":["Hi"],"default":["Body"],"low":["Lo"]},
        "known_mesh_objects":["Hi","Body","Lo"], "components":[],
    }))
    target=tmp_path / "client" / "char" / "test" / "body.smd"
    target.parent.mkdir(parents=True); target.write_bytes(b"smd")
    class Resolver:
        client_root=tmp_path / "client"
        index={}
        def resolve(self, logical, required=False):
            if str(logical).replace("\\", "/").casefold()=="char/test/body.smd": return target
            return None
    asset=SimpleNamespace(
        asset_id="AST", primary_path="char/test/body.smd", family="SMD_MODEL_062_RIGID_PHYSIQUE",
        configs=[
            {"inx":"char/a/body.inx","motion_smb":"char/test/body.smb","lod_groups":{"high":["Hi"],"default":["Body"],"low":["Lo"]}},
            {"inx":"char/b/body.inx","motion_smb":"char/test/body.smb","lod_groups":{"high":["Hi"],"default":["Body"],"low":["Lo"]}},
        ],
    )
    class Assets:
        def resolve(self, target): return asset
    reg=CharacterProfileRegistry(profiles_dir)
    ambiguous=reg.verify("hero", Resolver(), asset_registry=Assets())
    assert ambiguous["status"] == "FAIL"
    assert ambiguous["semantic_evidence"]["model_info_inx_match"] is False
    assert ambiguous["semantic_evidence"]["model_info_match_evidence"] == "UNIQUE_ASSOCIATED_INX_BASENAME"

    asset.configs=asset.configs[:1]
    exact=reg.verify("hero", Resolver(), asset_registry=Assets())
    assert exact["status"] == "PASS"
    assert exact["semantic_evidence"]["model_info_inx_match"] is True
