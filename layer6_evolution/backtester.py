"""鍥犲瓙鍥炴祴鏍￠獙妯″潡 杩借釜鍥犲瓙鍑嗙‘鐜囦笌鍖哄垎搴?
v2.5: 鐩存帴浠巉actor_backtest_data璇诲彇鍘嗗彶鍥犲瓙鏁版嵁鍔犻€熷洖娴?
"""
import json, os
from datetime import datetime, timedelta
import numpy as np
from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("backtester")
BACKTEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "backtest")
os.makedirs(BACKTEST_DIR, exist_ok=True)

def save_snapshot(date_str, scores, audit_data, seven_dim):
    try:
        snapshot = {"date": date_str, "stocks": {}}
        for code, s in scores.items():
            snapshot["stocks"][code] = {
                "name": s.get("name"), "price": s.get("price") or s.get("technicals",{}).get("price"),
                "signal": s.get("signal"), "total": s.get("total"), "factors": s.get("factors"),
                "audit_action": (audit_data.get(code) or {}).get("action"),
                "audit_total": (audit_data.get(code) or {}).get("total"),
            }
            if seven_dim and code in seven_dim:
                sd = seven_dim[code]
                snapshot["stocks"][code]["seven_dim"] = {"dimensions": sd.get("dimensions"), "total": sd.get("total"), "signal": sd.get("signal")}
        path = os.path.join(BACKTEST_DIR, f"snapshot_{date_str}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"save_snapshot failed: {e}")

def evaluate(horizon_days=20):
    try:
        files = sorted(os.listdir(BACKTEST_DIR))
        if len(files) < 2: return {"status": "insufficient_data"}
        with open(os.path.join(BACKTEST_DIR, files[0]), encoding="utf-8") as f: old_snap = json.load(f)
        with open(os.path.join(BACKTEST_DIR, files[-1]), encoding="utf-8") as f: new_snap = json.load(f)
        results = []
        for code, old in old_snap.get("stocks",{}).items():
            new = new_snap.get("stocks",{}).get(code)
            if not new: continue
            old_price, new_price = old.get("price"), new.get("price")
            if not old_price or not new_price: continue
            actual_return = (new_price / old_price - 1) * 100
            predicted_signal = old.get("signal","")
            is_correct = (predicted_signal in ("BUY","WATCH") and actual_return > 0) or (predicted_signal == "WAIT" and actual_return < -2)
            results.append({"code":code,"name":old.get("name"),"predicted_signal":predicted_signal,"predicted_score":old.get("total",0),"old_price":old_price,"new_price":new_price,"actual_return":round(actual_return,2),"is_correct":is_correct})
        if not results: return {"status":"no_comparable_data"}
        correct = sum(1 for r in results if r["is_correct"])
        buy = [r for r in results if r["predicted_signal"] in ("BUY","WATCH")]
        wait = [r for r in results if r["predicted_signal"] == "WAIT"]
        buy_avg = sum(r["actual_return"] for r in buy) / len(buy) if buy else 0
        wait_avg = sum(r["actual_return"] for r in wait) / len(wait) if wait else 0
        return {"status":"ok","period":f"{old_snap.get('date')} -> {new_snap.get('date')}","total_signals":len(results),"correct":correct,"win_rate":round(correct/len(results),3),"buy_avg_return":round(buy_avg,2),"wait_avg_return":round(wait_avg,2),"factor_discrimination":round(buy_avg-wait_avg,2)}
    except Exception as e:
        return {"status":"error","message":str(e)}

def evaluate_from_db():
    try:
        v = db.query("SELECT COUNT(*) as total, SUM(was_direction_correct) as correct, SUM(within_range) as in_range FROM daily_forecast WHERE verified_at IS NOT NULL")
        if not v or v[0]["total"] == 0: return {"status":"no_verified_data"}
        r = v[0]; t = r["total"] or 0; c = r["correct"] or 0; ir = r["in_range"] or 0
        by_dir = db.query("SELECT predicted_direction, COUNT(*) as cnt, SUM(was_direction_correct) as correct FROM daily_forecast WHERE verified_at IS NOT NULL GROUP BY predicted_direction")
        ds = {}
        for row in by_dir:
            d=row["predicted_direction"]; cnt=row["cnt"]; cor=row["correct"] or 0
            ds[d] = {"count":cnt,"accuracy":round(cor/cnt,3) if cnt>0 else 0}
        return {"status":"ok","source":"daily_forecast","total_forecasts":t,"direction_accuracy":round(c/t,3) if t>0 else 0,"range_accuracy":round(ir/t,3) if t>0 else 0,"by_direction":ds}
    except Exception as e:
        return {"status":"error","message":str(e)}

def factor_snapshot_from_db(code):
    rows = db.query("SELECT trade_date,ma5,ma10,ma20,adx,rsi14,ret_20d,vol_ratio,close,fwd_1d,fwd_5d,fwd_20d FROM factor_backtest_data WHERE ts_code=? ORDER BY trade_date DESC LIMIT 120", (code,))
    return [dict(r) for r in rows]
