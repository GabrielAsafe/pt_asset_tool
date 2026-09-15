#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import secrets
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pt_part_editor as editor
import pt_effect_preview as effect_preview

FORMAT = "PT_PARTICLE_EDITOR_UI_STAGING_V3"
MAX_BODY = 64 * 1024

def safe_asset_path(client_root: Path, asset: str) -> tuple[Path, Path]:
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError("asset is required")
    root = client_root.resolve()
    p = (root / asset).resolve()
    try:
        rel = p.relative_to(root)
    except ValueError:
        raise ValueError("asset escapes client root")
    if p.suffix.lower() != ".part":
        raise ValueError("only .part assets are allowed")
    if not p.is_file():
        raise FileNotFoundError(rel.as_posix())
    return p, rel

def safe_preview_image(app_root: Path, raw_path: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("preview image path is required")
    root=(app_root.resolve()/"pt_build"/"devtest"/"effect_preview"/"blender").resolve()
    p=Path(raw_path).expanduser().resolve()
    try: p.relative_to(root)
    except ValueError: raise ValueError("preview image escapes effect preview root")
    if p.suffix.lower() != ".png": raise ValueError("preview image must be PNG")
    if not p.is_file(): raise FileNotFoundError(str(p))
    return p

def asset_index(client_root: Path, query: str = ""):
    root = client_root.resolve()
    q = (query or "").casefold().strip()
    rows = []
    for p in editor.iter_part_files(root):
        rel = p.relative_to(root).as_posix()
        if q and q not in rel.casefold():
            continue
        rows.append({"asset": rel, "size": p.stat().st_size})
    return rows

def inspect_asset(client_root: Path, build_root: Path, asset: str):
    p, rel = safe_asset_path(client_root, asset)
    data = p.read_bytes()
    meta = editor.inspect_bytes(data)
    draft = editor.show_draft(client_root, rel.as_posix(), build_root)
    return {
        "format": FORMAT,
        "asset": rel.as_posix(),
        "size": len(data),
        "source_sha256": editor.sha256(data),
        "parse_status": meta["parse_status"],
        "authoring_status": meta["authoring_status"],
        "eol": meta["eol"],
        "brace_open_count": meta["brace_open_count"],
        "brace_close_count": meta["brace_close_count"],
        "occurrences": meta["occurrences"],
        "draft": draft,
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
    }

def apply_stage_edit(client_root: Path, build_root: Path, payload: dict):
    asset = payload.get("asset")
    selector = payload.get("selector")
    value = payload.get("value")
    fresh = bool(payload.get("fresh", False))
    if not isinstance(selector, str) or not selector:
        raise ValueError("selector is required")
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    _, rel = safe_asset_path(client_root, asset)
    expr = f"{selector}={value}"
    return editor.stage_edit(client_root, rel.as_posix(), build_root, [expr], fresh=fresh)

def verify_asset_draft(client_root: Path, build_root: Path, asset: str):
    _, rel = safe_asset_path(client_root, asset)
    return editor.verify_draft(client_root, rel.as_posix(), build_root)

def build_effect_preview(client_root: Path, build_root: Path, app_root: Path, asset: str):
    _, rel = safe_asset_path(client_root, asset)
    plan = effect_preview.build_preview_plan(client_root, build_root, rel.as_posix(), prefer_staged=True, write=True)
    cmd = effect_preview.blender_command(app_root, Path(plan["plan_path"]))
    return {
        "status": "PASS",
        "asset": rel.as_posix(),
        "event_count": plan["event_count"],
        "missing_texture_reference_count": plan["missing_texture_reference_count"],
        "complexity": plan["complexity"],
        "source_base_kind": plan["source"]["base_kind"],
        "preview_certification": plan["preview_certification"],
        "plan_path": plan["plan_path"],
        "blender_command": cmd,
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
    }

def run_effect_preview(client_root: Path, build_root: Path, app_root: Path, asset: str, lock: threading.Lock):
    _, rel = safe_asset_path(client_root, asset)
    if not lock.acquire(blocking=False):
        raise RuntimeError("another Blender particle preview is already running")
    try:
        plan = effect_preview.build_preview_plan(client_root, build_root, rel.as_posix(), prefer_staged=True, write=True)
        run = effect_preview.run_blender_preview(app_root, Path(plan["plan_path"]), timeout_seconds=120.0)
        run["asset"] = rel.as_posix()
        run["preview_certification"] = plan["preview_certification"]
        run["plan_path"] = plan["plan_path"]
        return run
    finally:
        lock.release()

HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'">
<title>PT Asset Tool - Particle Editor</title>
<style>
*{box-sizing:border-box}body{margin:0;font:14px/1.45 system-ui,sans-serif;background:#111;color:#eee}
header{padding:14px 18px;border-bottom:1px solid #333;display:flex;gap:12px;align-items:center}
header b{font-size:16px}.muted{color:#aaa}.ok{color:#9fd39f}.bad{color:#f0a0a0}
main{display:grid;grid-template-columns:360px 1fr;height:calc(100vh - 56px)}
aside{border-right:1px solid #333;overflow:auto;padding:12px}
section{overflow:auto;padding:16px}
input,button{font:inherit;background:#1c1c1c;color:#eee;border:1px solid #444;border-radius:5px;padding:7px}
button{cursor:pointer}button:disabled{opacity:.45;cursor:not-allowed}
#search{width:100%;margin-bottom:10px}
.asset{padding:7px;border-bottom:1px solid #292929;cursor:pointer;word-break:break-all}.asset:hover{background:#1b1b1b}
.card{border:1px solid #333;border-radius:7px;padding:12px;margin-bottom:14px;background:#161616}
table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:7px;border-bottom:1px solid #2d2d2d}
code{word-break:break-word}.row-edit{display:flex;gap:6px;align-items:center}.row-edit input{min-width:260px;flex:1}
small{color:#aaa}.pill{display:inline-block;border:1px solid #444;border-radius:999px;padding:2px 7px;margin-right:5px}
pre{white-space:pre-wrap;word-break:break-word;background:#0d0d0d;border:1px solid #333;padding:10px;border-radius:5px}
</style>
</head>
<body>
<header>
<b>PT Asset Tool - Particle Editor</b>
<span class="pill">staging only</span>
<span class="muted">client/server writes disabled</span>
</header>
<main>
<aside>
<input id="search" placeholder="Search .part assets">
<div id="assets"></div>
</aside>
<section>
<div id="empty" class="muted">Select a .part asset.</div>
<div id="view" hidden>
<div class="card">
<h3 id="title"></h3>
<div id="meta"></div>
</div>
<div class="card">
<h3>Fields</h3>
<table>
<thead><tr><th>Line</th><th>Selector</th><th>Kind</th><th>Value / Edit</th></tr></thead>
<tbody id="fields"></tbody>
</table>
</div>
<div class="card">
<h3>Draft</h3>
<div id="draft"></div>
<button id="verify">Verify draft</button> <button id="preview">Build Preview Plan</button> <button id="previewRun">Generate Blender .blend</button>
<pre id="verifyOut"></pre>
<pre id="previewOut"></pre>
<img id="previewImage" alt="Effect preview" hidden style="max-width:512px;width:100%;border:1px solid #333;border-radius:6px;background:#080808">
</div>
</div>
</section>
</main>
<script>
const CSRF = "__CSRF__";
let currentAsset = null;
const esc = s => String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
async function api(path, opts={}) {
  const headers = Object.assign({"Accept":"application/json"}, opts.headers||{});
  if (opts.method === "POST") {
    headers["Content-Type"]="application/json";
    headers["X-PT-CSRF"]=CSRF;
  }
  const r = await fetch(path, Object.assign({},opts,{headers}));
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
async function loadAssets(){
  const q=document.getElementById("search").value;
  const rows=await api("/api/assets?q="+encodeURIComponent(q));
  const el=document.getElementById("assets");
  el.innerHTML=rows.map(r=>`<div class="asset" data-a="${esc(r.asset)}">${esc(r.asset)} <small>${r.size} B</small></div>`).join("");
  el.querySelectorAll(".asset").forEach(x=>x.onclick=()=>loadAsset(x.dataset.a));
}
async function loadAsset(asset){
  currentAsset=asset;
  const d=await api("/api/inspect?asset="+encodeURIComponent(asset));
  document.getElementById("empty").hidden=true;
  document.getElementById("view").hidden=false;
  document.getElementById("title").textContent=d.asset;
  const cls=d.authoring_status==="EDITABLE_STAGING"?"ok":"bad";
  document.getElementById("meta").innerHTML=
    `<span class="${cls}">${esc(d.authoring_status)}</span> · ${esc(d.parse_status)} · EOL ${esc(d.eol)} · source ${esc(d.source_sha256.slice(0,16))}…`;
  const tbody=document.getElementById("fields");
  tbody.innerHTML=d.occurrences.map(o=>{
    const sel=`${o.canonical_key}[${o.occurrence}]`;
    if(o.editable && d.authoring_status==="EDITABLE_STAGING"){
      return `<tr><td>${o.line}</td><td><code>${esc(sel)}</code></td><td>${esc(o.value_kind)}</td>
      <td><div class="row-edit"><input data-sel="${esc(sel)}" value="${esc(o.value)}"><button data-edit="${esc(sel)}">Stage</button></div></td></tr>`;
    }
    return `<tr><td>${o.line}</td><td><code>${esc(sel)}</code></td><td>${esc(o.value_kind)}</td><td><code>${esc(o.value)}</code> <small>view-only</small></td></tr>`;
  }).join("");
  tbody.querySelectorAll("button[data-edit]").forEach(btn=>{
    btn.onclick=async()=>{
      const sel=btn.dataset.edit;
      const inputs=[...tbody.querySelectorAll("input[data-sel]")];
      const inp=inputs.find(x=>x.dataset.sel===sel);
      btn.disabled=true;
      try{
        const res=await api("/api/stage-edit",{method:"POST",body:JSON.stringify({asset:currentAsset,selector:sel,value:inp.value})});
        alert(`Staged revision ${res.revision}`);
        await loadAsset(currentAsset);
      }catch(e){alert(e.message)}finally{btn.disabled=false}
    };
  });
  renderDraft(d.draft);
}
function renderDraft(d){
  const el=document.getElementById("draft");
  if(!d.has_state){el.innerHTML='<span class="muted">No draft yet.</span>';return}
  const st=d.state;
  el.innerHTML=`revision <b>${st.revision}</b> · candidate <code>${esc(st.candidate_sha256.slice(0,16))}…</code>`;
}
document.getElementById("verify").onclick=async()=>{
  if(!currentAsset)return;
  const out=document.getElementById("verifyOut");
  try{out.textContent=JSON.stringify(await api("/api/draft-verify?asset="+encodeURIComponent(currentAsset)),null,2)}
  catch(e){out.textContent=e.message}
};
document.getElementById("preview").onclick=async()=>{
  if(!currentAsset)return;
  const out=document.getElementById("previewOut");
  out.textContent="Building semantic preview plan...";
  try{
    const r=await api("/api/preview-plan",{method:"POST",body:JSON.stringify({asset:currentAsset})});
    out.textContent=`${r.preview_certification}\nBase: ${r.source_base_kind}\nEvents: ${r.event_count}\nRequested particles: ${r.complexity.requested_particle_objects}\nMissing textures: ${r.missing_texture_reference_count}\nPlan: ${r.plan_path}\n\nManual command:\n${r.blender_command.shell}`;
  }catch(e){out.textContent=e.message}
};
document.getElementById("previewRun").onclick=async()=>{
  if(!currentAsset)return;
  const btn=document.getElementById("previewRun");
  const out=document.getElementById("previewOut");
  btn.disabled=true; out.textContent="Generating bounded Blender preview...";
  try{
    const r=await api("/api/preview-run",{method:"POST",body:JSON.stringify({asset:currentAsset})});
    const rep=r.report||{};
    const renders=r.render_files||rep.render_files||[];
    out.textContent=`${r.status} · ${r.preview_certification}\nPlan: ${r.plan_path}\nBlend: ${rep.blend||"not generated"}\nSprites: ${rep.created_sprite_objects??"?"}\nRenders: ${renders.length}\nWarnings: ${(rep.warnings||[]).length}\n\n${r.stdout_tail||""}`;
    const img=document.getElementById("previewImage");
    if(renders.length){img.src="/api/preview-image?path="+encodeURIComponent(renders[Math.min(1,renders.length-1)]);img.hidden=false}else{img.hidden=true;img.removeAttribute("src")}
  }catch(e){out.textContent=e.message}finally{btn.disabled=false}
};
let timer=null;
document.getElementById("search").oninput=()=>{clearTimeout(timer);timer=setTimeout(loadAssets,150)};
loadAssets();
</script>
</body>
</html>'''

class App:
    def __init__(self, client_root: Path, build_root: Path):
        self.client_root = client_root.resolve()
        self.build_root = build_root.resolve()
        self.app_root = Path(__file__).resolve().parent
        self.csrf = secrets.token_urlsafe(24)
        self.preview_lock = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    server_version = "PTParticleUI/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[particle-ui] " + (fmt % args) + "\n")

    @property
    def app(self) -> App:
        return self.server.app

    def send_json(self, obj, status=200):
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def send_html(self, text):
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def send_binary(self, data: bytes, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def fail(self, exc):
        code = 404 if isinstance(exc, FileNotFoundError) else 400
        self.send_json({"status":"ERROR","error":f"{type(exc).__name__}: {exc}"}, code)

    def do_GET(self):
        try:
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            if u.path == "/":
                self.send_html(HTML.replace("__CSRF__", html.escape(self.app.csrf)))
                return
            if u.path == "/api/assets":
                q = qs.get("q", [""])[0]
                self.send_json(asset_index(self.app.client_root, q))
                return
            if u.path == "/api/inspect":
                asset = qs.get("asset", [""])[0]
                self.send_json(inspect_asset(self.app.client_root, self.app.build_root, asset))
                return
            if u.path == "/api/draft-verify":
                asset = qs.get("asset", [""])[0]
                self.send_json(verify_asset_draft(self.app.client_root, self.app.build_root, asset))
                return
            if u.path == "/api/preview-image":
                raw = qs.get("path", [""])[0]
                image = safe_preview_image(self.app.app_root, raw)
                self.send_binary(image.read_bytes(), "image/png")
                return
            self.send_json({"error":"not found"},404)
        except Exception as exc:
            self.fail(exc)

    def do_POST(self):
        try:
            if self.headers.get("X-PT-CSRF") != self.app.csrf:
                self.send_json({"error":"CSRF token mismatch"},403)
                return
            length = int(self.headers.get("Content-Length","0") or 0)
            if length <= 0 or length > MAX_BODY:
                self.send_json({"error":"invalid request size"},413)
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            u = urllib.parse.urlparse(self.path)
            if u.path == "/api/stage-edit":
                self.send_json(apply_stage_edit(self.app.client_root, self.app.build_root, payload))
                return
            if u.path == "/api/preview-plan":
                self.send_json(build_effect_preview(self.app.client_root, self.app.build_root, self.app.app_root, payload.get("asset", "")))
                return
            if u.path == "/api/preview-run":
                self.send_json(run_effect_preview(self.app.client_root, self.app.build_root, self.app.app_root, payload.get("asset", ""), self.app.preview_lock))
                return
            self.send_json({"error":"not found"},404)
        except Exception as exc:
            self.fail(exc)

def serve(client_root: Path, build_root: Path, port: int):
    app = App(client_root, build_root)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = app
    print(json.dumps({
        "format": FORMAT,
        "status": "READY",
        "url": f"http://127.0.0.1:{port}/",
        "client_root": str(app.client_root),
        "build_root": str(app.build_root),
        "bind": "127.0.0.1",
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
    }, indent=2, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

def main():
    ap = argparse.ArgumentParser(description="PT Asset Tool Particle Editor staging UI")
    ap.add_argument("--client-root", required=True)
    ap.add_argument("--build-root", default="pt_build/devtest")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    if not (1 <= args.port <= 65535):
        raise SystemExit("invalid port")
    serve(Path(args.client_root).expanduser(), Path(args.build_root).expanduser(), args.port)

if __name__ == "__main__":
    main()
