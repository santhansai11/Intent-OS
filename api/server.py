"""IntentOS REST API server (Python standard library only).

Endpoints:
    GET  /api/health              liveness probe
    GET  /api/status              full kernel snapshot (intents, resources, services)
    GET  /api/metrics             scheduling metrics
    GET  /api/system              real system resources (psutil if installed)
    GET  /api/simulation          scheduler strategy comparison
    POST /api/intents             {"text": "..."} -> submit intent (auto-executes)
    POST /api/strategy            {"strategy": "deadline"} -> switch scheduler
    POST /api/faults              {"service": "messaging", "count": 1} -> fault injection
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from intent_kernel.kernel import IntentKernel
from intent_kernel.ipc.service_bus import ServiceError
from intent_kernel.scheduler import SCHEDULERS
from intent_kernel.simulation import compare_strategies

STEP_DELAY = 0.15  # paced execution so the UI can observe the lifecycle

# ---------------------------------------------------------------------------
# Built-in single-page UI served at "/" (no Node.js required).
# ---------------------------------------------------------------------------
_INDEX_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IntentOS</title>
<style>
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--fg:#e6edf3;--mut:#8b949e;
--acc:#58a6ff;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--run:#a371f7}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:14px/1.5 'Segoe UI',system-ui,sans-serif;padding:24px}
h1{font-size:22px;margin-bottom:2px}
.tagline{color:var(--mut);margin-bottom:16px;max-width:760px}
.grid{display:grid;grid-template-columns:1.6fr 1fr;gap:18px;align-items:start}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:18px}
.panel h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin-bottom:10px}
input[type=text]{width:100%;background:#0d1117;border:1px solid var(--line);border-radius:8px;
color:var(--fg);padding:10px 12px;font-size:15px}
button{cursor:pointer;border-radius:8px;border:1px solid var(--line);background:#21262d;color:var(--fg);padding:8px 14px;font-size:13px}
button.primary{background:#1f6feb;border-color:#1f6feb;color:#fff;font-weight:600}
button:hover{filter:brightness(1.15)}
button.voice.listening{background:#5a1d1d;border-color:var(--bad);color:#ffb4ae;
animation:pulse 1.2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.55}}
.row{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.chip{font-size:12px;color:var(--acc);background:transparent;
border:1px solid var(--line);border-radius:999px;padding:4px 12px}
.chip:hover{border-color:var(--acc)}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:600}
.b-COMPLETED{background:#12351c;color:var(--ok)}.b-RUNNING{background:#2a1e47;color:var(--run)}
.b-READY{background:#0b2a4a;color:var(--acc)}.b-FAILED{background:#3d1214;color:var(--bad)}
.b-RECOVERY{background:#3b2a08;color:var(--warn)}.b-WAITING{background:#33313a;color:var(--mut)}
.b-HIGH{background:#3d1214;color:#ff7b72}.b-MEDIUM{background:#3b2a08;color:#e3b341}.b-LOW{background:#12351c;color:#7ee787}
.muted{color:var(--mut)}.small{font-size:12px}
.intent{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin-bottom:8px}
.intent .head{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.intent .goal{flex:1;min-width:200px}
.file{display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid var(--line)}
.file .meta{flex:1;min-width:0}.file .name{font-weight:600;font-size:13px;word-break:break-all}
.file .path{font-size:11px;color:var(--mut);word-break:break-all}
.file button{padding:4px 10px;font-size:12px}
.auto{background:#0b2a4a;border:1px solid #1f4e7d;border-radius:8px;padding:8px 12px;margin-bottom:10px;font-size:12.5px}
.auto b{color:var(--acc)}
pre.view{background:#0d1117;border:1px solid var(--line);border-radius:8px;padding:12px;
font:12px/1.55 Consolas,monospace;white-space:pre-wrap;max-height:340px;overflow:auto;margin-top:8px}
.err{color:var(--bad);margin-top:8px;font-size:13px}
.kpis{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:12.5px;color:var(--mut)}
.kpis b{color:var(--fg)}
</style></head><body>
<h1>&#8984; IntentOS</h1>
<p class="tagline">Tell it <i>what</i> you want to accomplish &mdash; the kernel classifies the goal,
plans the steps, checks permissions, allocates resources, picks the scheduling policy automatically,
executes real services, recovers from failures, and writes the files to disk.</p>
<div class="grid"><div>
<div class="panel">
  <h2>What do you want to accomplish?</h2>
  <input id="inp" type="text" placeholder='e.g. "Write a brief summary of quantum computing"' autofocus>
  <div class="row">
    <button class="primary" onclick="run()">RUN</button>
    <button id="voicebtn" class="voice" onclick="startVoice()">&#127908; Voice</button>
    <button onclick="demo()" title="Submit several intents at once">Demo workload</button>
  </div>
  <div class="row" id="chips"></div>
  <div id="err" class="err"></div>
  <div class="kpis" id="kpis"></div>
</div>
<div class="panel"><h2>Intent Processes</h2><div id="intents"><p class="muted">No intents yet.</p></div></div>
</div><div>
<div class="panel"><h2>Scheduler (automatic)</h2>
  <div class="auto" id="autopolicy">waiting for first dispatch&hellip;</div>
  <p class="muted small">The kernel picks FCFS / Priority / Round Robin / EDF per workload:
  aging &rarr; deadlines &rarr; priorities &rarr; fairness &rarr; arrival order. No manual choice needed.</p>
</div>
<div class="panel"><h2>Files created on disk</h2><div id="files"><p class="muted">Nothing yet.</p></div></div>
<div class="panel"><h2>Services</h2><div id="services" class="small"></div></div>
</div></div>
<pre class="view" id="viewer" style="display:none"></pre>
<script>
const EXAMPLES = [
 'Write a brief summary of quantum computing',
 'Explain CPU scheduling algorithms',
 'Create a summary about the Linux kernel',
 'Prepare everything for my 4 PM meeting',
 'Send a message to John about the report',
];
document.getElementById('chips').innerHTML =
  EXAMPLES.map(e=>`<button class="chip" onclick="submitText('${e.replace(/'/g,"\\\\'")}')">${e}</button>`).join('');

async function api(p, body){
  const r = await fetch(p, body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);
  const d = await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(d.error||r.status);
  return d;
}
async function submitText(t){
  try{ await api('/api/intents',{text:t}); refresh(); }
  catch(e){ document.getElementById('err').textContent = e.message; }
}
function run(){ const i=document.getElementById('inp'); if(i.value.trim()){submitText(i.value.trim()); i.value='';} }

let _rec = null, _listening = false;
function startVoice(){
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){
    document.getElementById('err').textContent =
      'Voice input requires the Web Speech API - use Chrome or Edge.';
    return;
  }
  if(_listening && _rec){ _rec.stop(); return; }   // click again to stop
  const btn = document.getElementById('voicebtn');
  _rec = new SR();
  _rec.lang = 'en-US';
  _rec.interimResults = false;
  _rec.continuous = false;
  _rec.onstart = () => { _listening = true; btn.classList.add('listening');
                         btn.innerHTML = '&#127908; Listening&hellip;'; };
  _rec.onend = () => { _listening = false; btn.classList.remove('listening');
                       btn.innerHTML = '&#127908; Voice'; };
  _rec.onerror = (e) => { _listening = false; btn.classList.remove('listening');
                          btn.innerHTML = '&#127908; Voice';
                          document.getElementById('err').textContent =
                            'Voice error: ' + e.error; };
  _rec.onresult = (event) => {
    const said = event.results[0][0].transcript;
    document.getElementById('inp').value = said;
    submitText(said);          // submit immediately, like the React UI
  };
  _rec.start();
}
async function demo(){
  for(const t of ['Write a brief summary of quantum computing',
                  'Prepare everything for my 4 PM meeting',
                  'Send a message to John about the report'])
    await api('/api/intents',{text:t});
  refresh();
}
document.getElementById('inp').addEventListener('keydown',e=>{if(e.key==='Enter')run();});

const ICON={DONE:'\\u2713',STEP_FAILED:'\\u2717',BLOCKED:'\\u2298',PENDING:'\\u25cb'};
function render(s){
  document.getElementById('err').textContent='';
  const m=s.metrics||{};
  document.getElementById('kpis').innerHTML =
    `<span>submitted <b>${m.submitted||0}</b></span><span>completed <b>${m.completed||0}</b></span>`+
    `<span>failed <b>${m.failed||0}</b></span><span>retries <b>${m.retries||0}</b></span>`+
    `<span>deadline misses <b>${m.deadline_misses||0}</b></span>`;
  document.getElementById('autopolicy').innerHTML = s.scheduler_policy
    ? `policy <b>${s.scheduler_policy.toUpperCase()}</b> &mdash; ${s.scheduler_reason||''}`
    : 'waiting for first dispatch&hellip;';
  const list=(s.intents||[]).slice().reverse();
  document.getElementById('intents').innerHTML = list.length? list.map(i=>{
    const p=i.progress||{};
    const steps=(i.plan||[]).map(st=>{
      const stt=i.step_state[st.id]||'PENDING';
      const col=stt==='DONE'?'var(--ok)':(stt==='STEP_FAILED'?'var(--bad)':(stt==='PENDING'?'var(--mut)':'var(--acc)'));
      return `<div class="small" style="color:${col}">${ICON[stt]||'\\u25cb'} ${st.service}.${st.capability}</div>`;
    }).join('');
    const art=(s.artifacts||[]).filter(a=>a.intent_id===i.id).map(a=>
      `<div class="small" style="color:var(--ok)">&#10142; file: ${a.display_path||a.path} (${a.bytes} bytes)</div>`).join('');
    return `<div class="intent"><div class="head">
      <span class="badge b-${i.state}">${i.state}</span>
      <span class="muted small">${i.id}</span>
      <span class="goal">${i.goal}</span>
      <span class="badge b-${i.priority}">${i.priority}</span>
      <span class="muted small">${p.DONE||0}\\u2713 ${(p.STEP_FAILED||0)+(p.BLOCKED||0)}\\u2717 ${p.PENDING||0}\\u25cb</span>
      </div><div style="margin-top:6px">${steps}${art}</div></div>`;
  }).join('') : '<p class="muted">No intents yet.</p>';

  const wf=s.artifacts||[];
  document.getElementById('files').innerHTML = wf.length? wf.map(f=>
    `<div class="file"><div class="meta"><div class="name">${f.name||''}</div>
     <div class="path">${f.display_path||f.path||''} &middot; ${f.bytes||0} bytes</div></div>
     <button onclick="view('${encodeURIComponent(f.path)}')">View</button>
     <button onclick="openInOS('${encodeURIComponent(f.path)}')">Open</button></div>`
  ).join('') : '<p class="muted">Nothing yet &mdash; ask for a summary above.</p>';

  document.getElementById('services').innerHTML = (s.services||[]).map(sv=>
    `<div style="padding:3px 0"><b>${sv.name}</b> <span class="muted">&mdash; ${sv.description||''}</span></div>`).join('');
}
async function refresh(){ try{ render(await api('/api/status')); }catch(e){} }
async function view(p){
  const v=document.getElementById('viewer');
  try{ const d=await api('/api/file?path='+p); v.style.display='block';
       v.textContent='=== '+(d.name||d.path)+' ===\\n\\n'+(d.content||'(empty)'); v.scrollIntoView({behavior:'smooth'}); }
  catch(e){ v.style.display='block'; v.textContent='Cannot preview: '+e.message; }
}
async function openInOS(p){ try{ await api('/api/open',{path:decodeURIComponent(p)}); }catch(e){} }
refresh(); setInterval(refresh,1200);
</script></body></html>
"""



def _worker(kernel: IntentKernel) -> None:
    """Background loop that drains the READY queue with paced steps."""
    while True:
        acted = kernel.step_once()
        if acted is None:
            time.sleep(0.1)
        else:
            time.sleep(STEP_DELAY)


class IntentOSHandler(BaseHTTPRequestHandler):
    kernel: IntentKernel = None  # injected by serve()

    # ------------------------------------------------------------------
    def _send(self, code: int, payload) -> None:
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def log_message(self, fmt, *args):  # quiet console
        pass

    # ------------------------------------------------------------------
    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _list_workspace(kernel: IntentKernel) -> list:
        """Files currently on disk in the user-visible workspace folders."""
        from intent_kernel.paths import workspace_dir, documents_dir
        out = []
        for base in (workspace_dir(), documents_dir()):
            if not base.is_dir():
                continue
            for p in sorted(base.rglob("*")):
                if p.is_file() and not p.name.endswith(".part"):
                    out.append({
                        "path": str(p),
                        "name": p.name,
                        "bytes": p.stat().st_size,
                        "modified": time.strftime(
                            "%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)),
                        "folder": str(p.parent),
                    })
        return out

    # ------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        k = self.kernel
        if path == "/":
            self._send_html(_INDEX_HTML)
        elif path == "/api/health":
            self._send(200, {"status": "ok", "strategy": k.strategy})
        elif path == "/api/status":
            self._send(200, k.status())
        elif path == "/api/metrics":
            self._send(200, k.metrics())
        elif path == "/api/system":
            from intent_kernel.resource_manager.monitor import system_snapshot
            self._send(200, system_snapshot())
        elif path == "/api/simulation":
            self._send(200, {"results": compare_strategies()})
        elif path == "/api/schedulers":
            self._send(200, {"schedulers": sorted(SCHEDULERS)})
        elif path == "/api/files":
            self._send(200, {"files": k.all_artifacts(limit=50),
                             "workspace": self._list_workspace(k)})
        elif path == "/api/file":
            from pathlib import Path
            from intent_kernel.paths import root as _root
            raw = (query.get("path") or [""])[0]
            if raw and not Path(raw).is_absolute():
                raw = str(_root() / raw)   # project-relative paths from the UI
            svc = k.bus.get("filesystem")
            try:
                out = svc.cap_read_file({"path": raw})
            except ServiceError as exc:
                return self._send(404, {"error": str(exc)})
            if out.get("binary"):
                return self._send(400, {"error": "binary file; preview unavailable"})
            self._send(200, {"path": out["path"], "name": out["name"],
                             "bytes": out["size"], "content": out["content"]})
        else:
            self._send(404, {"error": f"unknown route {path}"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")
        body = self._read_json()
        k = self.kernel
        try:
            if path == "/api/intents":
                text = (body.get("text") or "").strip()
                if not text:
                    return self._send(400, {"error": "'text' is required"})
                intent = k.submit_text(
                    text,
                    priority=body.get("priority"),
                    deadline=body.get("deadline"),
                )
                return self._send(201, intent.to_dict(include_log=True))
            if path == "/api/strategy":
                strategy = body.get("strategy")
                if strategy not in SCHEDULERS:
                    return self._send(400, {"error": f"unknown strategy; options: {sorted(SCHEDULERS)}"})
                k.set_strategy(strategy)
                return self._send(200, {"strategy": k.strategy})
            if path == "/api/faults":
                service = body.get("service")
                count = int(body.get("count", 1))
                k.set_fault(service, count)
                return self._send(200, {"service": service, "fail_next": count})
            if path == "/api/open":
                raw = body.get("path") or ""
                svc = k.bus.get("filesystem")
                out = svc.cap_reveal({"path": raw})
                return self._send(200, out)
            if path == "/api/run":
                steps = k.run_all()
                return self._send(200, {"steps_executed": steps})
            return self._send(404, {"error": f"unknown route {path}"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})


def serve(port: int = 8765, host: str = "127.0.0.1", open_browser: bool = True) -> None:
    kernel = IntentKernel(strategy="auto", latency=0.0)
    IntentOSHandler.kernel = kernel
    threading.Thread(target=_worker, args=(kernel,), daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), IntentOSHandler)
    print(f"IntentOS application running on http://{host}:{port}")
    print(f"  Strategy: {kernel.strategy}")
    print(f"  UI:       http://{host}:{port}")
    print(f"  API:      GET /api/status  POST /api/intents")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IntentOS API server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    serve(port=args.port, host=args.host)
