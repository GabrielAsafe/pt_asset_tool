from __future__ import annotations

"""Local-server replacements for the useful Japaokiko/Restarter tasks.

The current game stack is localhost + SQLite.  Historical Windows firewall and
SQL Server network administration are intentionally obsolete: they are provenance
only and are not surfaced as executable product capabilities.
"""

from pathlib import Path
import configparser
import re
import sqlite3
from typing import Any

from .common import atomic_write_text, backup_file, sha256_file

FORMAT = "PT_LEGACY_SERVER_ADMIN_V2"
HOTUK_CONFIRM = "APPLY HOTUK CONFIG"
RESTarter_CONFIRM = "APPLY RESTARTER CONFIG"


def local_runtime_policy() -> dict[str, Any]:
    """Describe the modern replacement for Portas SQL/network setup.

    Nothing is opened on the network.  The server and database are local; SQLite
    database files are opened directly by Python/server processes.
    """
    return {
        "format": FORMAT,
        "status": "PASS",
        "network_mode": "LOCALHOST_ONLY",
        "database": "SQLite",
        "firewall_required": False,
        "sql_server_required": False,
        "odbc_required": False,
        "legacy_portas_sql": "OBSOLETE",
        "reason": "The active game stack uses local processes and SQLite files; no SQL Server listener or Windows firewall rule is needed.",
    }


def firewall_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Compatibility shim: historical Portas SQL is obsolete in this stack."""
    return local_runtime_policy() | {
        "operation": "NO_FIREWALL_NEEDED",
        "status": "NOT_APPLICABLE",
        "commands": [],
        "write_authorized": False,
    }


def apply_firewall_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
    raise ValueError("FIREWALL_NOT_APPLICABLE: localhost + SQLite requires no Portas SQL operation")

def parse_restarter_config(path: Path) -> dict[str, Any]:
    p=Path(path)
    cfg=configparser.ConfigParser(interpolation=None)
    cfg.read(p, encoding="latin-1")
    section="PT Restarter"
    if not cfg.has_section(section):
        raise ValueError("RESTarter_SECTION_MISSING:PT Restarter")
    return {
        "format":FORMAT,"status":"PASS","operation":"RESTarter_CONFIG","path":str(p),
        "sha256":sha256_file(p),"executable":cfg.get(section,"NomeEXE",fallback="").strip(),
        "startup_message":cfg.get(section,"Mensagem",fallback=""),
        "reverse_boundary":"Only ConfigRestarter.ini was supplied; no restarter executable was present to reverse.",
    }


def plan_restarter_config(path: Path, *, executable: str, startup_message: str) -> dict[str, Any]:
    p=Path(path); old=sha256_file(p) if p.is_file() else None
    if not executable.strip() or any(x in executable for x in ("\n","\r")):
        raise ValueError("RESTarter_EXECUTABLE_REQUIRED")
    text=f"[PT Restarter]\nNomeEXE={executable.strip()}\nMensagem={startup_message}\n"
    return {"format":FORMAT,"status":"READY","operation":"RESTarter_CONFIG_WRITE","path":str(p),"sha256_before":old,"new_text":text,"write_authorized":False}


def apply_restarter_config(plan: dict[str, Any], *, confirmation: str, backup_root: Path) -> dict[str, Any]:
    if confirmation != RESTarter_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{RESTarter_CONFIRM}")
    p=Path(plan["path"]); actual=sha256_file(p) if p.is_file() else None
    if actual != plan.get("sha256_before"):
        raise ValueError("RESTarter_CONFIG_DRIFTED")
    b=backup_file(p,backup_root,label="restarter_config")
    atomic_write_text(p,str(plan["new_text"]),encoding="latin-1",newline="\r\n")
    return {"format":FORMAT,"status":"PASS","path":str(p),"backup":str(b) if b else None,"sha256_after":sha256_file(p)}


# Japaokiko visibly targets C:/SERVER/hotuk.ini and exposes server IP, premium
# and age/event fields.  The file varies between server revisions, therefore the
# port uses a lossless line editor instead of inventing one fixed schema.
_LINE_RE=re.compile(r"^(?P<prefix>\s*[*A-Za-z0-9_.-]+)(?P<sep>\s*(?:=|\s)\s*)(?P<value>.*)$")


def inspect_hotuk(path: Path) -> dict[str, Any]:
    p=Path(path); raw=p.read_text(encoding="latin-1",errors="replace")
    entries=[]
    for n,line in enumerate(raw.splitlines(),1):
        m=_LINE_RE.match(line)
        if m and not line.lstrip().startswith(("#",";","//")):
            entries.append({"line":n,"key":m.group("prefix").strip(),"value":m.group("value").strip(),"raw":line})
    return {"format":FORMAT,"status":"PASS","operation":"HOTUK_INSPECT","path":str(p),"sha256":sha256_file(p),"entries":entries,"raw_text":raw}


def plan_hotuk_updates(path: Path, updates: dict[str,str]) -> dict[str, Any]:
    p=Path(path); info=inspect_hotuk(p); lines=info["raw_text"].splitlines()
    remaining={str(k).casefold(): (str(k),str(v)) for k,v in updates.items()}
    changed=[]
    for i,line in enumerate(lines):
        m=_LINE_RE.match(line)
        if not m or line.lstrip().startswith(("#",";","//")):
            continue
        key=m.group("prefix").strip(); hit=remaining.pop(key.casefold(),None)
        if hit:
            _orig,newv=hit; lines[i]=f"{m.group('prefix')}{m.group('sep')}{newv}"; changed.append(key)
    # Missing settings are appended explicitly rather than silently ignored.
    for _,(key,val) in remaining.items():
        lines.append(f"{key}={val}"); changed.append(key)
    return {"format":FORMAT,"status":"READY","operation":"HOTUK_UPDATE","path":str(p),"sha256_before":info["sha256"],"updates":updates,"changed_keys":changed,"new_text":"\n".join(lines)+"\n","write_authorized":False}


def apply_hotuk_updates(plan: dict[str, Any], *, confirmation: str, backup_root: Path) -> dict[str, Any]:
    if confirmation != HOTUK_CONFIRM: raise ValueError(f"CONFIRMATION_REQUIRED:{HOTUK_CONFIRM}")
    p=Path(plan["path"])
    if sha256_file(p) != plan.get("sha256_before"): raise ValueError("HOTUK_DRIFTED_SINCE_PLAN")
    b=backup_file(p,backup_root,label="hotuk")
    atomic_write_text(p,str(plan["new_text"]),encoding="latin-1",newline="\r\n")
    return {"format":FORMAT,"status":"PASS","operation":"HOTUK_UPDATE","path":str(p),"backup":str(b) if b else None,"sha256_after":sha256_file(p)}


def bprank_sqlite_plan(*, table: str="GameRecordBPRank") -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise ValueError("INVALID_TABLE_NAME")
    return {
        "format": FORMAT, "status": "READY", "operation": "BPRANK_NEXT_SQLITE",
        "select_sql": f'SELECT CharName, BP, DP FROM "{table}" WHERE ok=0 ORDER BY BP DESC LIMIT 1',
        "mark_sql": f'UPDATE "{table}" SET ok=1 WHERE CharName=?',
        "database": "SQLite",
        "network_required": False,
        "legacy_difference": "SQL Server TOP syntax and network setup were removed; values remain parameterized.",
        "write_authorized": False,
    }


def bprank_sql_plan(*, table: str="GameRecordBPRank") -> dict[str, Any]:
    """Backward-compatible name; now returns the SQLite-local plan."""
    return bprank_sqlite_plan(table=table)


def fetch_next_bprank(db_path: Path, *, table: str="GameRecordBPRank") -> dict[str, Any]:
    plan = bprank_sqlite_plan(table=table)
    with sqlite3.connect(Path(db_path)) as db:
        row = db.execute(plan["select_sql"]).fetchone()
    return {"format": FORMAT, "status": "PASS", "operation": "BPRANK_NEXT_SQLITE", "row": None if row is None else {"char_name": row[0], "bp": row[1], "dp": row[2]}}


def mark_bprank_processed(db_path: Path, char_name: str, *, table: str="GameRecordBPRank") -> dict[str, Any]:
    plan = bprank_sqlite_plan(table=table)
    with sqlite3.connect(Path(db_path)) as db:
        cur = db.execute(plan["mark_sql"], (char_name,))
        db.commit()
        count = cur.rowcount
    return {"format": FORMAT, "status": "PASS", "operation": "BPRANK_MARK_SQLITE", "char_name": char_name, "rowcount": count}

SERVER_START_CONFIRM = "START LOCAL SERVER"


def restarter_launch_plan(config_path: Path, *, server_root: Path, wine_command: str | None = None) -> dict[str, Any]:
    """Build the Linux/Wine launch plan for ConfigRestarter.ini.

    Only the INI survived from the historical restarter, so the Python supervisor
    implements the useful contract explicitly: locate NomeEXE under the local
    server root, launch it from its own working directory, and optionally restart
    it.  SQL/network setup is intentionally absent because the active runtime is
    localhost + SQLite.
    """
    import shutil
    cfg = parse_restarter_config(Path(config_path))
    root = Path(server_root).expanduser().resolve()
    exe_name = str(cfg.get("executable") or "").strip()
    if not exe_name:
        return {"format": FORMAT, "status": "BLOCKED", "operation": "SERVER_LAUNCH_PLAN", "reason": "RESTarter_EXECUTABLE_EMPTY"}
    candidate = Path(exe_name)
    exe = candidate if candidate.is_absolute() else root / candidate
    exe = exe.expanduser().resolve()
    if not exe.is_file():
        return {
            "format": FORMAT, "status": "BLOCKED", "operation": "SERVER_LAUNCH_PLAN",
            "reason": "SERVER_EXECUTABLE_NOT_FOUND", "server_root": str(root), "executable": str(exe),
        }
    suffix = exe.suffix.casefold()
    if suffix == ".exe":
        launcher = wine_command or shutil.which("wine") or shutil.which("wine64")
        if not launcher:
            return {
                "format": FORMAT, "status": "BLOCKED", "operation": "SERVER_LAUNCH_PLAN",
                "reason": "WINE_NOT_FOUND", "server_root": str(root), "executable": str(exe),
                "install": "Fedora: sudo dnf install wine",
            }
        command = [str(launcher), str(exe)]
        runtime = "WINE"
    else:
        command = [str(exe)]
        runtime = "NATIVE"
    return {
        "format": FORMAT,
        "status": "READY",
        "operation": "SERVER_LAUNCH_PLAN",
        "server_root": str(root),
        "config_path": str(Path(config_path).resolve()),
        "executable": str(exe),
        "runtime": runtime,
        "command": command,
        "cwd": str(exe.parent),
        "startup_message": cfg.get("startup_message") or "",
        "database_mode": "SQLite/local",
        "network_mode": "LOCALHOST_ONLY",
        "write_authorized": False,
    }


def run_server_once(plan: dict[str, Any], *, confirmation: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run one server process synchronously and report its exit code.

    This is intentionally one-shot.  A UI/background supervisor can call it in a
    bounded restart loop without hiding an immortal process inside library code.
    """
    import os
    import subprocess
    import time
    if confirmation != SERVER_START_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{SERVER_START_CONFIRM}")
    if plan.get("status") != "READY" or plan.get("operation") != "SERVER_LAUNCH_PLAN":
        raise ValueError("SERVER_LAUNCH_PLAN_NOT_READY")
    started = time.time()
    merged = os.environ.copy()
    if env:
        merged.update({str(k): str(v) for k, v in env.items()})
    cp = subprocess.run(
        [str(x) for x in plan["command"]],
        cwd=str(plan["cwd"]),
        env=merged,
        check=False,
    )
    return {
        "format": FORMAT,
        "status": "PASS" if cp.returncode == 0 else "EXITED_ERROR",
        "operation": "SERVER_RUN_ONCE",
        "command": list(plan["command"]),
        "cwd": str(plan["cwd"]),
        "returncode": int(cp.returncode),
        "runtime_seconds": round(time.time() - started, 3),
        "startup_message": plan.get("startup_message") or "",
    }


def bounded_restart_policy(*, max_restarts: int = 5, delay_seconds: float = 5.0) -> dict[str, Any]:
    """Describe the safer replacement for an unconditional historical restarter loop."""
    if max_restarts < 0 or max_restarts > 100:
        raise ValueError("MAX_RESTARTS_RANGE:0..100")
    if delay_seconds < 0 or delay_seconds > 3600:
        raise ValueError("RESTART_DELAY_RANGE:0..3600")
    return {
        "format": FORMAT,
        "status": "PASS",
        "operation": "SERVER_RESTART_POLICY",
        "max_restarts": int(max_restarts),
        "delay_seconds": float(delay_seconds),
        "legacy_difference": "The Python port uses a bounded restart budget instead of an unbounded hidden restart loop.",
    }
