"""L2 数据管线 — 自动采集+健康检查"""
import os, sys, json
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import db
from core.config import config
from core.logging import get_logger
from layer1_data.tencent_api import get_all_quotes, get_indices
logger = get_logger("pipeline")

def health() -> dict:
    s = {"ok": True, "checks": {}}
    try:
        db.query_one("SELECT 1"); s["checks"]["database"] = "ok"
    except Exception as e: s["checks"]["database"] = str(e); s["ok"] = False
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        rows = db.query("SELECT ts_code, MAX(trade_date) as last FROM stock_daily GROUP BY ts_code")
        stale = [r for r in rows if (r["last"] or "") < today]
        s["checks"]["freshness"] = {"total": len(rows), "stale": len(stale), "sample": [r["ts_code"] for r in stale[:5]]}
    except Exception as e: s["checks"]["freshness"] = str(e)
    return s

def run(brief=False):
    t0 = datetime.now()
    r = {"time": t0.strftime("%Y-%m-%d %H:%M:%S"), "steps": {}, "status": "ok"}

    logger.info("Step 1: 健康检查")
    h = health(); r["steps"]["health"] = h
    if not h["ok"]: r["status"] = "degraded"

    logger.info("Step 2: 实时行情")
    qs = get_all_quotes(); idx = get_indices()
    r["steps"]["realtime"] = {"stocks": len(qs), "indices": {k: v.get("price") for k, v in idx.items()}}

    if not brief:
        logger.info("Step 3: 存储行情")
        now = datetime.now().strftime("%Y-%m-%d"); saved = 0
        for c, d in qs.items():
            if d.get("price"):
                try:
                    db.execute("INSERT OR REPLACE INTO stock_daily (ts_code,trade_date,open,high,low,close,vol,amount,pct_chg) VALUES (?,?,?,?,?,?,?,?,?)",
                               (c, now, d["open"], d["high"], d["low"], d["price"], d["volume"], d["amount"], d["pct_chg"]))
                    saved += 1
                except: pass
        r["steps"]["storage"] = {"saved": saved}

    r["elapsed"] = round((datetime.now() - t0).total_seconds(), 1)
    logger.info(f"管线完成 {r['elapsed']}s")
    return r
