#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

from extract_legacy_maps import parse as extract_legacy_maps


class ExpressionError(ValueError):
    pass


class IntExpressionEvaluator:
    def __init__(self, defines: dict[str, str]):
        self.defines = defines
        self.cache: dict[str, int] = {}

    def evaluate(self, expr: str, variables: dict[str, int] | None = None) -> int:
        variables = variables or {}
        text = expr.strip()
        if text in variables:
            return int(variables[text])
        if text in self.cache and not variables:
            return self.cache[text]
        try:
            node = ast.parse(text, mode="eval").body
        except SyntaxError as exc:
            raise ExpressionError(f"unsupported integer expression: {expr!r}") from exc
        value = self._eval_node(node, variables, set())
        if not variables:
            self.cache[text] = value
        return value

    def _eval_node(self, node: ast.AST, variables: dict[str, int], stack: set[str]) -> int:
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return int(node.value)
        if isinstance(node, ast.Name):
            if node.id in variables:
                return int(variables[node.id])
            if node.id not in self.defines:
                raise ExpressionError(f"unknown integer symbol: {node.id}")
            if node.id in stack:
                raise ExpressionError(f"recursive integer symbol: {node.id}")
            stack.add(node.id)
            try:
                parsed = ast.parse(self.defines[node.id], mode="eval").body
                return self._eval_node(parsed, variables, stack)
            finally:
                stack.remove(node.id)
        if isinstance(node, ast.UnaryOp):
            value = self._eval_node(node.operand, variables, stack)
            if isinstance(node.op, ast.UAdd): return value
            if isinstance(node.op, ast.USub): return -value
            if isinstance(node.op, ast.Invert): return ~value
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left, variables, stack)
            right = self._eval_node(node.right, variables, stack)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, ast.FloorDiv): return left // right
            if isinstance(node.op, ast.Div): return int(left / right)
            if isinstance(node.op, ast.LShift): return left << right
            if isinstance(node.op, ast.RShift): return left >> right
            if isinstance(node.op, ast.BitOr): return left | right
            if isinstance(node.op, ast.BitAnd): return left & right
            if isinstance(node.op, ast.BitXor): return left ^ right
        raise ExpressionError(f"unsupported integer expression node: {ast.dump(node)}")


def parse_defines(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("//", 1)[0].strip()
        m = re.match(r"#\s*define\s+([A-Za-z_]\w*)\s+(.+?)\s*$", line)
        if not m:
            continue
        name, expr = m.groups()
        # Ignore function-like/non-numeric macros. They will fail explicitly if referenced.
        if name.endswith(")"):
            continue
        result[name] = expr.strip()
    return result


def build_evaluator(source_root: Path, profile: str, legacy_source: Path) -> IntExpressionEvaluator:
    candidates = [
        source_root / ("SrcGame/src/systems/world/field/field.h" if profile == "client" else "SrcServer/src/systems/world/field/field.h"),
        source_root / ("SrcGame/src/systems/network/client/netplay.h" if profile == "client" else "SrcServer/src/systems/network/server_gameplay/netplay.h"),
        source_root / ("Shared/audio/effects/EffectSoundLegacyCatalog.h" if profile == "client" else "Shared/audio/effects/effectsnd_legacy_server.h"),
        legacy_source,
    ]
    defines: dict[str, str] = {}
    for path in candidates:
        defines.update(parse_defines(path))
    return IntExpressionEvaluator(defines)


def symbolic_value(expr: str | None, evaluator: IntExpressionEvaluator, prefix: str | None = None) -> dict[str, Any]:
    if expr is None:
        return {"legacy_value": 0}
    value = evaluator.evaluate(expr)
    item: dict[str, Any] = {"legacy_value": value}
    if re.fullmatch(r"[A-Za-z_]\w*", expr):
        if prefix:
            suffix = expr
            prefixes = {
                "state": "FIELD_STATE_",
                "sky": "FIELD_BACKIMAGE_",
                "music": "BGM_CODE_",
                "server": "PLAY_SERVER_CODE_",
                "event": "FIELD_EVENT_",
            }
            marker = prefixes[prefix]
            if suffix.startswith(marker):
                item["id"] = f"{prefix}.{suffix[len(marker):].casefold()}"
        item["legacy_symbol"] = expr
        if "id" in item:
            # Match the historical semantic-catalog key order used in handoffs.
            return {"id": item["id"], "legacy_value": value, "legacy_symbol": expr}
    return item


def int_expr(expr: str, evaluator: IntExpressionEvaluator, cnt: int) -> int:
    return evaluator.evaluate(expr, {"cnt": cnt})


def target_code(expr: str, evaluator: IntExpressionEvaluator, cnt: int) -> int:
    m = re.fullmatch(r"&\s*sField\s*\[(.+)\]", expr.strip())
    if not m:
        raise ExpressionError(f"unsupported field target expression: {expr!r}")
    return evaluator.evaluate(m.group(1), {"cnt": cnt})


def condition_features(condition: str | None) -> dict[str, list[str]] | None:
    if not condition:
        return None
    normalized = re.sub(r"\s+", "", condition)
    if normalized == "defined(WORLDCUP_FIELD)":
        return {"require": ["worldcup_field"], "forbid": []}
    if normalized in ("!(defined(WORLDCUP_FIELD))", "!defined(WORLDCUP_FIELD)"):
        return {"require": [], "forbid": ["worldcup_field"]}
    raise ValueError(f"unsupported map compile-time condition: {condition}")


def portable_source_path(source_root: Path, source_path: Path) -> str:
    """Serialize provenance relative to the repository/source root when possible."""
    root = source_root.resolve()
    source = source_path.resolve()
    try:
        return source.relative_to(root).as_posix()
    except ValueError:
        # Inputs outside source-root are intentionally reduced to a stable leaf name;
        # canonical catalogs must never capture machine-local absolute paths.
        return source.name


def semanticize(shadow: dict, profile: str, source_root: Path, source_path: Path) -> dict:
    evaluator = build_evaluator(source_root, profile, source_path)
    provenance_source = portable_source_path(source_root, source_path)
    static_shadow = [m for m in shadow["maps"] if int(m["legacy_field_code"]) < 53]
    if len(static_shadow) != 53 or [int(m["legacy_field_code"]) for m in static_shadow] != list(range(53)):
        raise ValueError("SMAP v1 semanticizer expects contiguous legacy static fields 0..52")
    id_by_code = {int(m["legacy_field_code"]): m["id"] for m in static_shadow}

    maps: list[dict[str, Any]] = []
    recognized_ops = {
        "set_name", "add_stage_object", "set_center", "add_start_point", "add_gate",
        "add_warp_gate", "add_warp_out_gate", "add_ambient", "set_back_image",
        "set_property", "set_active_warp_property",
    }
    recognized_properties = {"State", "BackMusicCode", "FieldEvent", "ServerCode", "LimitLevel", "FieldSight"}

    for raw in static_shadow:
        code = int(raw["legacy_field_code"])
        if raw.get("unsupported_cpp"):
            raise ValueError(f"field {code}: extractor left unsupported sField statements")
        unknown_ops = sorted({op.get("op") for op in raw.get("operations", []) if op.get("op") not in recognized_ops})
        if unknown_ops:
            raise ValueError(f"field {code}: unsupported extracted operations: {unknown_ops}")
        props = raw.get("properties_cpp") or {}
        unknown_properties = sorted(set(props) - recognized_properties)
        if unknown_properties:
            raise ValueError(f"field {code}: unsupported direct properties: {unknown_properties}")
        back = list(raw.get("back_images_cpp") or [])
        while len(back) < 3: back.append(None)

        def e(expr: str) -> int:
            return int_expr(expr, evaluator, code)

        stage_objects = []
        for op in raw.get("operations", []):
            if op.get("op") != "add_stage_object":
                continue
            args = op.get("args") or []
            if not args or not isinstance(args[0], str):
                raise ValueError(f"field {code}: non-literal stage-object path")
            item: dict[str, Any] = {"asset": args[0], "bip_animation": 0}
            if len(args) > 1:
                arg = args[1]
                if isinstance(arg, dict):
                    item["bip_animation"] = e(str(arg.get("cpp_expr")))
                elif arg is not None:
                    item["bip_animation"] = int(arg)
            features = condition_features(op.get("condition_cpp"))
            if features:
                item["features"] = features
            stage_objects.append(item)

        start_points = [{"x": e(a[0]), "z": e(a[1])} for a in raw.get("start_points_cpp", [])]

        gates = []
        for args in raw.get("gates_cpp", []):
            target = target_code(args[0], evaluator, code)
            gates.append({
                "target": id_by_code.get(target, f"map.legacy_{target}"),
                "legacy_target_code": target,
                "x": e(args[1]), "z": e(args[2]), "y": e(args[3]),
            })

        warp_gates: list[dict[str, Any]] = []
        orphan: list[dict[str, Any]] = []
        active: dict[str, Any] | None = None
        for operation in raw.get("warp_operations_cpp", []):
            kind = operation["kind"]
            if kind == "in":
                a = operation["args"]
                active = {
                    "x": e(a[0]), "z": e(a[1]), "y": e(a[2]),
                    "size": e(a[3]), "height": e(a[4]),
                    "limit_level": 0, "special_effect": 0, "out_gates": [],
                }
                warp_gates.append(active)
            elif kind == "out":
                if active is None:
                    raise ValueError(f"field {code}: warp out without active warp gate")
                a = operation["args"]
                target = target_code(a[0], evaluator, code)
                active["out_gates"].append({
                    "target": id_by_code.get(target, f"map.legacy_{target}"),
                    "legacy_target_code": target,
                    "x": e(a[1]), "z": e(a[2]), "y": e(a[3]),
                })
            elif kind == "modifier":
                prop = operation["property"]
                value = e(operation["value_cpp"])
                if active is None:
                    orphan.append({"property": prop, "legacy_value": value})
                elif prop == "LimitLevel":
                    active["limit_level"] = value
                elif prop == "SpecialEffect":
                    active["special_effect"] = value
                else:
                    raise ValueError(f"field {code}: unsupported warp property {prop}")
            else:
                raise ValueError(f"field {code}: unsupported warp operation {kind}")

        ambient = []
        for a in raw.get("ambient_cpp", []):
            ambient.append({"x": e(a[0]), "y": e(a[1]), "z": e(a[2]), "round": e(a[3]), "sound_code": e(a[4])})

        center = raw.get("center_cpp") or ["0", "0"]
        map_image = raw.get("short_name")
        if isinstance(map_image, dict):
            raise ValueError(f"field {code}: non-literal map image id")
        stage = raw.get("stage")
        if not isinstance(stage, str):
            raise ValueError(f"field {code}: non-literal stage path")

        map_doc = {
            "schema": "summit.map/v1",
            "id": raw["id"],
            "legacy_field_code": code,
            "stage": stage,
            "map_image_id": map_image,
            "environment": {
                "state": symbolic_value(props.get("State"), evaluator, "state"),
                "sky": [symbolic_value(back[i], evaluator, "sky") for i in range(3)],
                "music": symbolic_value(props.get("BackMusicCode"), evaluator, "music"),
                "event": symbolic_value(props.get("FieldEvent"), evaluator, "event"),
            },
            "server": {"routing": symbolic_value(props.get("ServerCode"), evaluator, "server")},
            "limit_level": e(props.get("LimitLevel", "0")),
            "field_sight": e(props.get("FieldSight", "0")),
            "center": {"x": e(center[0]), "z": e(center[1])},
            "start_points": start_points,
            "stage_objects": stage_objects,
            "gates": gates,
            "warp_gates": warp_gates,
            "ambient": ambient,
            "legacy_orphan_warp_properties": orphan,
            "provenance": {"profile": profile, "source": provenance_source, "source_line": raw.get("source_line")},
        }
        maps.append(map_doc)

    return {
        "schema": "summit.map-catalog/v1",
        "profile": profile,
        "map_count": len(maps),
        "maps": maps,
        "legacy_dynamic_field": {"strategy": "append_after_static"},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert legacy map initialization into summit.map-catalog/v1")
    ap.add_argument("source", type=Path)
    ap.add_argument("--profile", choices=("client", "server"), required=True)
    ap.add_argument("--source-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    shadow = extract_legacy_maps(args.source)
    doc = semanticize(shadow, args.profile, args.source_root, args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{args.profile}: maps={doc['map_count']} -> {args.output}")


if __name__ == "__main__":
    main()
