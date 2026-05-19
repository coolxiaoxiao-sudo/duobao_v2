"""买卖临界点精算模块 — 多周期共振+支撑压力+量能异动+精准点位

核心理念：
- 买点：多周期共振向上 + 关键支撑 + 放量确认
- 卖点：多周期共振向下 + 关键压力 + 量能衰竭
- 每个点位附带确定度评级和逻辑链
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("critical_point")

CP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "critical_points")
os.makedirs(CP_DIR, exist_ok=True)


def _load_period_data(code: str, periods: list) -> dict:
    """加载多周期数据"""
    result = {}
    for p in periods:
        rows = db.query(
            "SELECT close,high,low,vol FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT ?",
            (code, p))
        if rows and len(rows) >= p:
            closes = [r["close"] for r in rows]
            highs = [r["high"] for r in rows]
            lows = [r["low"] for r in rows]
            vols = [r["vol"] for r in rows]
            result[p] = {
                "close": closes[0],
                "ma5": np.mean(closes[:5]) if len(closes) >= 5 else closes[0],
                "ma10": np.mean(closes[:10]) if len(closes) >= 10 else closes[0],
                "ma20": np.mean(closes[:20]) if len(closes) >= 20 else closes[0],
                "ma60": np.mean(closes[:60]) if len(closes) >= 60 else closes[0],
                "high_max": max(highs), "low_min": min(lows),
                "vol_avg": np.mean(vols),
            }
    return result


def find_support_resistance(code: str) -> dict:
    """找关键支撑压力位"""
    try:
        from layer3_analysis.technical import compute
        tech = compute(code)
    except:
        return {"supports": [], "resistances": [], "key_level": 0}

    price = tech.get("price", 0)
    supports = []
    resistances = []

    # MA作为支撑/压力
    ma20 = tech.get("ma20", price)
    ma60 = None
    try:
        rows = db.query(
            "SELECT close FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 60",
            (code,))
        if rows and len(rows) >= 60:
            ma60 = np.mean([r["close"] for r in rows])
    except:
        pass

    if ma20 and ma20 < price:
        supports.append({"level": round(ma20, 2), "type": "MA20支撑"})
    elif ma20 and ma20 > price:
        resistances.append({"level": round(ma20, 2), "type": "MA20压力"})

    if ma60 and ma60 < price:
        supports.append({"level": round(ma60, 2), "type": "MA60强支撑"})
    elif ma60 and ma60 > price:
        resistances.append({"level": round(ma60, 2), "type": "MA60强压力"})

    # 布林带
    bb_lower = tech.get("bb_lower", 0)
    bb_upper = tech.get("bb_upper", 0)
    if bb_lower and bb_lower < price:
        supports.append({"level": bb_lower, "type": "布林下轨"})
    if bb_upper and bb_upper > price:
        resistances.append({"level": bb_upper, "type": "布林上轨"})

    # 整数关口
    round_levels = [round(price, -1), round(price, -1) + 10, round(price, -1) - 10]
    for lv in round_levels:
        if lv < price and lv not in [s["level"] for s in supports]:
            supports.append({"level": lv, "type": "整数支撑"})
        elif lv > price and lv not in [r["level"] for r in resistances]:
            resistances.append({"level": lv, "type": "整数压力"})

    # 去重排序
    supports = sorted([dict(t) for t in {tuple(d.items()) for d in supports}],
                      key=lambda x: x["level"], reverse=True)[:3]
    resistances = sorted([dict(t) for t in {tuple(d.items()) for d in resistances}],
                         key=lambda x: x["level"])[:3]

    return {
        "current_price": price,
        "supports": supports,
        "resistances": resistances,
        "key_support": supports[0] if supports else None,
        "key_resistance": resistances[0] if resistances else None,
    }


def multi_period_resonance(code: str) -> dict:
    """多周期共振分析"""
    try:
        from layer3_analysis.technical import compute
        from layer3_analysis.trend import compute_all as trend_compute
        tech = compute(code)
        tr = trend_compute(code, 60)
    except:
        return {"resonance": "UNKNOWN", "confidence": 0}

    price = tech.get("price", 0)
    ma5 = tech.get("ma5", price)
    ma10 = tech.get("ma10", price)
    ma20 = tech.get("ma20", price)
    rsi = tech.get("rsi14", 50)
    trend = tr.get("trend_total", 5)
    ma_status = tr.get("ma_status", "unknown")

    # 多周期判断
    signals_up = 0
    signals_down = 0

    # 日线级别
    if price > ma5: signals_up += 1
    else: signals_down += 1
    if price > ma10: signals_up += 1
    else: signals_down += 1
    if price > ma20: signals_up += 1
    else: signals_down += 1

    # 趋势方向
    if trend >= 7: signals_up += 2
    elif trend >= 5: signals_up += 1
    elif trend <= 3: signals_down += 2
    else: signals_down += 1

    # RSI
    if rsi > 60: signals_up += 1
    elif rsi < 40: signals_down += 1

    total = signals_up + signals_down
    up_ratio = signals_up / total if total > 0 else 0.5

    if up_ratio >= 0.75:
        resonance = "多周期共振向上"
        confidence = up_ratio
        signal = "STRONG_BUY"
    elif up_ratio >= 0.6:
        resonance = "偏多但未共振"
        confidence = up_ratio
        signal = "WEAK_BUY"
    elif up_ratio <= 0.25:
        resonance = "多周期共振向下"
        confidence = 1 - up_ratio
        signal = "STRONG_SELL"
    elif up_ratio <= 0.4:
        resonance = "偏空但未共振"
        confidence = 1 - up_ratio
        signal = "WEAK_SELL"
    else:
        resonance = "多周期分歧"
        confidence = 0.5
        signal = "HOLD"

    return {
        "resonance": resonance, "confidence": round(confidence, 2),
        "signal": signal, "up_signals": signals_up, "down_signals": signals_down,
        "ma_status": ma_status, "trend_score": trend,
    }


def volume_anomaly(code: str) -> dict:
    """量能异动检测"""
    try:
        from layer3_analysis.technical import compute
        tech = compute(code)
    except:
        return {"anomaly": "NONE", "confidence": 0}

    vol_ratio = tech.get("vol_ratio", 1)
    rsi = tech.get("rsi14", 50)

    if vol_ratio > 2.0:
        return {"anomaly": "巨量异动", "vol_ratio": vol_ratio,
                "signal": "主力进出信号", "confidence": 0.7,
                "risk": "可能是出货/吸筹极端行为"}
    elif vol_ratio > 1.5:
        return {"anomaly": "放量", "vol_ratio": vol_ratio,
                "signal": "资金积极", "confidence": 0.55,
                "risk": "关注能否持续"}
    elif vol_ratio < 0.4:
        return {"anomaly": "地量", "vol_ratio": vol_ratio,
                "signal": "交投清淡，底部信号", "confidence": 0.5,
                "risk": "地量后可能变盘"}
    else:
        return {"anomaly": "NONE", "vol_ratio": vol_ratio,
                "signal": "量能正常", "confidence": 0.3}


def compute_entry_points(code: str, name: str) -> dict:
    """计算精准买卖点"""
    sr = find_support_resistance(code)
    resonance = multi_period_resonance(code)
    volume = volume_anomaly(code)

    price = sr.get("current_price", 0)
    supports = sr.get("supports", [])
    resistances = sr.get("resistances", [])

    # 买入临界点
    if supports:
        best_entry = supports[0]["level"]
        entry_zone = (round(best_entry * 0.98, 2), round(best_entry * 1.02, 2))
    else:
        best_entry = price * 0.95
        entry_zone = (round(price * 0.93, 2), round(price * 0.97, 2))

    # 止盈位
    if resistances:
        tp1 = resistances[0]["level"]  # 第一止盈
        tp2 = resistances[1]["level"] if len(resistances) > 1 else round(tp1 * 1.05, 2)
    else:
        tp1 = round(price * 1.1, 2)
        tp2 = round(price * 1.2, 2)

    # 减仓位（提前于止盈）
    reduce_point = round(tp1 * 0.95, 2)

    # 止损位
    key_support = sr.get("key_support", {})
    stop_loss = key_support.get("level", round(price * 0.92, 2)) if key_support else round(price * 0.92, 2)

    # 综合信号强度
    signals = []
    if resonance.get("signal") == "STRONG_BUY":
        signals.append("多周期共振买入")
    elif resonance.get("signal") == "WEAK_BUY":
        signals.append("偏多信号")
    elif resonance.get("signal") == "STRONG_SELL":
        signals.append("多周期共振卖出")
    elif resonance.get("signal") == "WEAK_SELL":
        signals.append("偏空信号")

    if volume.get("anomaly") != "NONE":
        signals.append(f"量能{volume.get('anomaly')}")

    return {
        "code": code, "name": name, "current_price": price,
        "entry_point": best_entry, "entry_zone": entry_zone,
        "take_profit_1": tp1, "take_profit_2": tp2,
        "reduce_point": reduce_point, "stop_loss": stop_loss,
        "supports": supports, "resistances": resistances,
        "resonance": resonance, "volume_anomaly": volume,
        "signals": signals,
    }


def batch_compute_all() -> dict:
    """全持仓买卖点计算"""
    results = {}
    for s in config.stocks:
        try:
            results[s["code"]] = compute_entry_points(s["code"], s["name"])
        except Exception as e:
            results[s["code"]] = {"error": str(e), "name": s["name"]}

    cp_file = os.path.join(CP_DIR, f"points_{datetime.now().strftime('%Y%m%d')}.json")
    with open(cp_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results
