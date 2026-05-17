"""Web看板 — 实时持仓/评分/审计/预警"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flask import Flask, render_template_string, jsonify
from core.config import config
from layer1_data.tencent_api import get_all_quotes, get_indices
from layer3_analysis.technical import score_all
from layer5_execution.audit import audit
from layer5_execution.monitor import get_all as get_monitor

app = Flask(__name__)

HTML = '<''!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>多宝v2.0</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:"Microsoft YaHei",sans-serif;background:#0f1923;color:#d0dce8;min-height:100vh}
.header{background:linear-gradient(135deg,#1a2a3a,#1e3040);padding:14px 28px;border-bottom:2px solid #2a4a6a;display:flex;justify-content:space-between;align-items:center}
.header h1{font-size:20px;color:#5ca0d8} .header .act{display:flex;align-items:center;gap:12px}
.header .time{color:#7a9ab8;font-size:13px} .btn{background:#2a5a8a;color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px}
.btn:hover{background:#3a6a9a} .container{max-width:1500px;margin:0 auto;padding:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:16px}
.card{background:#152330;border-radius:10px;padding:16px;border:1px solid #1e3040}
.card h2{font-size:16px;color:#5ca0d8;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #1e3040}
table{width:100%;border-collapse:collapse;font-size:12px}th{text-align:left;padding:6px 4px;color:#7a9ab8;border-bottom:1px solid#1e3040;font-weight:400}
td{padding:6px 4px;border-bottom:1px solid#0f1a24}tr:hover{background:#1a2a38}
.tag{display:inline-block;padding:1px 7px;border-radius:4px;font-size:11px;font-weight:700}
.t-BUY{background:#1a4a2a;color:#4ae04a}.t-WATCH{background:#4a3a1a;color:#e0c04a}.t-HOLD{background:#2a3a4a;color:#aab4c0}.t-AVOID{background:#3a1a1a;color:#e04a4a}
.t-ADD{background:#1a3a5a;color:#4ab4e0}.t-REDUCE{background:#4a3a1a;color:#e0a04a}.t-CLOSE{background:#4a1a1a;color:#e04a4a}
.alert{padding:10px;border-radius:6px;margin-bottom:6px;font-size:13px}
.a-CRITICAL{background:#3a1a1a;border:1px solid#e04a4a}.a-WARNING{background:#3a2a1a;border:1px solid#e0a04a}.a-INFO{background:#1a2a3a;border:1px solid#4ab4e0}
.idx{display:flex;gap:12px;flex-wrap:wrap}.idx-i{background:#1a2a38;padding:10px 14px;border-radius:6px;text-align:center;min-width:110px}
.idx-n{font-size:11px;color:#7a9ab8}.idx-p{font-size:18px;font-weight:700}.idx-c{font-size:12px}
.up{color:#e04a4a}.dn{color:#4ae04a}.loading{text-align:center;color:#7a9ab8;padding:60px;font-size:16px}
</style></head><body>
<div class="header"><h1>🔮 多宝 v2.0 · 股票分析系统</h1><div class="act"><span class="time" id="ut">加载中...</span><button class="btn" onclick="reload()">刷新</button></div></div>
<div class="container" id="app"><div class="loading">正在加载数据...</div></div>
<script>
async function reload(){document.getElementById("app").innerHTML="<div class=loading>刷新中...</div>";
try{const[A,B,C,D]=await Promise.all([fetch("/api/quotes").then(r=>r.json()),fetch("/api/scoring").then(r=>r.json()),fetch("/api/audit").then(r=>r.json()),fetch("/api/monitor").then(r=>r.json())]);
document.getElementById("ut").textContent=new Date().toLocaleTimeString("zh-CN");
let h="";
const al=D.stops||[],at=D.targets||[];
if(al.length+at.length>0){h+="<div class=card><h2>🔔 预警</h2>";
al.forEach(a=>h+=`<div class="alert a-${a.severity}">${a.severity=="CRITICAL"?"🚨":"⚠️"} ${a.name} ${a.type}: 现价${a.price} 止损${a.stop} 浮亏${a.pct}%</div>`);
at.forEach(a=>h+=`<div class="alert a-INFO">🎯 ${a.name} 接近止盈: 现价${a.price} 目标${a.target}</div>`);h+="</div>";}
h+="<div class=card><h2>🎯 六因子均值回归评分 (0-10制)</h2><table><tr><th>股票</th><th>现价</th><th>回撤深度</th><th>超卖强度</th><th>连跌衰竭</th><th>量价背离</th><th>波动收敛</th><th>支撑强度</th><th>总分</th><th>信号</th></tr>";
for(const[k,s]of Object.entries(B)){const f=s.factors||{};h+=`<tr><td>${s.name}</td><td>${(s.technicals?.price||"-").toFixed?.(2)||"-"}</td>`;
["回撤深度","超卖强度","连跌衰竭","量价背离","波动收敛","支撑强度"].forEach(x=>h+=`<td>${(f[x]||0).toFixed(2)}</td>`);
h+=`<td><b>${(s.total||0).toFixed(1)}</b></td><td><span class="tag t-${s.signal||"HOLD"}">${s.signal||"HOLD"}</span></td></tr>`;}h+="</table></div>";
h+="<div class=card><h2>📋 四维持仓审计 T/B/F/R</h2><table><tr><th>股票</th><th>现价</th><th>T趋势</th><th>B估值</th><th>F因子</th><th>R风险</th><th>总分</th><th>建议</th></tr>";
for(const[k,a]of Object.entries(C)){const sc=a.scores||{};h+=`<tr><td>${a.name}</td><td>${(a.price||"-").toFixed?.(2)||"-"}</td>`;
["T","B","F","R"].forEach(x=>h+=`<td>${sc[x]||"-"}</td>`);
h+=`<td><b>${a.total||"-"}</b></td><td><span class="tag t-${a.action||"HOLD"}">${a.action||"HOLD"}</span></td></tr>`;}h+="</table></div>";
document.getElementById("app").innerHTML=h;}catch(e){document.getElementById("app").innerHTML="<div class=loading>加载失败: "+e.message+"</div>";}}
reload();setInterval(reload,60000);
</script></body></html>'

@app.route("/")
def index(): return render_template_string(HTML)

@app.route("/api/quotes")
def quotes():
    qs = get_all_quotes(); r = {}
    for c, d in qs.items(): r[c] = {"name": d.get("name"), "price": d.get("price"), "pct_chg": d.get("pct_chg")}
    return jsonify(r)

@app.route("/api/scoring")
def scoring(): return jsonify(score_all())

@app.route("/api/audit")
def api_audit(): return jsonify(audit())

@app.route("/api/monitor")
def api_monitor(): return jsonify(get_monitor())

def run():
    h = config.get("notifications", "web_dashboard", "host", default="127.0.0.1")
    p = config.get("notifications", "web_dashboard", "port", default=8088)
    app.run(host=h, port=p, debug=False)

if __name__ == "__main__": run()
