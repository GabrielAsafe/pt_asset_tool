#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

FORMAT = "PT_PARTICLE_PART_TRANSACTIONAL_EDITOR_V1"

TEXTURE_EXTS = {".tga", ".bmp", ".png"}

LINE_RE = re.compile(
    r'^(?P<prefix>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)(?P<sep>\s*(?:=|:)\s*|\s+)'
    r'(?P<value>.*?)(?P<suffix>\s*)$'
)

NUMBER_RE = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')
INT_RE = re.compile(r'^[+-]?\d+$')
RANDOM_RE = re.compile(r'(?is)^random\s*\((.*)\)$')
XYZ_RE = re.compile(r'(?is)^xyz\s*\((.*)\)$')
RGBA_RE = re.compile(r'(?is)^rgba\s*\((.*)\)$')
INITIAL_RE = re.compile(r'(?is)^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$')
FADE_RE = re.compile(r'(?is)^so\s+final\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$')

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def split_lines_keepends(data: bytes):
    if b"\x00" in data:
        raise ValueError("BINARY_NUL")
    return data.decode("ascii").splitlines(keepends=True)

def line_body_eol(line: str):
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""

def split_top_level_csv(s: str):
    out, cur = [], []
    depth = 0
    quote = None
    esc = False
    for ch in s:
        if quote:
            cur.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
            continue
        if ch in {'"', "'"}:
            quote = ch
            cur.append(ch)
            continue
        if ch == "(":
            depth += 1
            cur.append(ch)
            continue
        if ch == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced expression parentheses")
            cur.append(ch)
            continue
        if ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if depth != 0 or quote:
        raise ValueError("unbalanced expression")
    out.append("".join(cur).strip())
    return out

def number_kind(v: str):
    v = v.strip()
    if INT_RE.fullmatch(v):
        return "INT"
    if NUMBER_RE.fullmatch(v):
        return "FLOAT"
    return None

def parse_random(v: str):
    m = RANDOM_RE.fullmatch(v.strip())
    if not m:
        return None
    try:
        parts = split_top_level_csv(m.group(1))
    except ValueError:
        return None
    if len(parts) != 2 or not all(number_kind(p) for p in parts):
        return None
    return {"kind": "RANDOM2", "values": parts}

def parse_xyz(v: str):
    m = XYZ_RE.fullmatch(v.strip())
    if not m:
        return None
    try:
        parts = split_top_level_csv(m.group(1))
    except ValueError:
        return None
    if len(parts) != 3:
        return None
    kinds = []
    for p in parts:
        nk = number_kind(p)
        if nk:
            kinds.append(nk)
            continue
        rr = parse_random(p)
        if rr:
            kinds.append("RANDOM2")
            continue
        return None
    return {"kind": "XYZ3", "components": parts, "component_kinds": kinds}

def parse_rgba(v: str):
    m = RGBA_RE.fullmatch(v.strip())
    if not m:
        return None
    try:
        parts = split_top_level_csv(m.group(1))
    except ValueError:
        return None
    if len(parts) != 4 or not all(INT_RE.fullmatch(p.strip()) for p in parts):
        return None
    vals = [int(p.strip()) for p in parts]
    if not all(0 <= x <= 255 for x in vals):
        return None
    return {"kind": "RGBA", "values": vals}

def parse_initial(v: str):
    m = INITIAL_RE.fullmatch(v.strip())
    if not m:
        return None
    field = m.group(1)
    expr = m.group(2).strip()
    cf = field.casefold()
    ek = semantic_expr_kind(expr)
    allowed = {
        "color": {"RGBA"},
        "size": {"INT", "FLOAT", "RANDOM2"},
        "velocity": {"XYZ3"},
        "partanglez": {"INT", "FLOAT", "RANDOM2"},
    }
    if cf not in allowed or ek not in allowed[cf]:
        return None
    return {"kind": "INITIAL_ASSIGN", "field": field, "canonical_field": cf, "expr_kind": ek}

def parse_fade(v: str):
    m = FADE_RE.fullmatch(v.strip())
    if not m:
        return None
    field = m.group(1)
    expr = m.group(2).strip()
    cf = field.casefold()
    ek = semantic_expr_kind(expr)
    allowed = {
        "color": {"RGBA"},
        "size": {"INT", "FLOAT", "RANDOM2"},
    }
    if cf not in allowed or ek not in allowed[cf]:
        return None
    return {"kind": "FADE_ASSIGN", "field": field, "canonical_field": cf, "expr_kind": ek}

def semantic_expr_kind(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in {'"', "'"}:
        return "STRING"
    nk = number_kind(v)
    if nk:
        return nk
    if parse_random(v):
        return "RANDOM2"
    if parse_xyz(v):
        return "XYZ3"
    if parse_rgba(v):
        return "RGBA"
    return "TOKEN"

def malformed_expression_reason(raw: str):
    v = raw.strip()
    lowered = v.casefold()
    candidates = ("random(", "xyz(", "rgba(")
    if not any(x in lowered for x in candidates):
        return None

    depth = 0
    quote = None
    esc = False
    for ch in v:
        if quote:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
            continue
        if ch in {'"', "'"}:
            quote = ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return "PAREN_CLOSE_WITHOUT_OPEN"
    if depth != 0:
        return "UNBALANCED_PARENTHESES"
    if quote:
        return "UNBALANCED_QUOTE"
    return None

def classify_value(key: str, raw: str):
    key = key.casefold()
    v = raw.strip()
    if key == "initial":
        p = parse_initial(v)
        if p:
            return p["kind"]
    if key == "fade":
        p = parse_fade(v)
        if p:
            return p["kind"]
    return semantic_expr_kind(v)

def brace_status(lines):
    op = cl = 0
    for line in lines:
        body, _ = line_body_eol(line)
        code = []
        quote = None
        esc = False
        i = 0
        while i < len(body):
            ch = body[i]
            if quote:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == quote:
                    quote = None
                i += 1
                continue
            if ch in {"'", '"'}:
                quote = ch
                i += 1
                continue
            if body.startswith("//", i) or ch in {"#", ";"}:
                break
            code.append(ch)
            i += 1
        c = "".join(code)
        op += c.count("{")
        cl += c.count("}")
    return op, cl

def eol_style(lines):
    kinds = set()
    for line in lines:
        _, e = line_body_eol(line)
        if e:
            kinds.add(e)
    if not kinds:
        return "NONE"
    if len(kinds) > 1:
        return "MIXED"
    return {"\r\n": "CRLF", "\n": "LF", "\r": "CR"}[next(iter(kinds))]

def is_editable(key: str, kind: str):
    k = key.casefold()
    allowed = {
        "delay": {"INT", "FLOAT"},
        "lifetime": {"INT", "FLOAT", "RANDOM2"},
        "loops": {"INT", "FLOAT"},
        "emitrate": {"INT"},
        "numparticles": {"INT"},
        "texture": {"STRING"},
        "gravity": {"XYZ3"},
        "emitradius": {"XYZ3"},
        "position": {"XYZ3"},
        "initial": {"INITIAL_ASSIGN"},
        "fade": {"FADE_ASSIGN"},
    }
    return kind in allowed.get(k, set())

def inspect_bytes(data: bytes):
    lines = split_lines_keepends(data)
    op, cl = brace_status(lines)
    eol = eol_style(lines)
    counts = {}
    occs = []
    for no, line in enumerate(lines, 1):
        body, _ = line_body_eol(line)
        s = body.strip()
        if not s or s.startswith(("//", "#", ";", "{", "}")):
            continue
        m = LINE_RE.match(body)
        if not m:
            continue
        key = m.group("key")
        canonical = key.casefold()
        idx = counts.get(canonical, 0)
        counts[canonical] = idx + 1
        value = m.group("value")
        kind = classify_value(canonical, value)
        occs.append({
            "key": key,
            "canonical_key": canonical,
            "occurrence": idx,
            "line": no,
            "value": value,
            "value_kind": kind,
            "editable": is_editable(canonical, kind),
            "semantic_warning": malformed_expression_reason(value),
        })
    parse_status = "PASS_LEXICAL" if op == cl else "REVIEW_UNBALANCED_BRACES"
    authoring_status = "EDITABLE_STAGING" if parse_status == "PASS_LEXICAL" and eol == "CRLF" else "BLOCKED_ANOMALY"
    return {
        "parse_status": parse_status,
        "authoring_status": authoring_status,
        "eol": eol,
        "brace_open_count": op,
        "brace_close_count": cl,
        "occurrences": occs,
    }

def parse_selector(s: str):
    m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_.-]*)\[(\d+)\]=(.*)", s, re.S)
    if not m:
        raise ValueError("selector must be key[index]=value")
    return m.group(1).casefold(), int(m.group(2)), m.group(3)

def validate_new_value(key, old_raw, new_raw):
    old_kind = classify_value(key, old_raw)
    new_kind = classify_value(key, new_raw)
    if not is_editable(key, old_kind):
        raise ValueError(f"{key} occurrence is not authorable; old_kind={old_kind}")
    if not is_editable(key, new_kind):
        raise ValueError(f"{key}[...] new value is not in a proven semantic shape; got {new_kind}")

    if key == "texture":
        v = new_raw.strip()
        if len(v) < 2 or v[0] != v[-1] or v[0] not in {'"', "'"}:
            raise ValueError("texture must remain quoted")
        ext = Path(v[1:-1].replace("\\", "/")).suffix.lower()
        if ext not in TEXTURE_EXTS:
            raise ValueError(f"texture extension {ext!r} not in {sorted(TEXTURE_EXTS)}")

    if key == "initial":
        old = parse_initial(old_raw)
        new = parse_initial(new_raw)
        if not old or not new or old["canonical_field"] != new["canonical_field"]:
            raise ValueError("initial edit must preserve its semantic subfield")
    if key == "fade":
        old = parse_fade(old_raw)
        new = parse_fade(new_raw)
        if not old or not new or old["canonical_field"] != new["canonical_field"]:
            raise ValueError("fade edit must preserve its semantic subfield")

    if old_kind == "STRING" and new_kind != "STRING":
        raise ValueError("string occurrence cannot become non-string")
    if old_kind == "INT" and new_kind == "FLOAT" and key not in {"delay", "lifetime", "loops"}:
        raise ValueError("integer occurrence cannot become float for this key")
    return old_kind, new_kind

def available_selectors(data: bytes):
    return [
        f"{o['canonical_key']}[{o['occurrence']}]"
        for o in inspect_bytes(data)["occurrences"]
        if o.get("editable")
    ]

def edit_bytes(data: bytes, selectors):
    meta = inspect_bytes(data)
    if meta["authoring_status"] != "EDITABLE_STAGING":
        raise ValueError(f"authoring blocked: {meta['parse_status']} eol={meta['eol']}")
    wanted = {}
    for raw in selectors:
        k, idx, value = parse_selector(raw)
        if (k, idx) in wanted:
            raise ValueError(f"duplicate selector {k}[{idx}]")
        wanted[(k, idx)] = value

    lines = split_lines_keepends(data)
    counts = {}
    changes = []
    found = set()
    for i, line in enumerate(lines):
        body, ending = line_body_eol(line)
        s = body.strip()
        if not s or s.startswith(("//", "#", ";", "{", "}")):
            continue
        m = LINE_RE.match(body)
        if not m:
            continue
        canonical = m.group("key").casefold()
        idx = counts.get(canonical, 0)
        counts[canonical] = idx + 1
        sel = (canonical, idx)
        if sel not in wanted:
            continue
        old = m.group("value")
        new = wanted[sel]
        old_kind, new_kind = validate_new_value(canonical, old, new)
        new_body = m.group("prefix") + m.group("key") + m.group("sep") + new + m.group("suffix")
        lines[i] = new_body + ending
        found.add(sel)
        changes.append({
            "key": m.group("key"),
            "canonical_key": canonical,
            "occurrence": idx,
            "line": i + 1,
            "old_value": old,
            "new_value": new,
            "old_kind": old_kind,
            "new_kind": new_kind,
        })

    missing = sorted(set(wanted) - found)
    if missing:
        raise ValueError(
            f"selectors not found: {missing}; available editable selectors: {available_selectors(data)}"
        )

    out = "".join(lines).encode("ascii")
    after = inspect_bytes(out)
    if after["parse_status"] != "PASS_LEXICAL":
        raise ValueError("candidate parse status regressed")
    if after["eol"] != "CRLF":
        raise ValueError("candidate EOL changed")
    return out, changes

def byte_diff_summary(a: bytes, b: bytes):
    # Minimal contiguous edit accounting based on common prefix/suffix.
    # This avoids counting the entire tail as changed when an edit changes length.
    prefix = 0
    limit = min(len(a), len(b))
    while prefix < limit and a[prefix] == b[prefix]:
        prefix += 1

    suffix = 0
    max_suffix = min(len(a) - prefix, len(b) - prefix)
    while suffix < max_suffix and a[len(a)-1-suffix] == b[len(b)-1-suffix]:
        suffix += 1

    a_mid_end = len(a) - suffix if suffix else len(a)
    b_mid_end = len(b) - suffix if suffix else len(b)
    a_mid = a[prefix:a_mid_end]
    b_mid = b[prefix:b_mid_end]

    replaced = min(len(a_mid), len(b_mid))
    deleted = max(0, len(a_mid) - len(b_mid))
    inserted = max(0, len(b_mid) - len(a_mid))
    return {
        "prefix_equal_bytes": prefix,
        "suffix_equal_bytes": suffix,
        "source_changed_span_bytes": len(a_mid),
        "candidate_changed_span_bytes": len(b_mid),
        "replaced_bytes": replaced,
        "inserted_bytes": inserted,
        "deleted_bytes": deleted,
        "net_size_delta": len(b) - len(a),
    }

def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)

def state_path(build_root: Path, rel: Path):
    return build_root / "part_editor" / "state" / (rel.as_posix().replace("/", "__") + ".json")

def load_state(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

def stage_edit(client_root: Path, asset: str, build_root: Path, selectors, fresh=False):
    root = client_root.resolve()
    src = (root / asset).resolve()
    try:
        rel = src.relative_to(root)
    except ValueError:
        raise ValueError("asset escapes client root")
    if src.suffix.lower() != ".part":
        raise ValueError("only .part assets are accepted")

    source = src.read_bytes()
    source_sha = sha256(source)
    out = build_root / "part_editor" / "staged" / rel
    st_path = state_path(build_root, rel)
    st = None if fresh else load_state(st_path)

    if fresh:
        base = source
        revision = 1
        history = []
        base_kind = "SOURCE_RESET"
    elif st is None:
        if out.exists():
            raise ValueError("staged candidate exists without state; use --fresh to reset safely")
        base = source
        revision = 1
        history = []
        base_kind = "SOURCE"
    else:
        if st.get("source_sha256") != source_sha:
            raise ValueError("STALE_SOURCE: client source changed since staged draft began; use --fresh after review")
        if not out.exists():
            raise ValueError("staged state exists but candidate is missing; use --fresh")
        current = out.read_bytes()
        if sha256(current) != st.get("candidate_sha256"):
            raise ValueError("STAGED_TAMPER: staged candidate hash does not match state")
        base = current
        revision = int(st.get("revision", 0)) + 1
        history = list(st.get("history", []))
        base_kind = "STAGED_REVISION"

    base_sha = sha256(base)
    candidate, changes = edit_bytes(base, selectors)
    candidate_sha = sha256(candidate)
    atomic_write(out, candidate)

    rev_entry = {
        "revision": revision,
        "base_kind": base_kind,
        "base_sha256": base_sha,
        "candidate_sha256": candidate_sha,
        "changes": changes,
    }
    history.append(rev_entry)
    state = {
        "format": "PT_PARTICLE_PART_DRAFT_STATE_V1",
        "asset": rel.as_posix(),
        "source_sha256": source_sha,
        "candidate_sha256": candidate_sha,
        "revision": revision,
        "history": history,
        "production_authorized": False,
        "client_write_authorized": False,
    }
    atomic_write(st_path, (json.dumps(state, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))

    report = {
        "format": FORMAT,
        "status": "PASS",
        "asset": rel.as_posix(),
        "revision": revision,
        "base_kind": base_kind,
        "source_sha256": source_sha,
        "base_sha256": base_sha,
        "candidate_sha256": candidate_sha,
        "byte_diff_this_revision": byte_diff_summary(base, candidate),
        "byte_diff_vs_source": byte_diff_summary(source, candidate),
        "changes": changes,
        "staged_candidate": str(out),
        "draft_state": str(st_path),
        "source_unchanged": sha256(src.read_bytes()) == source_sha,
        "editing_surface": "PT_BUILD_ONLY",
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
    }
    report_path = (
        build_root / "part_editor" / "reports" /
        (rel.as_posix().replace("/", "__") + f".rev{revision:04d}.json")
    )
    atomic_write(report_path, (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    report["report"] = str(report_path)
    return report

def show_draft(client_root: Path, asset: str, build_root: Path):
    root = client_root.resolve()
    src = (root / asset).resolve()
    rel = src.relative_to(root)
    st = load_state(state_path(build_root, rel))
    out = build_root / "part_editor" / "staged" / rel
    return {
        "format": "PT_PARTICLE_PART_DRAFT_STATUS_V1",
        "asset": rel.as_posix(),
        "has_state": st is not None,
        "has_candidate": out.exists(),
        "state": st,
        "staged_candidate": str(out),
        "production_authorized": False,
        "client_write_authorized": False,
    }

def verify_draft(client_root: Path, asset: str, build_root: Path):
    root = client_root.resolve()
    src = (root / asset).resolve()
    rel = src.relative_to(root)
    st_path = state_path(build_root, rel)
    st = load_state(st_path)
    out = build_root / "part_editor" / "staged" / rel
    errors = []

    if st is None:
        errors.append("MISSING_STATE")
    if not out.exists():
        errors.append("MISSING_CANDIDATE")

    source = src.read_bytes()
    source_sha = sha256(source)
    candidate = out.read_bytes() if out.exists() else b""

    if st is not None:
        if st.get("source_sha256") != source_sha:
            errors.append("SOURCE_SHA_MISMATCH")
        if out.exists() and st.get("candidate_sha256") != sha256(candidate):
            errors.append("CANDIDATE_SHA_MISMATCH")

        history = st.get("history") or []
        expected = 1
        prev_candidate_sha = source_sha
        for row in history:
            if row.get("revision") != expected:
                errors.append(f"REVISION_SEQUENCE_{expected}")
                break
            if expected > 1 and row.get("base_sha256") != prev_candidate_sha:
                errors.append(f"REVISION_CHAIN_{expected}")
                break
            prev_candidate_sha = row.get("candidate_sha256")
            expected += 1
        if history and history[-1].get("candidate_sha256") != st.get("candidate_sha256"):
            errors.append("STATE_HISTORY_TIP_MISMATCH")

    candidate_meta = inspect_bytes(candidate) if candidate else None
    if candidate_meta and candidate_meta.get("parse_status") != "PASS_LEXICAL":
        errors.append("CANDIDATE_PARSE_NOT_PASS")
    if candidate_meta and candidate_meta.get("eol") != "CRLF":
        errors.append("CANDIDATE_EOL_NOT_CRLF")

    return {
        "format": "PT_PARTICLE_PART_DRAFT_VERIFY_V1",
        "status": "PASS" if not errors else "FAIL",
        "asset": rel.as_posix(),
        "errors": errors,
        "source_sha256": source_sha,
        "candidate_sha256": sha256(candidate) if candidate else None,
        "revision": st.get("revision") if st else None,
        "candidate_parse_status": candidate_meta.get("parse_status") if candidate_meta else None,
        "candidate_eol": candidate_meta.get("eol") if candidate_meta else None,
        "byte_diff_vs_source": byte_diff_summary(source, candidate) if candidate else None,
        "source_unchanged": sha256(src.read_bytes()) == source_sha,
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
    }


def iter_part_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort(key=str.casefold)
        for name in sorted(filenames, key=str.casefold):
            if name.lower().endswith(".part"):
                yield Path(dirpath) / name

def corpus_semantic_gate(client_root: Path, build_root: Path):
    root = client_root.resolve()
    rows = []
    authorable_assets = 0
    view_only_assets = 0
    editable_occurrences = 0
    semantic_noop_pass = 0
    semantic_noop_fail = 0
    kind_counts = {}
    key_counts = {}
    blocked_reason_counts = {}
    semantic_warning_counts = {}
    semantic_warning_samples = []
    failures = []

    for p in iter_part_files(root):
        rel = p.relative_to(root).as_posix()
        data = p.read_bytes()
        meta = inspect_bytes(data)
        occs = meta["occurrences"]
        editable = [o for o in occs if o.get("editable")]

        if meta["authoring_status"] == "EDITABLE_STAGING":
            authorable_assets += 1
        else:
            view_only_assets += 1
            reason = f"{meta['parse_status']}|{meta['eol']}"
            blocked_reason_counts[reason] = blocked_reason_counts.get(reason, 0) + 1

        per_asset_noop = 0
        per_asset_failures = []

        for o in occs:
            kind = o["value_kind"]
            key = o["canonical_key"]
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
            key_counts[key] = key_counts.get(key, 0) + 1
            warning = o.get("semantic_warning")
            if warning:
                semantic_warning_counts[warning] = semantic_warning_counts.get(warning, 0) + 1
                if len(semantic_warning_samples) < 100:
                    semantic_warning_samples.append({
                        "asset": rel,
                        "line": o["line"],
                        "key": o["key"],
                        "occurrence": o["occurrence"],
                        "value": o["value"],
                        "warning": warning,
                    })

        if meta["authoring_status"] == "EDITABLE_STAGING":
            for o in editable:
                editable_occurrences += 1
                selector = f"{o['canonical_key']}[{o['occurrence']}]={o['value']}"
                try:
                    out, changes = edit_bytes(data, [selector])
                    if out != data:
                        raise ValueError("semantic noop was not byte-identical")
                    if len(changes) != 1:
                        raise ValueError(f"semantic noop expected one resolved occurrence, got {len(changes)}")
                    semantic_noop_pass += 1
                    per_asset_noop += 1
                except Exception as exc:
                    semantic_noop_fail += 1
                    row = {
                        "asset": rel,
                        "selector": f"{o['canonical_key']}[{o['occurrence']}]",
                        "value": o["value"],
                        "value_kind": o["value_kind"],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    failures.append(row)
                    per_asset_failures.append(row)

        rows.append({
            "asset": rel,
            "size": len(data),
            "sha256": sha256(data),
            "parse_status": meta["parse_status"],
            "authoring_status": meta["authoring_status"],
            "eol": meta["eol"],
            "occurrence_count": len(occs),
            "editable_occurrence_count": len(editable),
            "semantic_noop_pass_count": per_asset_noop,
            "semantic_noop_failures": per_asset_failures,
        })

    status = "PASS" if semantic_noop_fail == 0 else "FAIL"
    report = {
        "format": "PT_PARTICLE_PART_CORPUS_SEMANTIC_GATE_V1",
        "status": status,
        "asset_count": len(rows),
        "authorable_asset_count": authorable_assets,
        "view_only_asset_count": view_only_assets,
        "editable_occurrence_count": editable_occurrences,
        "semantic_noop_pass_count": semantic_noop_pass,
        "semantic_noop_fail_count": semantic_noop_fail,
        "value_kind_counts": dict(sorted(kind_counts.items())),
        "key_occurrence_counts": dict(sorted(key_counts.items())),
        "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
        "semantic_warning_counts": dict(sorted(semantic_warning_counts.items())),
        "semantic_warning_samples": semantic_warning_samples,
        "failures": failures,
        "rows": rows,
        "client_modified": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
    }
    out = build_root / "part_semantic_gate" / "result.json"
    atomic_write(out, (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    report["report"] = str(out)
    return report

def summarize_corpus_gate(report: dict):
    return {
        "status": report["status"],
        "asset_count": report["asset_count"],
        "authorable_asset_count": report["authorable_asset_count"],
        "view_only_asset_count": report["view_only_asset_count"],
        "editable_occurrence_count": report["editable_occurrence_count"],
        "semantic_noop_pass_count": report["semantic_noop_pass_count"],
        "semantic_noop_fail_count": report["semantic_noop_fail_count"],
        "blocked_reason_counts": report["blocked_reason_counts"],
        "semantic_warning_counts": report["semantic_warning_counts"],
        "semantic_warning_sample_count": len(report["semantic_warning_samples"]),
        "report": report["report"],
        "production_authorized": False,
        "client_write_authorized": False,
    }


def mutate_number(raw: str):
    v = raw.strip()
    if INT_RE.fullmatch(v):
        n = int(v)
        return str(n + 1 if n != -1 else 0)
    if NUMBER_RE.fullmatch(v):
        try:
            x = float(v)
        except ValueError:
            return None
        return format(x + 0.125, ".12g")
    return None

def mutate_random(raw: str):
    p = parse_random(raw)
    if not p:
        return None
    a, b = p["values"]
    ak = number_kind(a)
    bk = number_kind(b)
    def bump(x, kind):
        if kind == "INT":
            return str(int(x) + 1)
        return format(float(x) + 0.125, ".12g")
    return f"Random({bump(a, ak)},{bump(b, bk)})"

def mutate_xyz(raw: str):
    p = parse_xyz(raw)
    if not p:
        return None
    comps = list(p["components"])
    for i, c in enumerate(comps):
        nk = number_kind(c)
        if nk:
            comps[i] = str(int(c) + 1) if nk == "INT" else format(float(c) + 0.125, ".12g")
            return f"XYZ({','.join(comps)})"
        rr = parse_random(c)
        if rr:
            comps[i] = mutate_random(c)
            return f"XYZ({','.join(comps)})"
    return None

def mutate_rgba(raw: str):
    p = parse_rgba(raw)
    if not p:
        return None
    vals = list(p["values"])
    vals[0] = vals[0] - 1 if vals[0] == 255 else vals[0] + 1
    return f"rgba({vals[0]},{vals[1]},{vals[2]},{vals[3]})"

def mutation_for_occurrence(o: dict):
    key = o["canonical_key"]
    raw = o["value"]
    kind = o["value_kind"]

    if key == "texture" and kind == "STRING":
        q = raw.strip()[0]
        body = raw.strip()[1:-1]
        p = Path(body.replace("\\", "/"))
        stem = p.stem + "_ptprobe"
        suffix = p.suffix
        parent = str(p.parent).replace("/", "\\")
        new_body = (parent + "\\" if parent not in ("", ".") else "") + stem + suffix
        return q + new_body + q

    if kind in {"INT", "FLOAT"}:
        return mutate_number(raw)
    if kind == "RANDOM2":
        return mutate_random(raw)
    if kind == "XYZ3":
        return mutate_xyz(raw)
    if kind == "INITIAL_ASSIGN":
        p = parse_initial(raw)
        if not p:
            return None
        field = p["field"]
        expr = INITIAL_RE.fullmatch(raw.strip()).group(2).strip()
        ek = p["expr_kind"]
        if ek == "RGBA":
            m = mutate_rgba(expr)
        elif ek == "RANDOM2":
            m = mutate_random(expr)
        elif ek == "XYZ3":
            m = mutate_xyz(expr)
        else:
            m = mutate_number(expr)
        return f"{field} = {m}" if m is not None else None
    if kind == "FADE_ASSIGN":
        p = parse_fade(raw)
        if not p:
            return None
        field = p["field"]
        expr = FADE_RE.fullmatch(raw.strip()).group(2).strip()
        ek = p["expr_kind"]
        if ek == "RGBA":
            m = mutate_rgba(expr)
        elif ek == "RANDOM2":
            m = mutate_random(expr)
        else:
            m = mutate_number(expr)
        return f"so final {field} = {m}" if m is not None else None
    return None

def semantic_mutation_gate(client_root: Path, build_root: Path):
    root = client_root.resolve()
    target_kinds = [
        "INT", "FLOAT", "RANDOM2", "XYZ3",
        "INITIAL_ASSIGN", "FADE_ASSIGN", "STRING",
    ]
    selected = {}
    scanned = 0

    for p in iter_part_files(root):
        data = p.read_bytes()
        meta = inspect_bytes(data)
        if meta["authoring_status"] != "EDITABLE_STAGING":
            continue
        scanned += 1
        rel = p.relative_to(root).as_posix()
        for o in meta["occurrences"]:
            if not o.get("editable"):
                continue
            kind = o["value_kind"]
            if kind in target_kinds and kind not in selected:
                mutation = mutation_for_occurrence(o)
                if mutation is not None and mutation != o["value"]:
                    selected[kind] = {
                        "asset": rel,
                        "occurrence": o,
                        "mutation": mutation,
                    }
        if len(selected) == len(target_kinds):
            break

    missing_kinds = [k for k in target_kinds if k not in selected]
    results = []
    failures = []

    gate_root = build_root / "part_semantic_mutation_gate"
    for kind in target_kinds:
        if kind not in selected:
            continue
        row = selected[kind]
        rel = row["asset"]
        occ = row["occurrence"]
        mutation = row["mutation"]
        src = root / rel
        source = src.read_bytes()
        selector = f"{occ['canonical_key']}[{occ['occurrence']}]={mutation}"

        try:
            candidate, changes = edit_bytes(source, [selector])
            if candidate == source:
                raise ValueError("mutation did not change candidate")
            if len(changes) != 1:
                raise ValueError(f"expected one resolved change, got {len(changes)}")
            after = inspect_bytes(candidate)
            if after["parse_status"] != "PASS_LEXICAL":
                raise ValueError(f"candidate parse status {after['parse_status']}")
            if after["eol"] != "CRLF":
                raise ValueError(f"candidate EOL {after['eol']}")
            if sha256(src.read_bytes()) != sha256(source):
                raise ValueError("source changed during mutation gate")

            # Verify target line before/after and that all non-target lines are byte-identical.
            source_lines = split_lines_keepends(source)
            candidate_lines = split_lines_keepends(candidate)
            if len(source_lines) != len(candidate_lines):
                raise ValueError("line count changed")
            target_line = changes[0]["line"] - 1
            non_target_diffs = [
                i + 1 for i, (a, b) in enumerate(zip(source_lines, candidate_lines))
                if i != target_line and a != b
            ]
            if non_target_diffs:
                raise ValueError(f"non-target lines changed: {non_target_diffs[:20]}")

            out = gate_root / "candidates" / kind / rel
            atomic_write(out, candidate)
            result = {
                "semantic_kind": kind,
                "asset": rel,
                "selector": f"{occ['canonical_key']}[{occ['occurrence']}]",
                "line": changes[0]["line"],
                "old_value": changes[0]["old_value"],
                "new_value": changes[0]["new_value"],
                "source_sha256": sha256(source),
                "candidate_sha256": sha256(candidate),
                "byte_diff": byte_diff_summary(source, candidate),
                "only_target_line_changed": True,
                "candidate_parse_status": after["parse_status"],
                "candidate_eol": after["eol"],
                "source_unchanged": True,
                "candidate": str(out),
                "status": "PASS",
            }
            results.append(result)
        except Exception as exc:
            fail = {
                "semantic_kind": kind,
                "asset": rel,
                "selector": f"{occ['canonical_key']}[{occ['occurrence']}]",
                "error": f"{type(exc).__name__}: {exc}",
                "status": "FAIL",
            }
            failures.append(fail)
            results.append(fail)

    status = "PASS" if not missing_kinds and not failures else "FAIL"
    report = {
        "format": "PT_PARTICLE_PART_SEMANTIC_MUTATION_GATE_V1",
        "status": status,
        "authorable_assets_scanned_for_representatives": scanned,
        "target_semantic_kinds": target_kinds,
        "selected_semantic_kinds": sorted(selected),
        "missing_semantic_kinds": missing_kinds,
        "pass_count": sum(r["status"] == "PASS" for r in results),
        "fail_count": len(failures),
        "results": results,
        "failures": failures,
        "client_modified": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
    }
    out = gate_root / "result.json"
    atomic_write(out, (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    report["report"] = str(out)
    return report

def summarize_mutation_gate(report: dict):
    return {
        "status": report["status"],
        "target_semantic_kinds": report["target_semantic_kinds"],
        "selected_semantic_kinds": report["selected_semantic_kinds"],
        "missing_semantic_kinds": report["missing_semantic_kinds"],
        "pass_count": report["pass_count"],
        "fail_count": report["fail_count"],
        "report": report["report"],
        "production_authorized": False,
        "client_write_authorized": False,
    }

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inspect-editable")
    p.add_argument("--client-root", required=True)
    p.add_argument("asset")

    p = sub.add_parser("stage-edit")
    p.add_argument("--client-root", required=True)
    p.add_argument("--build-root", default="pt_build/devtest")
    p.add_argument("--fresh", action="store_true")
    p.add_argument("asset")
    p.add_argument("--set", dest="sets", action="append", required=True)

    p = sub.add_parser("draft-status")
    p.add_argument("--client-root", required=True)
    p.add_argument("--build-root", default="pt_build/devtest")
    p.add_argument("asset")

    p = sub.add_parser("draft-verify")
    p.add_argument("--client-root", required=True)
    p.add_argument("--build-root", default="pt_build/devtest")
    p.add_argument("asset")

    p = sub.add_parser("corpus-semantic-gate")
    p.add_argument("--client-root", required=True)
    p.add_argument("--build-root", default="pt_build/devtest")

    p = sub.add_parser("semantic-mutation-gate")
    p.add_argument("--client-root", required=True)
    p.add_argument("--build-root", default="pt_build/devtest")

    args = ap.parse_args()
    root = Path(args.client_root).expanduser().resolve()

    if args.cmd == "inspect-editable":
        src = (root / args.asset).resolve()
        r = inspect_bytes(src.read_bytes())
        r.update({
            "format": FORMAT,
            "asset": src.relative_to(root).as_posix(),
            "editing_surface": "PT_BUILD_ONLY",
            "production_authorized": False,
            "client_write_authorized": False,
        })
    elif args.cmd == "draft-status":
        r = show_draft(root, args.asset, Path(args.build_root).resolve())
    elif args.cmd == "draft-verify":
        r = verify_draft(root, args.asset, Path(args.build_root).resolve())
    elif args.cmd == "corpus-semantic-gate":
        full = corpus_semantic_gate(root, Path(args.build_root).resolve())
        r = summarize_corpus_gate(full)
    elif args.cmd == "semantic-mutation-gate":
        full = semantic_mutation_gate(root, Path(args.build_root).resolve())
        r = summarize_mutation_gate(full)
    else:
        r = stage_edit(root, args.asset, Path(args.build_root).resolve(), args.sets, fresh=args.fresh)

    print(json.dumps(r, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
