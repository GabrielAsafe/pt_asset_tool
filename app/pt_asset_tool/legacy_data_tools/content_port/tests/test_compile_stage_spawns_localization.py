#!/usr/bin/env python3
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fixture(root: Path, localized_text):
    canonical_text = root / "text"
    monster_rel = Path("resources/Servidor/GameServer/Monster/test.inf.json")
    write_json(canonical_text / "index.json", {
        "documents": [{
            "kind": "monster_definition",
            "json_path": monster_rel.as_posix(),
        }]
    })
    write_json(canonical_text / monster_rel, {
        "id": "monster.test_localized",
        "semantic": {"fields": {"name": "테스트", "english_name": "Test"}},
    })
    entries = []
    if localized_text is not None:
        entries.append({
            "key": "monster.test_localized.name",
            "text": localized_text,
            "quality": "translated",
            "source": "monster.test_localized",
        })
    write_json(canonical_text / "localization/pt-BR.json", {"entries": entries})

    spawns = root / "spawns"
    write_json(spawns / "index.json", {
        "documents": [{"json_path": "spawns/test.spm.json"}],
    })
    write_json(spawns / "spawns/test.spm.json", {
        "logical_path": "GameServer/Field/test.ASE.spm",
        "id": "spawn.test",
        "limit_max": 300,
        "delay": {"shift": 1, "milliseconds": 2000},
        "open_limit": 1,
        "actors": [{
            "legacy_name_bytes_hex": "4142",
            "monster_id": "monster.test_localized",
            "weight": 1,
        }],
        "bosses": [],
    })
    return canonical_text, spawns


def run_case(compiler: Path, localized_text, expect_ok: bool, expected_error: str = ""):
    with tempfile.TemporaryDirectory(prefix="summit_spawn_loc_test_") as td:
        root = Path(td)
        canonical_text, spawns = fixture(root, localized_text)
        output = root / "stage_spawns.sspb"
        proc = subprocess.run(
            [
                sys.executable,
                str(compiler),
                str(spawns),
                str(output),
                "--canonical-text",
                str(canonical_text),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if expect_ok:
            if proc.returncode != 0:
                raise AssertionError("expected PASS, got:\n" + proc.stdout)
            data = output.read_bytes()
            if b"Nome Seguro\x00" not in data:
                raise AssertionError("localized runtime name missing from SSPB")
            if "테스트".encode("utf-8") in data:
                raise AssertionError("semantic Korean name leaked into SSPB runtime display name")
        else:
            if proc.returncode == 0:
                raise AssertionError("expected FAIL but compiler passed")
            if expected_error not in proc.stdout:
                raise AssertionError(
                    f"expected error fragment {expected_error!r}, got:\n{proc.stdout}"
                )


def main():
    compiler = Path(__file__).resolve().parents[1] / "compile_stage_spawns_canonical.py"
    run_case(compiler, "Nome Seguro", True)
    run_case(compiler, None, False, "runtime pt-BR display name is missing or empty")
    run_case(compiler, "V-레나", False, "runtime pt-BR display name is not CP1252 encodable")
    run_case(compiler, "A" * 32, False, "runtime pt-BR display name exceeds legacy capacity")
    print("COMPILE_STAGE_SPAWNS_LOCALIZATION_REGRESSION=PASS")


if __name__ == "__main__":
    main()
