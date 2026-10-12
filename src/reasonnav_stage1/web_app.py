"""Dependency-free localhost UI for the first-stage human-in-the-loop loop."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .runtime import EpisodeRunner


_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ReasonNav 第一阶段实验</title>
<style>
body{font-family:system-ui,-apple-system,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#202124;background:#f7f8fa}
.card{background:white;border:1px solid #dfe3e8;border-radius:12px;padding:1rem 1.2rem;margin:1rem 0;box-shadow:0 1px 2px #0000000b}
pre{white-space:pre-wrap;background:#f1f3f4;border-radius:8px;padding:.8rem;overflow:auto}
button{border:0;border-radius:8px;padding:.7rem 1rem;margin:.25rem;cursor:pointer;font-size:1rem}
.primary{background:#1967d2;color:white}.ok{background:#188038;color:white}.stop{background:#d93025;color:white}.muted{color:#5f6368}
</style></head>
<body>
<h1>ReasonNav 第一阶段实验</h1>
<p class="muted">人在回路 · 单步观察 · 单步执行 · 反馈后再决策</p>
<div class="card"><strong>目标</strong><div id="goal">加载中…</div><strong>状态</strong><div id="status">加载中…</div></div>
<div class="card"><h2>当前导航指令</h2><pre id="intent">尚未生成指令</pre>
<button class="primary" onclick="nextDecision()">生成下一条指令</button>
<button class="ok" onclick="execute('completed')">已完成</button>
<button onclick="execute('failed')">无法完成</button>
<button class="stop" onclick="execute('skipped')">停止/跳过</button></div>
<div class="card"><h2>历史记忆</h2><pre id="memory">[]</pre></div>
<div class="card"><h2>执行反馈</h2><textarea id="result" rows="3" style="width:100%" placeholder="记录实际看到或执行的结果"></textarea></div>
<script>
let state={};
async function refresh(){const r=await fetch('/api/state');state=await r.json();
document.querySelector('#goal').textContent=state.goal.value;
document.querySelector('#status').textContent=state.status;
document.querySelector('#memory').textContent=JSON.stringify(state.memory,null,2);
const last=(state.records||[]).slice(-1)[0];
if(last){document.querySelector('#intent').textContent=JSON.stringify(last.intent,null,2);}}
async function nextDecision(){const r=await fetch('/api/step',{method:'POST'});const d=await r.json();if(!r.ok) alert(d.error||'生成失败');await refresh();}
async function execute(status){const actual=document.querySelector('#result').value;const r=await fetch('/api/execute',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status,actual_result:actual})});const d=await r.json();if(!r.ok) alert(d.error||'记录失败');document.querySelector('#result').value='';await refresh();}
refresh();
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    runner: EpisodeRunner

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self._send(HTTPStatus.OK, _HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._json(HTTPStatus.OK, self.runner.snapshot())
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/step":
            try:
                response = self.runner.next_decision()
                self._json(HTTPStatus.OK, {"response": response.raw_text, "state": self.runner.snapshot()})
            except (RuntimeError, ValueError) as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc), "state": self.runner.snapshot()})
            return
        if self.path == "/api/execute":
            try:
                payload = self._body()
                result = self.runner.record_execution(
                    status=str(payload.get("status", "completed")),
                    actual_result=str(payload.get("actual_result", "")),
                    operator_note=str(payload.get("operator_note", "")),
                )
                self._json(HTTPStatus.OK, {"result": result.status, "state": self.runner.snapshot()})
            except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc), "state": self.runner.snapshot()})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(runner: EpisodeRunner, host: str = "127.0.0.1", port: int = 8765) -> None:
    handler = type("ReasonNavHandler", (_Handler,), {"runner": runner})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"ReasonNav UI: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
