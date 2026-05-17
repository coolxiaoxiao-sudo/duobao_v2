"""L3 技术面 — 六因子均值回归评分 (0-10制) + 趋势双重确认"""
import numpy as np, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import db
from core.config import config
from core.logging import get_logger
logger = get_logger("technical")

def load_kline(code, n=60):
    return db.query("SELECT trade_date,open,high,low,close,vol,pct_chg FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT ?", (code, n))

def _rsi(closes, p=14):
    if len(closes) < p + 1: return 50
    g = l = 0
    for i in range(p):
        d = closes[i] - closes[i + 1]
        if d > 0: g += d
        else: l -= d
    if l == 0: return 100
    return round(100 - 100 / (1 + g / l), 1)

def _atr(highs, lows, closes, p=14):
    if len(closes) < p + 1: return 0
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i + 1]), abs(lows[i] - closes[i + 1])) for i in range(len(closes) - 1)]
    return float(np.mean(trs[:p]))

def _bollinger(closes, p=20):
    if len(closes) < p: return (closes[0], closes[0], closes[0])
    mid = np.mean(closes[:p])
    std = np.std(closes[:p], ddof=1)
    return (mid, mid + 2 * std, mid - 2 * std)

def _consec(pct_chgs):
    days = cum = 0
    for chg in pct_chgs:
        if chg is None: break
        if days == 0: days = 1 if chg > 0 else (-1 if chg < 0 else 0); cum = chg
        elif (days > 0 and chg > 0) or (days < 0 and chg < 0): days += 1 if days > 0 else -1; cum += chg
        else: break
    return {"days": days, "cum": cum}

def compute(code):
    rows = load_kline(code, 60)
    if len(rows) < 10: return {"error": "数据不足(<10行)"}
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]; lows = [r["low"] for r in rows]
    pct_chgs = [r["pct_chg"] for r in rows]; vols = [r["vol"] for r in rows]
    price = closes[0]
    ma5 = np.mean(closes[:5]) if len(closes) >= 5 else price
    ma10 = np.mean(closes[:10]) if len(closes) >= 10 else price
    ma20 = np.mean(closes[:20]) if len(closes) >= 20 else price
    rsi14 = _rsi(closes, 14)
    atr14 = _atr(highs, lows, closes, 14)
    cons = _consec(pct_chgs)
    vol5 = np.mean(vols[1:6]) if len(vols) >= 6 else vols[0]
    bb_mid, bb_upper, bb_lower = _bollinger(closes, 20)
    bb_range = bb_upper - bb_lower
    support = (price - bb_lower) / bb_range if bb_range > 0 else 0.5
    return {"price": price, "ma5": ma5, "ma10": ma10, "ma20": ma20, "rsi14": rsi14,
        "pct_ma10": round((price / ma10 - 1) * 100, 2) if ma10 else 0,
        "pct_ma20": round((price / ma20 - 1) * 100, 2) if ma20 else 0,
        "atr14": round(atr14, 2), "atr_pct": round(atr14 / price * 100, 2) if price else 0,
        "vol_ratio": round(vols[0] / vol5, 2) if vol5 else 1,
        "cons_days": cons["days"], "cons_cum": round(cons["cum"], 2),
        "points": len(rows),
        "bb_lower": round(bb_lower, 2), "bb_upper": round(bb_upper, 2),
        "bb_support": round(support, 3)}

def score(techs, weights=None):
    """六因子评分 → 0-10 制
    BUY≥5.5  WATCH≥4  HOLD≥2.5  AVOID<2.5"""
    if weights is None: weights = config.weights
    f = {}
    drop = abs(techs.get("pct_ma20", 0))
    f["回撤深度"] = min(drop / 10, 1.0)
    rsi = techs.get("rsi14", 50)
    f["超卖强度"] = max(0, min(1, (50 - rsi) / 30))
    cons = techs.get("cons_days", 0)
    f["连跌衰竭"] = min(abs(cons) / 5, 1.0) if cons < 0 else 0
    vr = techs.get("vol_ratio", 1)
    f["量价背离"] = max(0, min(1, 1 - vr / 2)) if cons < 0 else 0.3
    atr_pct = techs.get("atr_pct", 5)
    f["波动收敛"] = max(0, min(1, 1 - atr_pct / 10))
    bb_support = techs.get("bb_support", 0.5)
    f["支撑强度"] = max(0, min(1, 1 - bb_support))
    raw = sum(f.get(k, 0) * weights.get(k, 0) for k in weights)
    total_10 = round(raw * 10, 1)
    th = config.signal_thresholds
    if total_10 >= th.get("buy", 5.5): sig = "BUY"
    elif total_10 >= th.get("watch", 4): sig = "WATCH"
    elif total_10 >= th.get("hold", 2.5): sig = "HOLD"
    else: sig = "AVOID"
    return {"scores": {k: round(v, 3) for k, v in f.items()}, "total": total_10, "signal": sig}


def score_with_trend(techs, trend_data=None, weights=None):
    """六因子 + 趋势双重确认
    - 趋势因子≥7 且 六因子≥4 → 升级为BUY（趋势+均值双重确认）
    - 趋势因子<4 且 六因子≥6 → 降级为WATCH（可能是下跌反弹陷阱）
    - 否则维持六因子信号"""
    base = score(techs, weights)
    sig = base["signal"]
    if trend_data is None:
        return base
    trend_total = trend_data.get("trend_total", 5)
    if trend_total >= 7 and base["total"] >= 4:
        sig = "BUY"
    elif trend_total < 4 and base["total"] >= 6:
        sig = "WATCH"
    base["signal"] = sig
    base["trend_cross"] = trend_total
    return base


def score_all():
    from layer3_analysis.trend import compute_all as trend_compute
    r = {}
    for s in config.stocks:
        c = s["code"]
        t = compute(c)
        if "error" in t: r[c] = {**s, "error": t["error"]}; continue
        tr = trend_compute(c, 60)
        sc = score_with_trend(t, tr)
        r[c] = {**s, "technicals": t, "factors": sc["scores"], "total": sc["total"],
                "signal": sc["signal"], "trend_cross": sc.get("trend_cross")}
    return dict(sorted(r.items(), key=lambda x: x[1].get("total", 0), reverse=True))
