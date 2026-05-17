"""L5 执行追踪 — 止损/止盈监控"""
import os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import config
from core.logging import get_logger
from layer1_data.tencent_api import get_all_quotes
logger = get_logger("monitor")

def check_stops(quotes=None):
    if quotes is None: quotes = get_all_quotes()
    alerts = []
    for s in config.stocks:
        q = quotes.get(s["code"], {}); p = q.get("price", 0); cost = s.get("cost", 0); stop = s.get("stop", 0)
        if not p or not cost: continue
        pct = round((p / cost - 1) * 100, 2) if cost else 0
        if p <= stop:
            alerts.append({"code": s["code"], "name": s["name"], "type": "止损触发", "price": p, "stop": stop,
                           "pct": pct, "severity": "CRITICAL"})
        elif pct < -5:
            alerts.append({"code": s["code"], "name": s["name"], "type": "浮亏预警", "price": p, "stop": stop,
                           "pct": pct, "severity": "WARNING"})
    return alerts

def check_targets(quotes=None):
    if quotes is None: quotes = get_all_quotes()
    alerts = []
    for s in config.stocks:
        q = quotes.get(s["code"], {}); p = q.get("price", 0); tgt = s.get("target", 0)
        if not p or not tgt: continue
        pct = round((p / tgt - 1) * 100, 2) if tgt else 0
        if pct >= -5:
            alerts.append({"code": s["code"], "name": s["name"], "type": "接近止盈", "price": p, "target": tgt,
                           "pct": pct, "severity": "INFO"})
    return alerts

def get_all():
    qs = get_all_quotes()
    return {"time": datetime.now().strftime("%H:%M:%S"), "stops": check_stops(qs), "targets": check_targets(qs)}
