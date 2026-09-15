import csv
import json
import tempfile
import unittest
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from asset_common import CaseIndex
from audit_fix136_skill_assets import (
    MultiSourceResolver, SourceTree, classify_asset, follow_part_dependencies,
    load_wanted, safe_stage, reconcile_runtime_dest_collisions,
)


class Fix136AuditTests(unittest.TestCase):
    def test_suffix_matching_for_base_root_and_all_sources(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            old = td / "old"
            eu = td / "eu"
            target = td / "target"
            rel = Path("image/Sinimage/skill/Fighter/Button/TF103 Sesmic_Impact.bmp")
            p_old = old / "backup/client" / rel
            p_eu = eu / rel
            p_old.parent.mkdir(parents=True); p_old.write_bytes(b"old")
            p_eu.parent.mkdir(parents=True); p_eu.write_bytes(b"eu")
            target.mkdir()

            sources = [
                SourceTree("pt_eu_files", eu, 10, CaseIndex(eu)),
                SourceTree("previous_client_base", old, 20, CaseIndex(old)),
            ]
            resolver = MultiSourceResolver(sources)
            asset = {
                "asset_id":"A0001", "category":"button_normal", "expected":str(rel),
                "search_mode":"path", "classes":"Fighter", "tiers":"5",
                "skill_ids":"SKILLID_SeismicImpact", "origins":"", "references":"",
                "parent_asset":"", "depth":0,
            }
            row, cands = classify_asset(asset, resolver, CaseIndex(target))
            self.assertEqual(row["selected_source"], "pt_eu_files")
            self.assertEqual(row["selected_match"], "EXACT")
            self.assertEqual(len(cands), 2)
            self.assertIn("SUFFIX", {c["match_type"] for c in cands})
            self.assertEqual(row["source_hash_variants"], 2)
            self.assertEqual(row["needs_review"], "YES")

    def test_double_backslashes_from_eu_csv_are_normalized(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            inv = td / "inv.csv"; eff = td / "eff.csv"
            with inv.open("w", newline="", encoding="utf-8") as f:
                w=csv.DictWriter(f,fieldnames=["class","tier","skill_id","button_base","button_normal","button_hover","explicit_tga","source","line"])
                w.writeheader(); w.writerow({
                    "class":"Shaman","tier":"5","skill_id":"SKILLID_Creed","button_base":"MS80 Creed",
                    "button_normal":r"image\\Sinimage\\skill\\Shaman\\Button\\MS80 Creed.bmp",
                    "button_hover":r"image\\Sinimage\\skill\\Shaman\\Button\\MS80 Creed_.bmp",
                    "explicit_tga":"Sh5_CREED.tga","source":"shared/skill.h","line":"1"})
            with eff.open("w", newline="", encoding="utf-8") as f:
                w=csv.DictWriter(f,fieldnames=["source","line","asset","type"]); w.writeheader()
            rows=load_wanted(inv,eff,{5})
            expected={r["expected"] for r in rows}
            self.assertIn("image/Sinimage/skill/Shaman/Button/MS80 Creed.bmp", expected)
            self.assertIn("Sh5_CREED.tga", expected)

    def test_part_dependency_closure_and_staging(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            src=td/"src"; target=td/"target"; stage=td/"stage"
            part_rel=Path("game/scripts/particles/Example.part")
            tex_rel=Path("game/scripts/particles/ExampleGlow.tga")
            part=src/"nested/client"/part_rel
            tex=src/"nested/client"/tex_rel
            part.parent.mkdir(parents=True)
            part.write_text('texture = "ExampleGlow.tga"\n',encoding="latin1")
            tex.write_bytes(b"texture-bytes")
            target.mkdir()
            resolver=MultiSourceResolver([SourceTree("previous_client_base",src,20,CaseIndex(src))])
            asset={
                "asset_id":"A0001","category":"effect_literal","expected":str(part_rel),"search_mode":"path",
                "classes":"","tiers":"","skill_ids":"","origins":"","references":"part","parent_asset":"","depth":0,
            }
            row,_=classify_asset(asset,resolver,CaseIndex(target))
            deps,_=follow_part_dependencies([row],resolver,CaseIndex(target),8)
            self.assertEqual(len(deps),1)
            self.assertEqual(deps[0]["expected"],str(tex_rel))
            self.assertTrue(deps[0]["status"].startswith("FOUND_"))
            log=safe_stage([row]+deps,stage)
            self.assertEqual(sum(x["result"]=="STAGED" for x in log),2)
            self.assertEqual((stage/part_rel).read_bytes(),part.read_bytes())
            self.assertEqual((stage/tex_rel).read_bytes(),tex.read_bytes())


class Fix136V8EvidenceTests(unittest.TestCase):
    def test_mechanician_mecha_alias_is_structural(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); old=td/'old'; target=td/'target'; target.mkdir()
            physical=old/'image/Sinimage/skill/Mecha/Button/TM10 Ex_shield.bmp'
            physical.parent.mkdir(parents=True); physical.write_bytes(b'old-mecha')
            resolver=MultiSourceResolver([SourceTree('previous_client_base',old,20,CaseIndex(old))])
            asset={
                'asset_id':'A1','category':'button_normal','expected':'image/Sinimage/skill/Mechanician/Button/TM10 Ex_shield.bmp',
                'search_mode':'path','classes':'Mechanician','tiers':'1','skill_ids':'x','origins':'','references':'','parent_asset':'','depth':0,
            }
            row,cands=classify_asset(asset,resolver,CaseIndex(target))
            self.assertEqual(row['selected_match'],'ALIAS_EXACT')
            self.assertEqual(cands[0]['matched_as'],'image/Sinimage/skill/Mecha/Button/TM10 Ex_shield.bmp')

    def test_baseline_lineage_resolves_cross_source_variant(self):
        from audit_fix136_skill_assets import infer_baseline_source, resolve_base_actions
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); old=td/'old'; eu=td/'eu'; target=td/'target'
            old.mkdir(); eu.mkdir(); target.mkdir()
            sources=[SourceTree('pt_eu_files',eu,10,CaseIndex(eu)),SourceTree('previous_client_base',old,20,CaseIndex(old))]
            resolver=MultiSourceResolver(sources)
            rows=[]; cmap={}
            # 20 present assets prove old lineage.
            for i in range(20):
                rel=Path(f'image/x/p{i}.bmp')
                for root,data in ((old,b'old'),(eu,b'eu')):
                    p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(data+bytes([i]))
                t=target/rel; t.parent.mkdir(parents=True,exist_ok=True); t.write_bytes(b'old'+bytes([i]))
            # Rebuild indexes after writing.
            resolver=MultiSourceResolver([SourceTree('pt_eu_files',eu,10,CaseIndex(eu)),SourceTree('previous_client_base',old,20,CaseIndex(old))])
            for i in range(20):
                asset={'asset_id':f'P{i}','category':'button_normal','expected':f'image/x/p{i}.bmp','search_mode':'path','classes':'Fighter','tiers':'1','skill_ids':'','origins':'','references':'','parent_asset':'','depth':0}
                row,cands=classify_asset(asset,resolver,CaseIndex(target)); rows.append(row); cmap[row['asset_id']]=cands
            missing_rel='image/Sinimage/skill/Mechanician/Button/TM10 Ex_shield.bmp'
            po=old/'image/Sinimage/skill/Mecha/Button/TM10 Ex_shield.bmp'; po.parent.mkdir(parents=True,exist_ok=True); po.write_bytes(b'old-button')
            pe=eu/'image/Sinimage/skill/Mecha/Button/TM10 Ex_shield.bmp'; pe.parent.mkdir(parents=True,exist_ok=True); pe.write_bytes(b'eu-button')
            # refresh resolver for added files
            resolver=MultiSourceResolver([SourceTree('pt_eu_files',eu,10,CaseIndex(eu)),SourceTree('previous_client_base',old,20,CaseIndex(old))])
            asset={'asset_id':'M','category':'button_normal','expected':missing_rel,'search_mode':'path','classes':'Mechanician','tiers':'1','skill_ids':'','origins':'','references':'','parent_asset':'','depth':0}
            row,cands=classify_asset(asset,resolver,CaseIndex(target)); rows.append(row); cmap['M']=cands
            baseline,evidence=infer_baseline_source(rows,cmap)
            self.assertEqual(baseline,'previous_client_base')
            resolve_base_actions(rows,cmap,resolver,baseline)
            mr=[x for x in rows if x['asset_id']=='M'][0]
            self.assertEqual(mr['selected_source'],'previous_client_base')
            self.assertEqual(mr['action'],'STAGE_SAFE')
            self.assertEqual(mr['resolution'],'BASELINE_LINEAGE_KNOWN_ALIAS')

    def test_tf26_warcry_resolves_to_roar_narrow_alias(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); old=td/'old'; target=td/'target'; target.mkdir()
            normal=old/'image/Sinimage/skill/Fighter/Button/TF26 Roar.bmp'
            hover=old/'image/Sinimage/skill/Fighter/Button/TF26 Roar_.bmp'
            normal.parent.mkdir(parents=True); normal.write_bytes(b'roar-normal'); hover.write_bytes(b'roar-hover')
            resolver=MultiSourceResolver([SourceTree('previous_client_base',old,20,CaseIndex(old))])
            for expected,physical in [
                ('image/Sinimage/skill/Fighter/Button/TF26 WarCry.bmp', normal),
                ('image/Sinimage/skill/Fighter/Button/TF26 WarCry_.bmp', hover),
            ]:
                asset={'asset_id':'W','category':'button_normal','expected':expected,'search_mode':'path','classes':'Fighter','tiers':'2','skill_ids':'SKILLID_WarCry','origins':'','references':'TF26 WarCry','parent_asset':'','depth':0}
                row,cands=classify_asset(asset,resolver,CaseIndex(target))
                self.assertEqual(row['selected_match'],'ALIAS_EXACT')
                self.assertEqual(Path(row['selected_path']),physical)

    def test_shared_runtime_collision_prefers_target_baseline(self):
        rows=[
            {'asset_id':'D1','expected':'Effect/Particle/Script/flare.tga','runtime_dest':'Effect/Particle/flare.tga','action':'STAGE_SAFE','resolution':'PART_BUNDLE_COHERENT','selected_source':'previous_client_base','selected_match':'BASENAME','selected_rel':'Effect/Particle/flare.tga','selected_path':'/old/flare.tga','selected_sha256':'oldhash','selected_size':'10'},
            {'asset_id':'D2','expected':'game/scripts/particles/flare.tga','runtime_dest':'Effect/Particle/flare.tga','action':'STAGE_SAFE','resolution':'PART_BUNDLE_COHERENT','selected_source':'pt_eu_files','selected_match':'BASENAME','selected_rel':'Game/Effect/Particle/flare.tga','selected_path':'/eu/flare.tga','selected_sha256':'euhash','selected_size':'11'},
        ]
        report=reconcile_runtime_dest_collisions(rows,'previous_client_base')
        self.assertEqual(len(report),1)
        self.assertEqual(report[0]['resolution'],'BASELINE_LINEAGE_WINS')
        self.assertEqual(rows[1]['selected_source'],'previous_client_base')
        self.assertEqual(rows[1]['selected_sha256'],'oldhash')
        self.assertEqual(rows[1]['resolution'],'SHARED_RUNTIME_BASELINE')
        self.assertEqual(rows[1]['action'],'STAGE_SAFE')

    def test_part_loose_resource_uses_particle_family_and_strips_wrapper(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); eu=td/'eu'; target=td/'target'; target.mkdir()
            part=eu/'Game/game/scripts/particles/Test.part'; part.parent.mkdir(parents=True)
            part.write_text('texture = "flare.tga"\n',encoding='latin1')
            good=eu/'Game/Effect/Particle/flare.tga'; good.parent.mkdir(parents=True); good.write_bytes(b'good')
            other=eu/'Game/Effect/AssaEffect/flare.tga'; other.parent.mkdir(parents=True); other.write_bytes(b'other')
            resolver=MultiSourceResolver([SourceTree('pt_eu_files',eu,10,CaseIndex(eu),('Game',))])
            asset={'asset_id':'A','category':'effect_literal','expected':'game/scripts/particles/Test.part','search_mode':'path','classes':'','tiers':'','skill_ids':'','origins':'','references':'part','parent_asset':'','depth':0}
            row,cands=classify_asset(asset,resolver,CaseIndex(target))
            row['action']='STAGE_SAFE'; row['runtime_dest']=row['expected']
            deps,_=follow_part_dependencies([row],resolver,CaseIndex(target),8)
            self.assertEqual(len(deps),1)
            self.assertEqual(deps[0]['selected_rel'],'Game/Effect/Particle/flare.tga')
            self.assertEqual(deps[0]['runtime_dest'],'Effect/Particle/flare.tga')
            self.assertEqual(deps[0]['action'],'STAGE_SAFE')


if __name__ == "__main__":
    unittest.main()
