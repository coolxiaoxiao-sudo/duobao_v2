"""跨周期联动研判体系 — 日线/周线/月线/60分钟/15分钟多级周期共振

核心理念：
  大周期定方向（月线/周线）
  中周期定结构（日线）
  小周期抓拐点（60分/15分）
  杜绝大趋势相悖下盲目短线操作
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("cross_cycle")

CYCLE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cycles")
os.makedirs(CYCLE_DIR, exist_ok=True)


def analyze_cycle(code: str, period: str, n: int) -> dict:
    """分析单个周期"""
    rows = db.query(
        "SELECT trade_date,open,high,low,close,vol FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT ?",
        (code, n))
    if len(rows) < 20:
        return {"error": f"数据不足({len(rows)}行)"}

    closes = [r["close"] for r in rows][::-1]
    highs = [r["high"] for r in rows][::-1]
    lows = [r["low"] for r in rows][::-1]
    price = closes[-1]

    # MA
    ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else price
    ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else price
    ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else price
    ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else None

    # 趋势方向
    if ma5 > ma10 > ma20 and (ma60 is None or ma20 > ma60):
        trend = "BULLISH"
        trend_score = 8
    elif ma5 < ma10 < ma20 and (ma60 is None or ma20 < ma60):
        trend = "BEARISH"
        trend_score = 2
    elif abs(ma5 / ma20 - 1) < 0.03:
        trend = "SIDEWAYS"
        trend_score = 5
    elif ma5 > ma20:
        trend = "BIAS_UP"
        trend_score = 6
    else:
        trend = "BIAS_DOWN"
        trend_score = 4

    # RSI
    def calc_rsi(data, p=14):
        if len(data) < p + 1: return 50
        gains = losses = 0
        for i in range(p):
            d = data[-i-1] - data[-i-2]
            if d > 0: gains += d
            else: losses -= d
        if losses == 0: return 100
        rs = gains / losses
        return 100 - 100 / (1 + rs)

    rsi = calc_rsi(closes)

    # MACD
    def calc_macd(data, fast=12, slow=26, sig=9):
        if len(data) < slow + sig: return 0, 0, 0
        ema_fast = [np.mean(data[:fast])]
        k_fast = 2 / (fast + 1)
        for v in data[fast:]:
            ema_fast.append(ema_fast[-1] * (1 - k_fast) + v * k_fast)
        ema_slow = [np.mean(data[:slow])]
        k_slow = 2 / (slow + 1)
        for v in data[slow:]:
            ema_slow.append(ema_slow[-1] * (1 - k_slow) + v * k_slow)
        dif = [f - s for f, s in zip(ema_fast[-len(ema_slow):], ema_slow)]
        dea = [np.mean(dif[:sig])]
        k_sig = 2 / (sig + 1)
        for v in dif[sig:]:
            dea.append(dea[-1] * (1 - k_sig) + v * k_sig)
        return dif[-1], dea[-1], dif[-1] - dea[-1]

    dif, dea, hist = calc_macd(closes)

    return {
        "period": period, "price": price,
        "ma5": round(ma5, 2), "ma10": round(ma10, 2), "ma20": round(ma20, 2),
        "ma60": round(ma60, 2) if ma60 else None,
        "trend": trend, "trend_score": trend_score,
        "rsi": round(rsi, 1),
        "macd": {"dif": round(dif, 3), "dea": round(dea, 3), "hist": round(hist, 3)},
    }


def cross_cycle_analysis(code: str, name: str = "") -> dict:
    """跨周期联动分析"""
    # 各周期数据
    monthly = analyze_cycle(code, "月线", 60)   # ~5年
    weekly = analyze_cycle(code, "周线", 120)   # ~2年
    daily = analyze_cycle(code, "日线", 60)     # ~3月
    h60 = analyze_cycle(code, "60分钟", 60)     # ~15天
    m15 = analyze_cycle(code, "15分钟", 60)     # ~4天

    cycles = {"月线": monthly, "周线": weekly, "日线": daily, "60分钟": h60, "15分钟": m15}

    # 大周期定方向
    big_trend = monthly.get("trend", "SIDEWAYS")
    big_score = monthly.get("trend_score", 5) * 0.4 + weekly.get("trend_score", 5) * 0.6

    # 中周期定结构
    mid_score = daily.get("trend_score", 5)

    # 小周期抓拐点
    small_score = h60.get("trend_score", 5) * 0.6 + m15.get("trend_score", 5) * 0.4

    # 周期一致性判断
    all_trends = [c.get("trend") for c in cycles.values() if "error" not in c]
    bullish_count = sum(1 for t in all_trends if t in ("BULLISH", "BIAS_UP"))
    bearish_count = sum(1 for t in all_trends if t in ("BEARISH", "BIAS_DOWN"))

    # 共振强度
    if bullish_count >= 4 and big_score >= 6:
        resonance = "STRONG_BULL"
        direction = "多周期共振向上"
        trade_action = "顺势做多，小周期回调即买点"
    elif bearish_count >= 4 and big_score <= 4:
        resonance = "STRONG_BEAR"
        direction = "多周期共振向下"
        trade_action = "顺势做空/观望，反弹即卖点"
    elif big_score >= 6 and mid_score <= 4:
        resonance = "BIG_UP_SMALL_DOWN"
        direction = "大周期向上，小周期调整"
        trade_action = "大方向看多，等小周期企稳再进场"
    elif big_score <= 4 and mid_score >= 6:
        resonance = "BIG_DOWN_SMALL_UP"
        direction = "大周期向下，小周期反弹"
        trade_action = "大趋势空头，小周期反弹是减仓机会"
    else:
        resonance = "MIXED"
        direction = "周期分歧，方向不明"
        trade_action = "观望等待，不做方向性押注"

    # 拐点信号（小周期背离）
    divergence = []
    if h60.get("rsi", 50) < 35 and daily.get("rsi", 50) > 40:
        divergence.append("60分钟超卖，日线未超卖，短期可能反弹")
    if m15.get("macd", {}).get("hist", 0) > 0 and h60.get("macd", {}).get("hist", 0) < 0:
        divergence.append("15分钟MACD金叉，60分钟未金叉，短期拐点")

    result = {
        "code": code, "name": name,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "cycles": cycles,
        "big_trend_score": round(big_score, 1),
        "mid_trend_score": mid_score,
        "small_trend_score": round(small_score, 1),
        "resonance": resonance,
        "direction": direction,
        "trade_action": trade_action,
        "divergence_signals": divergence,
        "consistency": f"看多周期{bullish_count}/5, 看空周期{bearish_count}/5",
    }

    # 保存
    f = os.path.join(CYCLE_DIR, f"cycle_{code.replace('.','_')}_{datetime.now().strftime('%Y%m%d')}.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    return result


def batch_cross_cycle() -> dict:
    """全持仓跨周期分析"""
    results = {}
    for s in config.stocks:
        try:
            results[s["code"]] = cross_cycle_analysis(s["code"], s["name"])
        except Exception as e:
            results[s["code"]] = {"error": str(e), "name": s["name"]}

    # 统计
    strong_bull = sum(1 for r in results.values() if r.get("resonance") == "STRONG_BULL")
    strong_bear = sum(1 for r in results.values() if r.get("resonance") == "STRONG_BEAR")
    mixed = sum(1 for r in results.values() if r.get("resonance") == "MIXED")

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "strong_bull": strong_bull, "strong_bear": strong_bear, "mixed": mixed,
        "details": results,
    }
