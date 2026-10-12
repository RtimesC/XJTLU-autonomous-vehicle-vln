"""Dependency-free localhost UI for the first-stage human-in-the-loop loop."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .runtime import EpisodeRunner


_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ReasonNav · 人机协同导航</title>
<style>
:root{--ink:#162033;--muted:#6b778c;--line:#dce3ed;--paper:#f4f7fb;--card:#fff;--blue:#2864dc;--blue-dark:#1744a6;--green:#16845b;--amber:#bc7412;--red:#c44b4b;--shadow:0 12px 32px #203a5b12}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 85% -10%,#dce9ff 0,#f4f7fb 35%,#f4f7fb 100%);color:var(--ink);font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
button,textarea{font:inherit}button{cursor:pointer}.shell{max-width:1280px;margin:auto;padding:28px 26px 42px}.topbar{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:24px}.brand{display:flex;align-items:center;gap:13px}.brand-mark{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;color:#fff;font-weight:800;font-size:18px;background:linear-gradient(145deg,#467ef0,#163b9b);box-shadow:0 8px 18px #2864dc44}.eyebrow{margin:0;color:var(--blue);font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase}.brand h1{margin:2px 0 0;font-size:21px;letter-spacing:-.02em}.session{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:12px}.dot{width:8px;height:8px;border-radius:50%;background:#26a269;box-shadow:0 0 0 4px #26a2691c}.layout{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(300px,.8fr);gap:18px}.card{background:var(--card);border:1px solid #e1e7f0;border-radius:18px;box-shadow:var(--shadow)}.hero{padding:22px 24px;display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:18px}.hero h2{font-size:27px;letter-spacing:-.04em;margin:4px 0 4px}.hero p{margin:0;color:var(--muted)}.state{padding:8px 12px;border-radius:999px;background:#eaf7f1;color:var(--green);font-weight:700;white-space:nowrap}.section{padding:20px 22px;margin-bottom:18px}.section-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px}.section-head h3{margin:0;font-size:15px}.section-head span{color:var(--muted);font-size:12px}.observation{min-height:230px;border:1px dashed #b8c7dc;border-radius:14px;background:linear-gradient(135deg,#f8fbff,#eef4fc);display:grid;place-items:center;text-align:center;color:var(--muted);padding:24px}.observation .camera-icon{width:52px;height:52px;border-radius:16px;background:#dbe8ff;color:var(--blue);display:grid;place-items:center;font-size:25px;margin:0 auto 10px}.observation strong{display:block;color:var(--ink);font-size:15px}.observation small{display:block;margin-top:5px}.intent{border-radius:14px;background:#121d31;color:#e8efff;padding:18px 19px;min-height:122px}.intent-label{display:flex;align-items:center;gap:8px;color:#91b4ff;font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}.intent-text{font-size:22px;line-height:1.25;margin:12px 0 8px;color:#fff}.intent-meta{color:#afbed8;font-size:12px;white-space:pre-wrap}.action-row{display:flex;flex-wrap:wrap;gap:9px;margin-top:15px}.btn{border:1px solid var(--line);border-radius:11px;background:#fff;color:var(--ink);padding:10px 14px;font-weight:700;transition:.15s}.btn:hover{transform:translateY(-1px);border-color:#9eb5dd}.btn.primary{border-color:var(--blue);background:var(--blue);color:#fff}.btn.primary:hover{background:var(--blue-dark)}.btn.success{border-color:#b7e2d0;background:#edfaf4;color:var(--green)}.btn.danger{border-color:#f0c4c4;background:#fff5f5;color:var(--red)}.btn:disabled{opacity:.45;cursor:not-allowed;transform:none}.feedback textarea{width:100%;resize:vertical;border:1px solid var(--line);border-radius:11px;padding:12px 13px;outline:none;min-height:76px;background:#fbfcfe}.feedback textarea:focus{border-color:#6b94e8;box-shadow:0 0 0 3px #2864dc18}.feedback-foot{display:flex;justify-content:space-between;align-items:center;margin-top:10px;color:var(--muted);font-size:12px}.side{display:flex;flex-direction:column;gap:18px}.side .section{margin:0}.metric-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.metric{padding:13px;border-radius:12px;background:#f6f8fc}.metric label{display:block;color:var(--muted);font-size:11px;margin-bottom:4px}.metric strong{font-size:17px}.timeline{list-style:none;padding:0;margin:0}.timeline li{position:relative;padding:0 0 16px 22px;border-left:1px solid #d9e1ed}.timeline li:last-child{padding-bottom:0;border-left-color:transparent}.timeline li:before{content:"";position:absolute;left:-5px;top:2px;width:9px;height:9px;border:2px solid #fff;border-radius:50%;background:#86a6df;box-shadow:0 0 0 1px #a6bce2}.timeline b{display:block;font-size:12px}.timeline span{color:var(--muted);font-size:12px}.memory{max-height:230px;overflow:auto;background:#f7f9fc;border-radius:12px;padding:13px;color:#4f5c70;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap}.footnote{color:var(--muted);font-size:11px;text-align:center;margin-top:24px}.toast{position:fixed;right:22px;bottom:22px;max-width:340px;padding:12px 15px;border-radius:12px;background:#162033;color:#fff;box-shadow:var(--shadow);opacity:0;transform:translateY(8px);pointer-events:none;transition:.2s}.toast.show{opacity:1;transform:none}@media(max-width:850px){.shell{padding:18px 14px 30px}.layout{grid-template-columns:1fr}.hero{align-items:flex-start;flex-direction:column}.session{display:none}}
</style></head>
<body>
<main class="shell">
<header class="topbar"><div class="brand"><div class="brand-mark">R</div><div><p class="eyebrow">Human-in-the-loop navigation</p><h1>ReasonNav 控制台</h1></div></div><div class="session"><i class="dot"></i><span>本地实验会话 · 已连接</span></div></header>
<section class="card hero"><div><p class="eyebrow">当前任务</p><h2 id="goal">加载中…</h2><p>观察 → 建议 → 人工执行 → 反馈 → 再观察</p></div><div class="state" id="status">加载中…</div></section>
<div class="layout"><div>
<section class="card section"><div class="section-head"><h3>观察输入</h3><span id="step-label">等待第一帧</span></div><div class="observation"><div><div class="camera-icon">◉</div><strong id="observation-title">等待观测</strong><small id="observation-detail">当前为离线回放模式；接入相机后这里显示 RGB-D 观测状态。</small></div></div></section>
<section class="card section"><div class="section-head"><h3>导航建议</h3><span>模型输出 · 待人工确认</span></div><div class="intent"><div class="intent-label"><span>✦</span> NEXT ACTION</div><div class="intent-text" id="intent-text">尚未生成指令</div><div class="intent-meta" id="intent-meta">点击“请求下一条建议”开始一次单步决策。</div></div><div class="action-row"><button class="btn primary" id="next-btn" onclick="nextDecision()">请求下一条建议</button><button class="btn success" id="complete-btn" onclick="execute('completed')" disabled>✓ 已完成</button><button class="btn" id="failed-btn" onclick="execute('failed')" disabled>↺ 执行失败</button><button class="btn danger" id="stop-btn" onclick="execute('skipped')" disabled>■ 停止 / 跳过</button></div></section>
<section class="card section feedback"><div class="section-head"><h3>执行反馈</h3><span>由操作者确认实际结果</span></div><textarea id="result" placeholder="例如：沿走廊前进约 3 米，在楼梯口停下；或记录看到的地标、障碍和偏差…"></textarea><div class="feedback-foot"><span>反馈会写入本轮记忆，供下一次建议使用。</span><span id="char-count">0 / 500</span></div></section>
</div><aside class="side">
<section class="card section"><div class="section-head"><h3>会话概览</h3><span>LIVE</span></div><div class="metric-grid"><div class="metric"><label>已决策步数</label><strong id="step-count">0</strong></div><div class="metric"><label>待处理建议</label><strong id="pending">无</strong></div><div class="metric"><label>执行反馈</label><strong id="feedback-count">0</strong></div><div class="metric"><label>记忆条目</label><strong id="memory-count">0</strong></div></div></section>
<section class="card section"><div class="section-head"><h3>交互轨迹</h3><span>本轮活动</span></div><ol class="timeline" id="timeline"><li><b>会话已建立</b><span>等待第一次观测与决策</span></li></ol></section>
<section class="card section"><div class="section-head"><h3>历史记忆</h3><span>反馈摘要</span></div><div class="memory" id="memory">暂无反馈记忆</div></section>
</aside></div>
<p class="footnote">ReasonNav Stage 1 · 人在回路 · 单步决策与反馈 · 模型和相机适配器可后续替换</p>
</main><div class="toast" id="toast"></div>
<script>
let state={};
const $=id=>document.getElementById(id);
function showToast(message){const t=$('toast');t.textContent=message;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2600)}
function intentLabel(intent){if(!intent)return '尚未生成指令';const text=intent.instruction||intent.action||intent.intent||intent.raw_text;return typeof text==='string'?text:'已生成导航建议'}
function render(){
 $('goal').textContent=state.goal?.value||'未设置目标';$('status').textContent=state.status||'未知';
 const records=state.records||[],last=records[records.length-1],pending=!!(last&&last.execution===null);
 $('step-count').textContent=records.length;$('feedback-count').textContent=records.filter(r=>r.execution).length;$('memory-count').textContent=(state.memory||[]).length;$('pending').textContent=pending?'待确认':'无';
 $('next-btn').disabled=pending||state.status==='stopped'||state.status==='no_more_observations';['complete-btn','failed-btn','stop-btn'].forEach(id=>$(id).disabled=!pending);
 if(last){$('step-label').textContent='第 '+last.observation.step_id+' 步';$('observation-title').textContent='已接收第 '+last.observation.step_id+' 帧观测';$('observation-detail').textContent='观测已送入当前决策流程（离线回放）';$('intent-text').textContent=intentLabel(last.intent);$('intent-meta').textContent=last.intent?.stop?'模型建议停止当前任务':'请先执行建议，再提交结果';}
 $('memory').textContent=(state.memory||[]).length?JSON.stringify(state.memory,null,2):'暂无反馈记忆';
 const timeline=$('timeline');timeline.innerHTML='<li><b>会话已建立</b><span>目标：'+(state.goal?.value||'未设置')+'</span></li>';
 records.slice().reverse().forEach(record=>{const li=document.createElement('li');li.innerHTML='<b>步骤 '+record.observation.step_id+' · '+(record.execution?'已反馈':'等待执行')+'</b><span>'+intentLabel(record.intent)+'</span>';timeline.appendChild(li)});
}
async function refresh(){const r=await fetch('/api/state');state=await r.json();render()}
async function nextDecision(){const b=$('next-btn');b.disabled=true;const r=await fetch('/api/step',{method:'POST'});const d=await r.json();if(!r.ok)showToast(d.error||'生成失败');else showToast('已生成新的导航建议');await refresh()}
async function execute(status){const actual=$('result').value.trim();const r=await fetch('/api/execute',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status,actual_result:actual})});const d=await r.json();if(!r.ok){showToast(d.error||'记录失败');return} $('result').value='';showToast(status==='completed'?'已记录完成':'已记录执行反馈');await refresh()}
$('result').addEventListener('input',e=>{if(e.target.value.length>500)e.target.value=e.target.value.slice(0,500);$('char-count').textContent=e.target.value.length+' / 500'});refresh();
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
