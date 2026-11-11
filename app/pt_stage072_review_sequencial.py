#!/usr/bin/env python3
"""V20 — Open the 58 validated Etervale Stage0.72 maps one at a time in Blender.

Only reads original assets and the V13/V19 report, and opens a disposable copy of
an already validated preview .blend. Closing Blender advances automatically.
This is a HUMAN REVIEW queue; opening/closing is never counted as visual PASS.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from typing import Any

FORMAT = "PT_ETERVALE_STAGE072_SEQUENTIAL_VISUAL_REVIEW_V20"
VALID_WORKER_STATUS = "PASS_BLENDER_TRANSPORT_AND_VIEW"
VISITED_STATUSES = {"VISTO_SEM_AVALIACAO", "APROVADO_VISUALMENTE", "REVER_VISUALMENTE", "IGNORADO"}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_relative_asset(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"INVALID_ASSET_PATH:{value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or path.suffix.lower() != ".smd" or any(x in (".", "..", "") for x in path.parts):
        raise ValueError(f"INVALID_ASSET_PATH:{value!r}")
    return str(path)


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(directory.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(2 * 1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def load_validated_maps(project_root: Path, report_path: Path) -> tuple[list[dict], Path]:
    project_root = project_root.resolve(strict=True)
    app_root = project_root / "app"
    if not (app_root / "pt_asset.py").is_file():
        raise ValueError(f"PT_ASSET_ROOT_NOT_FOUND:{project_root}")
    report_path = report_path.resolve(strict=True)
    if not _inside(report_path, app_root / "pt_build"):
        raise ValueError("REPORT_OUTSIDE_PT_BUILD_REFUSED")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("format") != "PT_ETERVALE_STAGE072_ALL_MAPS_V13":
        raise ValueError("NOT_A_V13_STAGE072_AUDIT_REPORT")
    if report.get("stage") != 0 or report.get("limited_scan") or not report.get("blender_executed"):
        raise ValueError("REPORT_MUST_BE_FULL_STAGE0_BLENDER_AUDIT")
    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("REPORT_HAS_NO_MAP_ROWS")
    client_root = Path(report["client_root"]).resolve(strict=True)
    if not client_root.is_dir():
        raise ValueError("CLIENT_ASSETS_DIRECTORY_MISSING")

    maps = []
    seen = set()
    for row in rows:
        logical = _safe_relative_asset(row.get("asset"))
        if logical in seen:
            raise ValueError(f"DUPLICATE_MAP:{logical}")
        seen.add(logical)
        if row.get("blender") != VALID_WORKER_STATUS:
            raise ValueError(f"MAP_NOT_VALIDATED_IN_BLENDER:{logical}:{row.get('blender')}")
        src = client_root.joinpath(*PurePosixPath(logical).parts)
        if not src.is_file() or src.is_symlink() or not _inside(src, client_root):
            raise ValueError(f"SOURCE_MISSING_OR_UNSAFE:{logical}")
        evidence = row.get("blender_evidence") or {}
        blend_value = evidence.get("preview_blend")
        if not isinstance(blend_value, str) or not blend_value:
            # Some audits may retain only the worker result on disk.
            digest = hashlib.sha256(logical.encode("utf-8")).hexdigest()[:16]
            worker_result = (report_path.parent / "blender_tasks" / digest / "worker_result.json")
            if worker_result.is_file() and _inside(worker_result, app_root / "pt_build"):
                worker_data = json.loads(worker_result.read_text(encoding="utf-8"))
                if worker_data.get("status") == VALID_WORKER_STATUS:
                    blend_value = worker_data.get("preview_blend")
        if not isinstance(blend_value, str) or not blend_value:
            raise ValueError(f"PREVIEW_PATH_NOT_IN_REPORT:{logical}")
        blend = Path(blend_value)
        if not blend.is_file() or blend.is_symlink() or not _inside(blend, app_root / "pt_build"):
            raise ValueError(f"PREVIEW_MISSING_OR_UNSAFE:{logical}:{blend}")
        if blend.suffix.lower() != ".blend":
            raise ValueError(f"NOT_A_BLEND:{blend}")
        sha = row.get("source_sha256")
        if not isinstance(sha, str) or len(sha) != 64:
            raise ValueError(f"SOURCE_SHA_MISSING:{logical}")
        maps.append({
            "asset": logical,
            "source": src,
            "source_sha256": sha,
            "preview_blend": blend,
            "audit_status": row.get("status"),
            "missing_count": row.get("missing_count", 0),
            "known_missing_count": row.get("known_missing_count", 0),
            "invalid_reference_count": row.get("invalid_reference_count", 0),
        })
    if report.get("stage_files_discovered") != len(maps):
        raise ValueError(f"REPORT_INCOMPLETE:{len(maps)}!={report.get('stage_files_discovered')}")
    return maps, client_root


def _load_events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    events = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if obj.get("format") == FORMAT and isinstance(obj.get("asset"), str):
                events.append(obj)
        except (ValueError, TypeError):
            # A partially written last line (e.g. abrupt power failure)
            # must not destroy earlier completed records.
            print(f"AVISO: evento inválido na linha {lineno}, ignorado", file=sys.stderr)
    return events


def _append_event(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _latest_by_asset(events: list[dict]) -> dict[str, dict]:
    latest = {}
    for item in events:
        latest[item["asset"]] = item
    return latest


def _write_summary(path: Path, events: list[dict], maps: list[dict]) -> None:
    latest = _latest_by_asset(events)
    entries = []
    for m in maps:
        event = latest.get(m["asset"])
        valid_event = bool(event and event.get("source_sha256") == m["source_sha256"])
        result = (event.get("result") if valid_event else "PENDENTE")
        entries.append({
            "mapa": m["asset"], "avaliacao": result,
            "nota": (event.get("note", "") if valid_event else ""),
            "auditoria": m["audit_status"],
            "texturas_ausentes": m["missing_count"],
            "referencias_invalidas": m["invalid_reference_count"],
        })
    csv_path = path.parent / "stage_0_avaliacoes.csv"
    csv_tmp = csv_path.with_name(csv_path.name + ".tmp")
    with csv_tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(entries[0]) if entries else [])
        writer.writeheader()
        writer.writerows(entries)
    os.replace(csv_tmp, csv_path)
    statuses = dict(sorted(Counter(e["avaliacao"] for e in entries).items()))
    summary = {"format": FORMAT, "maps": len(maps), "counts": statuses,
               "visual_pass_only_when_explicitly_rated": True,
               "not_game_runtime_certified": True,
               "csv": str(csv_path), "events": str(path), "updated_utc": _utc()}
    json_path = path.parent / "stage_0_avaliacoes_summary.json"
    tmp = json_path.with_name(json_path.name + ".tmp")
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, json_path)


def _choose_result(asset: str) -> tuple[str, str, bool]:
    """Optional interactive review, only when explicitly enabled by --avaliar."""
    while True:
        try:
            choice = input("Avaliação [a=aprovado, r=rever, s=ignorar, Enter=visto, q=sair]: ").strip().lower()
        except EOFError:
            return "VISTO_SEM_AVALIACAO", "", False
        if choice in ("", "v"):
            return "VISTO_SEM_AVALIACAO", "", False
        if choice in ("a", "ok"):
            return "APROVADO_VISUALMENTE", "", False
        if choice in ("s", "i"):
            return "IGNORADO", "", False
        if choice in ("r", "n"):
            note = input(f"Nota sobre {asset} (opcional): ").strip()
            return "REVER_VISUALMENTE", note[:2000], False
        if choice in ("q", "sair"):
            return "ADIADO", "", True
        print("Escolha a, r, s, Enter ou q.")


def run_review(*, project_root: Path, report_path: Path | None = None,
               blender_command: list[str] | None = None, avaliar: bool = False,
               dry_run: bool = False, limit: int = 0,
               reabrir: str | None = None) -> int:
    project_root = project_root.resolve(strict=True)
    app_root = project_root / "app"
    if report_path is None:
        report_path = app_root / "pt_build/etervale/stage072_all_maps/stage_0_summary.json"
    maps, _ = load_validated_maps(project_root, report_path)
    all_maps = maps
    if reabrir:
        reabrir = _safe_relative_asset(reabrir)
        maps = [m for m in maps if m["asset"] == reabrir]
        if not maps:
            raise ValueError(f"MAP_NOT_IN_AUDIT:{reabrir}")
    helper = app_root / "pt_asset_tool/blender/open_stage072_preview.py"
    if not helper.is_file() or not _inside(helper, app_root):
        raise FileNotFoundError(f"V19_STAGE072_VIEW_SCRIPT_MISSING:{helper}")
    if blender_command is None and not dry_run:
        sys.path.insert(0, str(app_root))
        from pt_asset_tool.dependencies import resolve_blender_command
        blender_command, ready, detail = resolve_blender_command(app_root)
        if not ready:
            raise RuntimeError(f"BLENDER_UNAVAILABLE:{detail}")
    events_path = app_root / "pt_build/etervale/stage072_visual_review/stage_0_events.jsonl"
    events = _load_events(events_path)
    latest = _latest_by_asset(events)
    pending = []
    for m in maps:
        previous = latest.get(m["asset"])
        if reabrir or not previous or previous.get("source_sha256") != m["source_sha256"] or previous.get("result") not in VISITED_STATUSES:
            pending.append(m)
    if limit > 0:
        pending = pending[:limit]
    print(f"REVISAO_STAGE072 total={len(maps)} pendentes={len(pending)} avaliacao={'MANUAL' if avaliar else 'SEM_PERGUNTAS'}", flush=True)
    print("FECHA O BLENDER para abrir o mapa seguinte. Ctrl+C interrompe e preserva o registo.", flush=True)
    if not pending:
        if not dry_run:
            _write_summary(events_path, events, all_maps)
        print("TODOS_OS_MAPAS_VISITADOS: nenhum Blender aberto.")
        return 0

    failed = 0
    for idx, m in enumerate(pending, 1):
        asset = m["asset"]
        print(f"\n[{idx}/{len(pending)}] MAPA={asset} audit={m['audit_status']} missing={m['missing_count']} invalid={m['invalid_reference_count']}", flush=True)
        if _file_sha256(m["source"]) != m["source_sha256"]:
            print(f"BLOQUEADO: o SMD mudou desde a auditoria: {asset}", file=sys.stderr, flush=True)
            event = {"format": FORMAT, "time_utc": _utc(), "asset": asset,
                     "source_sha256": m["source_sha256"], "result": "FONTE_ALTERADA", "note": "Hash diferente do relatório V13"}
            _append_event(events_path, event)
            events.append(event)
            _write_summary(events_path, events, all_maps)
            failed += 1
            continue
        if dry_run:
            print(f"DRY_RUN abriria {m['preview_blend']}", flush=True)
            continue
        # Keep the disposable copy IN THE SAME DIRECTORY as the original .blend;
        # relative image paths (//...) must still resolve. NEVER open the certified
        # preview for editing or alter its transport hashes.
        fd, temp_name = tempfile.mkstemp(prefix=".pt_stage072_revisao_", suffix=".blend", dir=m["preview_blend"].parent)
        os.close(fd)
        preview_copy = Path(temp_name)
        returncode = -1
        failure_note = ""
        try:
            shutil.copy2(m["preview_blend"], preview_copy)
            command = list(blender_command or []) + [str(preview_copy), "--python", str(helper)]
            if not blender_command:
                raise RuntimeError("BLENDER_COMMAND_EMPTY")
            print("BLENDER_ABRINDO — fecha a janela para continuar...", flush=True)
            returncode = subprocess.run(command, cwd=str(project_root), check=False).returncode
        except KeyboardInterrupt:
            print("\nINTERRUPT: mapa atual não foi marcado como visto; podes retomar.", file=sys.stderr, flush=True)
            raise
        except Exception as exc:
            failure_note = f"{type(exc).__name__}: {exc}"
            print(f"ERRO_ABERTURA: {failure_note}", file=sys.stderr, flush=True)
        finally:
            preview_copy.unlink(missing_ok=True)
            # Blender may create a backup if the human presses Ctrl+S. This is
            # only the disposable review copy, never the validated .blend.
            Path(str(preview_copy) + "1").unlink(missing_ok=True)

        if returncode == 0 and not failure_note:
            if avaliar:
                result, note, stop = _choose_result(asset)
            else:
                result, note, stop = "VISTO_SEM_AVALIACAO", "", False
        else:
            result, note, stop = "ERRO_ABERTURA", failure_note or f"Blender exit code {returncode}", False
            failed += 1
        event = {"format": FORMAT, "time_utc": _utc(), "asset": asset,
                 "source_sha256": m["source_sha256"], "result": result,
                 "note": note, "blender_returncode": returncode,
                 "audit_status": m["audit_status"]}
        _append_event(events_path, event)
        events.append(event)
        _write_summary(events_path, events, all_maps)
        print(f"FECHADO: {asset} => {result}", flush=True)
        if stop:
            print("REVISAO_INTERROMPIDA_A_PEDIDO. Retoma com o mesmo comando.", flush=True)
            break
    if dry_run:
        print("DRY_RUN: nenhum Blender aberto e nenhum registo alterado.", flush=True)
        return 0
    print(f"\nREGISTOS: {events_path}")
    print(f"RESUMO: {events_path.parent / 'stage_0_avaliacoes_summary.json'}")
    print(f"CSV: {events_path.parent / 'stage_0_avaliacoes.csv'}")
    return 3 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Abre os Stage0.72 validados um a um; fechar Blender abre o próximo.")
    ap.add_argument("--project-root", type=Path, default=Path.cwd(), help="diretório pt_asset_tool (default: cwd)")
    ap.add_argument("--report", type=Path, help="stage_0_summary.json V13/V19 (default: pt_build)")
    ap.add_argument("--avaliar", action="store_true", help="pedir aprovação/revisão depois de fechar cada Blender")
    ap.add_argument("--dry-run", action="store_true", help="listar sequência sem abrir Blender")
    ap.add_argument("--limit", type=int, default=0, help="abrir apenas os primeiros N pendentes")
    ap.add_argument("--reabrir", help="reabrir um mapa específico, mesmo se já foi visto")
    args = ap.parse_args(argv)
    try:
        return run_review(project_root=args.project_root, report_path=args.report,
                          avaliar=args.avaliar, dry_run=args.dry_run,
                          limit=max(args.limit, 0), reabrir=args.reabrir)
    except KeyboardInterrupt:
        print("\nINTERRUPTED: registos anteriores preservados.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"REVISAO_STAGE072_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
