from __future__ import annotations

"""Python replacement for PriTaTor bulk monster conveniences.

The .NET IL proves that the EXP changer substitutes the tokens EXP and LVL in a
formula, evaluates it through DataTable.Compute, warns above MaxExp, then writes
the Monster Experience directive and saves each selected INF.  This port keeps
that behavior but replaces DataTable.Compute with a restricted arithmetic parser
and stages through the transactional Legacy Authoring writer.
"""

import ast
from pathlib import Path
import re
from typing import Any, Iterable

from ..legacy_authoring import _ci_file, _inspect_text_definition, stage_authoring

FORMAT = "PT_PRITATOR_BULK_PYTHON_V1"
_TOKEN_RE = re.compile(r"\b(EXP|LVL)\b", re.IGNORECASE)


class _Arithmetic(ast.NodeVisitor):
    _bin = {
        ast.Add: lambda a,b: a+b,
        ast.Sub: lambda a,b: a-b,
        ast.Mult: lambda a,b: a*b,
        ast.Div: lambda a,b: a/b,
        ast.Mod: lambda a,b: a%b,
    }
    _un = {ast.UAdd: lambda a:+a, ast.USub: lambda a:-a}

    def visit_Expression(self, node: ast.Expression) -> float:
        return float(self.visit(node.body))

    def visit_Constant(self, node: ast.Constant) -> float:
        if isinstance(node.value, bool) or not isinstance(node.value, (int,float)):
            raise ValueError("PRITATOR_FORMULA_CONSTANT_NOT_NUMERIC")
        return float(node.value)

    def visit_BinOp(self, node: ast.BinOp) -> float:
        fn=self._bin.get(type(node.op))
        if fn is None: raise ValueError(f"PRITATOR_FORMULA_OPERATOR_BLOCKED:{type(node.op).__name__}")
        a=self.visit(node.left); b=self.visit(node.right)
        if isinstance(node.op,(ast.Div,ast.Mod)) and b==0:
            raise ValueError("PRITATOR_FORMULA_DIVISION_BY_ZERO")
        return float(fn(a,b))

    def visit_UnaryOp(self, node: ast.UnaryOp) -> float:
        fn=self._un.get(type(node.op))
        if fn is None: raise ValueError(f"PRITATOR_FORMULA_OPERATOR_BLOCKED:{type(node.op).__name__}")
        return float(fn(self.visit(node.operand)))

    def generic_visit(self, node: ast.AST):
        raise ValueError(f"PRITATOR_FORMULA_SYNTAX_BLOCKED:{type(node).__name__}")


def evaluate_formula(formula: str, *, exp: int, level: int) -> dict[str, Any]:
    text=str(formula or "").strip().upper()
    if not text:
        raise ValueError("PRITATOR_FORMULA_REQUIRED")
    substituted=_TOKEN_RE.sub(lambda m: str(exp if m.group(1).upper()=="EXP" else level), text)
    if re.search(r"[A-Z_]", substituted):
        raise ValueError("PRITATOR_FORMULA_UNKNOWN_IDENTIFIER")
    try:
        tree=ast.parse(substituted, mode="eval")
        value=_Arithmetic().visit(tree)
    except SyntaxError as exc:
        raise ValueError("PRITATOR_FORMULA_INVALID") from exc
    # VB Conversions.ToInteger uses banker's rounding for fractional numeric
    # results. Python round() has the same ties-to-even behavior for finite values.
    result=int(round(value))
    return {"formula":text,"substituted":substituted,"value":value,"integer":result}


def _scalar(detail: dict[str,Any], field: str, default: int=0) -> int:
    rows=(detail.get("recognized") or {}).get(field) or []
    if not rows or not rows[0]: return default
    return int(rows[0][0])


def inspect_monster_bulk(server_root: Path, logical_path: str) -> dict[str, Any]:
    logical=str(logical_path).replace("\\","/")
    if not logical.casefold().startswith("gameserver/monster/") or not logical.casefold().endswith(".inf"):
        raise ValueError(f"PRITATOR_MONSTER_PATH_INVALID:{logical}")
    source=_ci_file(Path(server_root),logical)
    if source is None: raise FileNotFoundError(f"PRITATOR_MONSTER_NOT_FOUND:{logical}")
    detail=_inspect_text_definition("MONSTER",source.read_bytes())
    return {
        "logical_path":logical,
        "source":str(source),
        "level":_scalar(detail,"level"),
        "experience":_scalar(detail,"experience"),
        "name":((detail.get("recognized") or {}).get("name") or [[source.stem]])[0][0],
    }


def plan_bulk_experience(server_root: Path, logical_paths: Iterable[str], formula: str, *, max_exp: int | None=None) -> dict[str,Any]:
    rows=[]; warnings=[]
    paths=[str(x) for x in logical_paths]
    if not paths: raise ValueError("PRITATOR_BULK_MONSTERS_REQUIRED")
    constant_formula=not bool(_TOKEN_RE.search(str(formula or "")))
    for logical in paths:
        before=inspect_monster_bulk(server_root,logical)
        calc=evaluate_formula(formula,exp=int(before["experience"]),level=int(before["level"]))
        after=int(calc["integer"])
        if after<0: raise ValueError(f"PRITATOR_EXP_NEGATIVE:{logical}:{after}")
        over=bool(max_exp is not None and after>int(max_exp))
        if over: warnings.append({"logical_path":logical,"reason":"ABOVE_MAX_EXP","value":after,"max_exp":int(max_exp)})
        rows.append({**before,"calculation":calc,"new_experience":after,"above_max":over})
    return {
        "format":FORMAT,"status":"READY","operation":"PRITATOR_BULK_EXPERIENCE",
        "formula":str(formula),"constant_formula":constant_formula,"constant_formula_warning": constant_formula and len(rows)>1,
        "max_exp":max_exp,"rows":rows,"warning_count":len(warnings),"warnings":warnings,
        "legacy_evidence":{
            "formula_engine":"PriTaTor Funktionen.textausrechnung -> DataTable.Compute",
            "variables":["EXP","LVL"],
            "write":"SetMonsterExp + MonsterSaver",
        },
        "port_difference":"Restricted arithmetic evaluation; no arbitrary DataTable.Compute expressions and no live write during planning.",
        "write_authorized":False,
    }


def stage_bulk_experience(project_root: Path, server_root: Path, client_root: Path | None, plan: dict[str,Any]) -> dict[str,Any]:
    if plan.get("status")!="READY" or plan.get("operation")!="PRITATOR_BULK_EXPERIENCE":
        raise ValueError("PRITATOR_BULK_EXP_PLAN_NOT_READY")
    staged=[]
    for row in plan.get("rows") or []:
        spec={
            "kind":"MONSTER","mode":"EDIT","path":row["logical_path"],
            "patch":{"set":{"experience":int(row["new_experience"])}},
        }
        result=stage_authoring(Path(project_root),Path(server_root),client_root,spec)
        staged.append({"logical_path":row["logical_path"],"new_experience":row["new_experience"],"manifest":result["manifest"]})
    return {
        "format":FORMAT,"status":"STAGED","operation":"PRITATOR_BULK_EXPERIENCE",
        "count":len(staged),"staged":staged,
        "publish":"Each generated asset bundle remains review/publish-gated by Legacy Authoring.",
    }

_GOLD_TOKEN_RE = re.compile(r"\b(GOLD|LVL)\b", re.IGNORECASE)


def evaluate_gold_formula(formula: str, *, gold: int, level: int) -> dict[str, Any]:
    """Evaluate the exact PriTaTor Gold/LVL arithmetic surface safely.

    PriTaTor Form3 substitutes GOLD and LVL then delegates to the same
    DataTable.Compute helper used by Bulk EXP.  We deliberately keep the
    replacement arithmetic-only.
    """
    text = str(formula or "").strip().upper()
    if not text:
        raise ValueError("PRITATOR_GOLD_FORMULA_REQUIRED")
    substituted = _GOLD_TOKEN_RE.sub(
        lambda m: str(gold if m.group(1).upper() == "GOLD" else level), text
    )
    if re.search(r"[A-Z_]", substituted):
        raise ValueError("PRITATOR_GOLD_FORMULA_UNKNOWN_IDENTIFIER")
    try:
        tree = ast.parse(substituted, mode="eval")
        value = _Arithmetic().visit(tree)
    except SyntaxError as exc:
        raise ValueError("PRITATOR_GOLD_FORMULA_INVALID") from exc
    return {
        "formula": text,
        "substituted": substituted,
        "value": value,
        "integer": int(round(value)),
    }


def _monster_drop_spec(detail: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    """Convert parsed FallItem rows to the structured authoring representation.

    Returns the complete list plus the index of the first Money row, matching
    PriTaTor GetMonsterGold/SetMonsterGold (which stops at the first such row).
    """
    from ..legacy_authoring import _source_token

    money_token = _source_token("character_tokens", "Money")
    none_token = _source_token("character_tokens", "NoItem")
    rows = ((detail.get("repeated") or {}).get("drops") or [])
    out: list[dict[str, Any]] = []
    money_index: int | None = None
    for idx, vals in enumerate(rows):
        if not vals:
            continue
        try:
            pct = int(vals[0])
        except Exception as exc:
            raise ValueError(f"PRITATOR_DROP_PERCENT_INVALID:{idx}") from exc
        tail = list(vals[1:])
        if tail and tail[0] == money_token:
            if len(tail) not in {2, 3}:
                raise ValueError(f"PRITATOR_MONEY_VALUES_INVALID:{idx}:{tail}")
            money = [int(x) for x in tail[1:]]
            out.append({"percentage": pct, "money": money})
            if money_index is None:
                money_index = len(out) - 1
        elif tail and tail[0] == none_token:
            out.append({"percentage": pct, "none": True})
        else:
            if not tail:
                raise ValueError(f"PRITATOR_DROP_ITEMS_EMPTY:{idx}")
            out.append({"percentage": pct, "items": [str(x) for x in tail]})
    return out, money_index


def inspect_monster_gold(server_root: Path, logical_path: str) -> dict[str, Any]:
    logical = str(logical_path).replace("\\", "/")
    if not logical.casefold().startswith("gameserver/monster/") or not logical.casefold().endswith(".inf"):
        raise ValueError(f"PRITATOR_MONSTER_PATH_INVALID:{logical}")
    source = _ci_file(Path(server_root), logical)
    if source is None:
        raise FileNotFoundError(f"PRITATOR_MONSTER_NOT_FOUND:{logical}")
    detail = _inspect_text_definition("MONSTER", source.read_bytes())
    drops, money_index = _monster_drop_spec(detail)
    values = drops[money_index]["money"] if money_index is not None else []
    return {
        "logical_path": logical,
        "source": str(source),
        "name": ((detail.get("recognized") or {}).get("name") or [[source.stem]])[0][0],
        "level": _scalar(detail, "level"),
        "drops": drops,
        "money_drop_index": money_index,
        "gold_values": values,
    }


def plan_bulk_gold(
    server_root: Path,
    logical_paths: Iterable[str],
    formula: str,
    *,
    max_gold: int | None = None,
) -> dict[str, Any]:
    paths = [str(x) for x in logical_paths]
    if not paths:
        raise ValueError("PRITATOR_BULK_MONSTERS_REQUIRED")
    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    constant_formula = not bool(_GOLD_TOKEN_RE.search(str(formula or "")))
    for logical in paths:
        before = inspect_monster_gold(server_root, logical)
        values = list(before["gold_values"])
        if not values:
            warnings.append({"logical_path": logical, "reason": "MONEY_DROP_NOT_FOUND"})
            rows.append({**before, "status": "REVIEW", "new_gold_values": []})
            continue
        calculations = [
            evaluate_gold_formula(formula, gold=int(value), level=int(before["level"]))
            for value in values
        ]
        after = [int(x["integer"]) for x in calculations]
        if any(x < 0 for x in after):
            raise ValueError(f"PRITATOR_GOLD_NEGATIVE:{logical}:{after}")
        over = bool(max_gold is not None and any(x > int(max_gold) for x in after))
        if over:
            warnings.append({
                "logical_path": logical,
                "reason": "ABOVE_MAX_GOLD",
                "values": after,
                "max_gold": int(max_gold),
            })
        new_drops = [dict(x) for x in before["drops"]]
        new_drops[int(before["money_drop_index"])] = {
            **new_drops[int(before["money_drop_index"])],
            "money": after,
        }
        rows.append({
            **before,
            "status": "READY",
            "calculations": calculations,
            "new_gold_values": after,
            "new_drops": new_drops,
            "above_max": over,
        })
    ready_count = sum(1 for x in rows if x.get("status") == "READY")
    return {
        "format": FORMAT,
        "status": "READY" if ready_count else "REVIEW",
        "operation": "PRITATOR_BULK_GOLD",
        "formula": str(formula),
        "constant_formula": constant_formula,
        "constant_formula_warning": constant_formula and len(rows) > 1,
        "max_gold": max_gold,
        "rows": rows,
        "ready_count": ready_count,
        "review_count": len(rows) - ready_count,
        "warning_count": len(warnings),
        "warnings": warnings,
        "legacy_evidence": {
            "parser": "GetMonsterGold scans first FallItem containing Money and accepts one or two numeric values",
            "formula": "PriTaTor Form3 substitutes GOLD/LVL through Funktionen.textausrechnung",
            "write": "SetMonsterGold preserves FallItem prefix/percentage and rewrites the one/two money values, then MonsterSaver",
        },
        "port_difference": "Arithmetic-only evaluator; preview/stage instead of mutating selected monsters in memory/live server.",
        "write_authorized": False,
    }


def stage_bulk_gold(
    project_root: Path,
    server_root: Path,
    client_root: Path | None,
    plan: dict[str, Any],
) -> dict[str, Any]:
    if plan.get("operation") != "PRITATOR_BULK_GOLD" or plan.get("status") not in {"READY", "REVIEW"}:
        raise ValueError("PRITATOR_BULK_GOLD_PLAN_NOT_READY")
    staged: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in plan.get("rows") or []:
        if row.get("status") != "READY":
            skipped.append({"logical_path": row.get("logical_path"), "reason": "MONEY_DROP_NOT_FOUND"})
            continue
        spec = {
            "kind": "MONSTER",
            "mode": "EDIT",
            "path": row["logical_path"],
            "patch": {"drops": row["new_drops"]},
        }
        result = stage_authoring(Path(project_root), Path(server_root), client_root, spec)
        staged.append({
            "logical_path": row["logical_path"],
            "new_gold_values": row["new_gold_values"],
            "manifest": result["manifest"],
        })
    return {
        "format": FORMAT,
        "status": "STAGED" if staged else "REVIEW",
        "operation": "PRITATOR_BULK_GOLD",
        "count": len(staged),
        "skipped": skipped,
        "staged": staged,
        "publish": "Each generated asset bundle remains review/publish-gated by Legacy Authoring.",
    }
