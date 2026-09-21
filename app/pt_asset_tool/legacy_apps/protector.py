from __future__ import annotations

"""Safe core replacement for PT Protector Reloaded.

The original VB6 application combines log watching, Hotuk allow/exclusion lists,
error aliases/libraries, disconnect handling and a configurable SQL block action.
This port makes detection deterministic/read-only; account blocking is an explicit
parameterized SQL plan.
"""

from dataclasses import dataclass, asdict
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable

FORMAT="PT_LEGACY_PROTECTOR_V1"
BLOCK_CONFIRM="APPLY ACCOUNT BLOCK"


def read_line_set(path: Path) -> list[str]:
    p=Path(path)
    if not p.is_file(): return []
    out=[]
    for raw in p.read_text(encoding="latin-1",errors="replace").splitlines():
        s=raw.strip()
        if s and not s.startswith(("#",";","//")): out.append(s)
    return out


def load_rule_directory(root: Path) -> dict[str,Any]:
    root=Path(root)
    files={
        "excluded_accounts":"excluded_account.txt",
        "excluded_ips":"excluded_ip.txt",
        "error_aliases":"error_alias.txt",
        "error_library":"error_library.txt",
    }
    data={k:read_line_set(root/v) for k,v in files.items()}
    return {"format":FORMAT,"status":"PASS","root":str(root),**data}


def parse_alias_lines(lines: Iterable[str]) -> list[tuple[str,str]]:
    out=[]
    for line in lines:
        if "=" in line:
            a,b=line.split("=",1); out.append((a.strip(),b.strip()))
        elif "|" in line:
            a,b=line.split("|",1); out.append((a.strip(),b.strip()))
        else:
            out.append((line.strip(),line.strip()))
    return [(a,b) for a,b in out if a]


ACTION_PREFIX_RE = re.compile(r"^:(skip|ban|dc)\s+", re.IGNORECASE)
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def parse_error_rule(line: str) -> dict[str, Any]:
    """Parse the PTprotector action prefix proven by native string evidence.

    The original binary contains the exact grammar ``^:(skip|ban|dc) `` plus
    explicit diagnostics requiring ``%ip``/``%id`` for actions that need them.
    No deployment fixture of error_library.txt was supplied, so the remainder
    of the pattern is preserved as a literal search expression rather than
    inventing undocumented wildcard/alias semantics.
    """
    raw = str(line).strip()
    action = "review"
    body = raw
    m = ACTION_PREFIX_RE.match(raw)
    if m:
        action = m.group(1).lower()
        body = raw[m.end():].strip()
    required = []
    for ident in ("%id", "%ip"):
        if ident.casefold() in body.casefold():
            required.append(ident[1:])
    # Match a stable literal skeleton after removing the two proven identifiers.
    # Extraction happens independently from the actual log line.
    skeleton = re.sub(r"(?i)%(?:id|ip)", "", body)
    skeleton = " ".join(skeleton.split())
    return {
        "raw": raw,
        "action": action,
        "pattern": body,
        "required_identifiers": required,
        "literal_skeleton": skeleton,
        "syntax_coverage": "PROVEN_ACTION_PREFIX_LITERAL_PATTERN",
    }


def _extract_identity(line: str, account_regex: str, ip_regex: str) -> tuple[str | None, str | None]:
    am = re.search(account_regex, line)
    account = am.group(1) if am else None
    im = re.search(ip_regex, line)
    ip = im.group(0) if im else None
    return account, ip


def _rule_matches(rule: dict[str, Any], line: str) -> bool:
    skeleton = str(rule.get("literal_skeleton") or "").strip()
    if not skeleton:
        # A rule containing only identifiers is too broad to act on safely.
        return False
    return skeleton.casefold() in line.casefold()


def protector_capabilities() -> dict[str, Any]:
    return {
        "format": FORMAT,
        "status": "PASS",
        "runtime": "localhost + SQLite",
        "proven_rule_syntax": {
            "action_prefix": r"^:(skip|ban|dc) ",
            "identifiers": ["%id", "%ip"],
            "files": ["error_library.txt", "error_alias.txt", "excluded_account.txt", "excluded_ip.txt"],
        },
        "implemented": [
            "load rule/exclusion files",
            "parse proven action prefix",
            "account/IP extraction",
            "exclusion handling",
            "deterministic review/skip/ban/disconnect recommendation",
            "SQLite account block plan/apply",
        ],
        "not_auto_executed": ["ban", "disconnect"],
        "why": "Legacy automatic actions are converted to reviewable plans so malformed logs/rules cannot mutate live state silently.",
        "unsupported_syntax_policy": "Preserve original rule and report REVIEW instead of guessing undocumented grammar.",
    }


def analyze_log_lines(lines: Iterable[str], *, rule_root: Path | None=None, account_regex: str=r"(?i)account\s*[:=]\s*([A-Za-z0-9_.-]+)", ip_regex: str=r"\b(?:\d{1,3}\.){3}\d{1,3}\b") -> dict[str,Any]:
    rules=load_rule_directory(rule_root) if rule_root else {"excluded_accounts":[],"excluded_ips":[],"error_aliases":[],"error_library":[]}
    excluded_accounts={x.casefold() for x in rules.get("excluded_accounts",[])}
    excluded_ips=set(rules.get("excluded_ips",[]))
    aliases=parse_alias_lines(rules.get("error_aliases",[]))
    library=[parse_error_rule(x) for x in rules.get("error_library",[])]
    events=[]
    for lineno,line in enumerate(lines,1):
        text=str(line).rstrip("\n")
        account,ip=_extract_identity(text,account_regex,ip_regex)
        matched=[]
        # Alias matching remains intentionally non-destructive: aliases explain
        # the log but do not invent an action unless an error_library rule does.
        for needle,label in aliases:
            if needle.casefold() in text.casefold():
                matched.append({"kind":"alias","needle":needle,"label":label,"action":"review"})
        for rule in library:
            if _rule_matches(rule,text):
                missing=[x for x in rule["required_identifiers"] if (x=="id" and not account) or (x=="ip" and not ip)]
                matched.append({"kind":"library","rule":rule,"missing_identifiers":missing})
        if not matched:
            continue
        excluded=bool((account and account.casefold() in excluded_accounts) or (ip and ip in excluded_ips))
        actions=[]
        for match in matched:
            if match["kind"]!="library":
                continue
            rule=match["rule"]
            if match["missing_identifiers"]:
                actions.append({"action":"review","reason":"REQUIRED_IDENTIFIER_MISSING","missing":match["missing_identifiers"],"rule":rule["raw"]})
            else:
                actions.append({"action":rule["action"],"reason":"LEGACY_RULE_ACTION","rule":rule["raw"]})
        if excluded:
            recommended="IGNORE_EXCEPTION"
        elif any(x["action"]=="ban" for x in actions):
            recommended="PLAN_BAN"
        elif any(x["action"]=="dc" for x in actions):
            recommended="PLAN_DISCONNECT"
        elif actions and all(x["action"]=="skip" for x in actions):
            recommended="SKIP"
        else:
            recommended="REVIEW"
        events.append({
            "line":lineno,"text":text,"account":account,"ip":ip,"matches":matched,
            "actions":actions,"excluded":excluded,"recommended_action":recommended,
            "automatic_action_executed":False,
        })
    return {
        "format":FORMAT,"status":"PASS","events":events,"event_count":len(events),
        "rule_count":len(library),"policy":"Detection/planning only; no automatic block/disconnect.",
        "capabilities":protector_capabilities(),
    }

def plan_account_block_sqlite(*, table: str, account_column: str, account: str, block_column: str="BlockChk", block_value: int=1, reason_column: str|None=None, reason: str|None=None, ip_column: str|None=None, ip: str|None=None, date_column: str|None=None, date_value: str|None=None) -> dict[str,Any]:
    ident=re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    for label,val in (("table",table),("account_column",account_column),("block_column",block_column)):
        if not ident.fullmatch(val): raise ValueError(f"INVALID_SQL_IDENTIFIER:{label}")
    assignments=[f"[{block_column}]=?"]; params:[Any]=[int(block_value)]
    for col,val in ((reason_column,reason),(ip_column,ip),(date_column,date_value)):
        if col:
            if not ident.fullmatch(col): raise ValueError("INVALID_SQL_IDENTIFIER:optional")
            assignments.append(f"[{col}]=?"); params.append(val)
    params.append(account)
    sql=f"UPDATE [{table}] SET {', '.join(assignments)} WHERE [{account_column}]=?"
    return {"format":FORMAT,"status":"READY","operation":"ACCOUNT_BLOCK_SQLITE","sql":sql,"params":params,"account":account,"database":"SQLite","network_required":False,"write_authorized":False,"legacy_difference":"PT Protector allowed configurable SQL Server text. The Python port uses local SQLite, parameterizes values and validates identifiers."}


def plan_account_block(**kwargs: Any) -> dict[str, Any]:
    """Backward-compatible name; active database backend is local SQLite."""
    return plan_account_block_sqlite(**kwargs)


def apply_account_block(plan: dict[str,Any], *, connection: Any, confirmation: str) -> dict[str,Any]:
    if confirmation != BLOCK_CONFIRM: raise ValueError(f"CONFIRMATION_REQUIRED:{BLOCK_CONFIRM}")
    if plan.get("status")!="READY" or plan.get("operation")!="ACCOUNT_BLOCK_SQLITE": raise ValueError("ACCOUNT_BLOCK_PLAN_NOT_READY")
    cur=connection.cursor(); cur.execute(plan["sql"], tuple(plan["params"])); connection.commit()
    return {"format":FORMAT,"status":"PASS","operation":"ACCOUNT_BLOCK_SQLITE","account":plan["account"],"rowcount":getattr(cur,"rowcount",None)}


def apply_account_block_sqlite(plan: dict[str,Any], *, db_path: Path, confirmation: str) -> dict[str,Any]:
    with sqlite3.connect(Path(db_path)) as db:
        return apply_account_block(plan, connection=db, confirmation=confirmation)
