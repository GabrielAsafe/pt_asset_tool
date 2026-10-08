#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "docs" / "en" / "engineering" / "SOURCE_API_REFERENCE.md"


@dataclass(frozen=True)
class Symbol:
    kind: str
    qualified_name: str
    signature: str
    lineno: int
    summary: str
    decorators: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModuleInventory:
    path: Path
    module_summary: str
    symbols: tuple[Symbol, ...]


def documented_python_files(root: Path = ROOT) -> list[Path]:
    """Return every maintained first-party Python implementation file covered here."""
    files: list[Path] = []
    ready = root / "READY_TO_DEPLOY.py"
    if ready.is_file():
        files.append(ready)
    app = root / "app"
    files.extend(p for p in sorted(app.glob("*.py")) if p.name != "conftest.py")
    pkg = app / "pt_asset_tool"
    files.extend(sorted(pkg.rglob("*.py")))
    validation = root / "docs" / "validation"
    files.extend(sorted(validation.glob("*.py")))
    return files


# Backward-compatible name used by older validation callers.
def runtime_python_files(root: Path = ROOT) -> list[Path]:
    return documented_python_files(root)


def _summary(node: ast.AST) -> str:
    text = ast.get_docstring(node, clean=True) or ""
    if not text:
        return "—"
    return " ".join(text.strip().splitlines()[0].split())


def _expr(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


def _arg(a: ast.arg, default: ast.AST | None = None) -> str:
    text = a.arg
    if a.annotation is not None:
        text += f": {_expr(a.annotation)}"
    if default is not None:
        text += f" = {_expr(default)}"
    return text


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = node.args
    pieces: list[str] = []
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    posonly_count = len(args.posonlyargs)
    for i, (arg, default) in enumerate(zip(positional, defaults)):
        pieces.append(_arg(arg, default))
        if posonly_count and i + 1 == posonly_count:
            pieces.append("/")
    if args.vararg is not None:
        pieces.append("*" + _arg(args.vararg))
    elif args.kwonlyargs:
        pieces.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        pieces.append(_arg(arg, default))
    if args.kwarg is not None:
        pieces.append("**" + _arg(args.kwarg))
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    sig = f"{prefix}{node.name}({', '.join(pieces)})"
    if node.returns is not None:
        sig += f" -> {_expr(node.returns)}"
    return sig


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> tuple[str, ...]:
    return tuple(_expr(x) for x in node.decorator_list)


def _class_signature(node: ast.ClassDef) -> str:
    bases = [_expr(x) for x in node.bases]
    bases.extend(f"{kw.arg}={_expr(kw.value)}" for kw in node.keywords)
    return f"class {node.name}" + (f"({', '.join(bases)})" if bases else "")


def _class_symbols(node: ast.ClassDef, prefix: str = "") -> list[Symbol]:
    qname = f"{prefix}.{node.name}" if prefix else node.name
    out = [Symbol("class", qname, _class_signature(node), node.lineno, _summary(node), _decorators(node))]
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(Symbol("method", f"{qname}.{child.name}", _signature(child), child.lineno, _summary(child), _decorators(child)))
        elif isinstance(child, ast.ClassDef):
            out.extend(_class_symbols(child, qname))
    return out


def inventory_module(path: Path) -> ModuleInventory:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbols: list[Symbol] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(Symbol("function", node.name, _signature(node), node.lineno, _summary(node), _decorators(node)))
        elif isinstance(node, ast.ClassDef):
            symbols.extend(_class_symbols(node))
    return ModuleInventory(path=path, module_summary=_summary(tree), symbols=tuple(symbols))


def inventory(root: Path = ROOT) -> list[ModuleInventory]:
    return [inventory_module(path) for path in documented_python_files(root)]


def source_digest(root: Path = ROOT) -> str:
    h = hashlib.sha256()
    for path in documented_python_files(root):
        rel = path.relative_to(root).as_posix().encode("utf-8")
        raw = path.read_bytes()
        h.update(len(rel).to_bytes(4, "big")); h.update(rel)
        h.update(len(raw).to_bytes(8, "big")); h.update(raw)
    return h.hexdigest()


def render_reference(root: Path = ROOT) -> str:
    modules = inventory(root)
    class_count = sum(1 for m in modules for s in m.symbols if s.kind == "class")
    method_count = sum(1 for m in modules for s in m.symbols if s.kind == "method")
    function_count = sum(1 for m in modules for s in m.symbols if s.kind == "function")
    lines = [
        "# Source API Reference",
        "",
        "<!-- GENERATED BY docs/validation/generate_source_api_reference.py; DO NOT EDIT BY HAND -->",
        "",
        "This is the exhaustive maintained first-party Python implementation symbol inventory for the current checkout. It is generated from the AST, so modules, classes, methods, signatures, decorators, source lines, and available docstring summaries stay synchronized with the implementation.",
        "",
        "Scope: `READY_TO_DEPLOY.py`, top-level runtime scripts in `app/*.py` (excluding `conftest.py`), every `app/pt_asset_tool/**/*.py` module, and the maintained documentation validators/generator in `docs/validation/*.py`. Test functions are validated by pytest but are intentionally not treated as implementation API. Historical merge-preview trees are evidence only. `vendor/` is upstream/external code with its own versioned documentation boundary and is not re-documented as first-party API here.",
        "",
        f"- Source SHA-256: `{source_digest(root)}`",
        f"- Maintained Python modules/scripts: **{len(modules)}**",
        f"- Classes: **{class_count}**",
        f"- Class methods: **{method_count}**",
        f"- Module-level functions: **{function_count}**",
        "",
        "A summary of `—` means the symbol has no Python docstring; the signature and source location remain documented here. This reference documents private helpers too because they are part of the maintained source surface, not only public API.",
        "",
    ]
    for mod in modules:
        rel = mod.path.relative_to(root).as_posix()
        lines.extend([f"## `{rel}`", "", mod.module_summary, ""])
        if not mod.symbols:
            lines.extend(["_No top-level functions or classes._", ""])
            continue
        lines.extend(["| Kind | Symbol | Signature | Line | Summary |", "|---|---|---|---:|---|"])
        for sym in mod.symbols:
            decorators = " ".join(f"@{d}" for d in sym.decorators)
            decorated = (decorators + " " if decorators else "") + sym.signature
            def esc(s: str) -> str:
                return s.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {sym.kind} | `{esc(sym.qualified_name)}` | `{esc(decorated)}` | {sym.lineno} | {esc(sym.summary)} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
