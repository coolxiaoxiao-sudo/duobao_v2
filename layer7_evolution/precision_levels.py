"""多层精准测算 — 前期高低点/黄金分割/筹码峰/均线/多层点位细分

输出点位：
  首次试仓点（轻仓试探）
  重仓加仓点（确认突破）
  止损防守点（严格风控）
  分批止盈点（1/2/3级）
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("precision_levels")

PRECISION_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "precision")
os.makedirs(PRECISION_DIR, exist_ok=True)


def fibonacci_levels(high: float, low: float) -> dict:
    """黄金分割位"""
    diff = high - low
    return {
        "0.0": high,
        "0.236": round(high - diff * 0.236, 2),
        "0.382": round(high - diff * 0.382, 2),
        "0.5": round(high - diff * 0.5, 2),
        "0.618": round(high - diff * 0.618, 2),
        "1.0": low,
    }


def calculate_precision_levels(code: str, name: str = "") -> dict:
    """计算多层精准点位"""
    rows = db.query(
        "SELECT trade_date,high,low,close,vol FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 120",
        (code,))
    if len(rows) < 60:
        return {"error": "数据不足", "code": code, "name": name}

    highs = [r["high"] for r in rows][::-1]
    lows = [r["low"] for r in rows][::-1]
    closes = [r["close"] for r in rows][::-1]
    vols = [r["vol"] for r in rows][::-1]
    price = closes[-1]

    # 1. 前期高低点
    recent_high = max(highs[-60:])  # 近60日高点
    recent_low = min(lows[-60:])    # 近60日低点

    # 2. 黄金分割
    fib = fibonacci_levels(recent_high, recent_low)

    # 3. 筹码密集峰（成交量加权平均价格）
    vwaps = []
    for i in range(len(closes) - 20):
        w_sum = sum(c * v for c, v in zip(closes[i:i+20], vols[i:i+20]))
        v_sum = sum(vols[i:i+20])
        if v_sum > 0:
            vwaps.append(w_sum / v_sum)
    chip_peak = np.median(vwaps) if vwaps else price

    # 4. 均线支撑压力
    ma5 = np.mean(closes[-5:])
    ma10 = np.mean(closes[-10:])
    ma20 = np.mean(closes[-20:])
    ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else ma20

    # 5. 布林带
    std20 = np.std(closes[-20:])
    bb_upper = ma20 + 2 * std20
    bb_lower = ma20 - 2 * std20

    # === 点位细分 ===

    # 支撑位（取最大3个）
    supports = sorted([
        ("近期低点", recent_low),
        ("黄金分割0.618", fib["0.618"]),
        ("筹码峰", chip_peak),
        ("MA60", ma60),
        ("MA20", ma20),
        ("布林下轨", bb_lower),
    ], key=lambda x: x[1], reverse=True)[:3]

    # 压力位
    resistances = sorted([
        ("近期高点", recent_high),
        ("黄金分割0.382", fib["0.382"]),
        ("MA5", ma5),
        ("布林上轨", bb_upper),
    ], key=lambda x: x[1])[:3]

    # 首次试仓点（最接近当前价的支撑）
    entry_probe = max([s[1] for s in supports if s[1] < price], default=price * 0.95)

    # 重仓加仓点（突破MA20或筹码峰）
    entry_heavy = max(ma20, chip_peak) * 1.02

    # 止损防守点（近期低点下方3%）
    stop_loss = recent_low * 0.97

    # 分批止盈点
    tp1 = min([r[1] for r in resistances if r[1] > price], default=price * 1.1)
    tp2 = recent_high * 0.98
    tp3 = recent_high * 1.05

    # 减仓点（跌破MA10）
    reduce_point = ma10 * 0.98

    return {
        "code": code, "name": name, "price": price,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "key_levels": {
            "recent_high": recent_high, "recent_low": recent_low,
            "fibonacci": fib, "chip_peak": round(chip_peak, 2),
            "ma5": round(ma5, 2), "ma10": round(ma10, 2),
            "ma20": round(ma20, 2), "ma60": round(ma60, 2),
            "bb_upper": round(bb_upper, 2), "bb_lower": round(bb_lower, 2),
        },
        "trade_levels": {
            "entry_probe": round(entry_probe, 2),      # 首次试仓
            "entry_heavy": round(entry_heavy, 2),      # 重仓加仓
            "stop_loss": round(stop_loss, 2),          # 止损
            "reduce_point": round(reduce_point, 2),    # 减仓
            "take_profit_1": round(tp1, 2),            # 一级止盈
            "take_profit_2": round(tp2, 2),            # 二级止盈
            "take_profit_3": round(tp3, 2),            # 三级止盈
        },
        "supports": supports,
        "resistances": resistances,
    }


def batch_precision_levels() -> dict:
    """全持仓精准点位"""
    results = {}
    for s in config.stocks:
        try:
            results[s["code"]] = calculate_precision_levels(s["code"], s["name"])
        except Exception as e:
            results[s["code"]] = {"error": str(e), "name": s["name"]}

    f = os.path.join(PRECISION_DIR, f"precision_{datetime.now().strftime('%Y%m%d')}.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)

    return {"date": datetime.now().strftime("%Y-%m-%d"), "results": results}
