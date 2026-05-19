"""多层严筛模块 — 剔除暴雷/流动性差/高位透支标的

五层过滤：
  L1 流动性过滤 — 日均成交额 < 5000万 剔除
  L2 基本面过滤 — PE<0 或 PE>200 或 PB<0 剔除
  L3 高位透支过滤 — 价格距MA60涨幅>100% 且 RSI>80 剔除
  L4 暴雷风险过滤 — ST/退市风险 剔除
  L5 筹码结构过滤 — 换手率异常(>30%或<0.5%) 剔除
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("stock_screener")

SCREENER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "screener")
os.makedirs(SCREENER_DIR, exist_ok=True)


def _get_quote_data(code: str) -> dict:
    try:
        from layer1_data.tencent_api import get_quote
        return get_quote(code)
    except:
        return {}


def _get_amount(code: str) -> float:
    try:
        rows = db.query(
            "SELECT vol, close FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 5",
            (code,))
        if not rows:
            return 0
        return np.mean([r["vol"] * r["close"] / 1e8 for r in rows])
    except:
        return 0


def _get_ma60_pct(code: str) -> float:
    try:
        rows = db.query(
            "SELECT close FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 60",
            (code,))
        if not rows or len(rows) < 60:
            return 0
        closes = [r["close"] for r in rows]
        return (closes[0] / np.mean(closes) - 1) * 100
    except:
        return 0


def screen_stock(code: str, name: str, industry: str = "",
                 min_amount: float = 0.5, max_pe: float = 200,
                 max_ma60_pct: float = 100) -> dict:
    """单只股票五层严筛"""
    results = []
    passed = True

    # L1 流动性
    amount = _get_amount(code)
    if amount < min_amount:
        results.append({"layer": "L1流动性", "pass": False,
                        "reason": f"日均成交额{amount:.1f}亿 < {min_amount}亿"})
        passed = False
    else:
        results.append({"layer": "L1流动性", "pass": True,
                        "reason": f"日均成交额{amount:.1f}亿"})

    # L2 基本面
    q = _get_quote_data(code)
    pe = q.get("pe", 0) or 0
    pb = q.get("pb", 0) or 0
    if pe <= 0 or pe > max_pe:
        results.append({"layer": "L2基本面", "pass": False,
                        "reason": f"PE={pe}({'亏损' if pe<=0 else '高估'})"})
        passed = False
    elif pb <= 0:
        results.append({"layer": "L2基本面", "pass": False, "reason": f"PB={pb}异常"})
        passed = False
    else:
        results.append({"layer": "L2基本面", "pass": True,
                        "reason": f"PE={pe:.1f} PB={pb:.1f}"})

    # L3 高位透支
    ma60_pct = _get_ma60_pct(code)
    try:
        from layer3_analysis.technical import compute
        rsi = compute(code).get("rsi14", 50)
    except:
        rsi = 50

    if ma60_pct > max_ma60_pct and rsi > 80:
        results.append({"layer": "L3高位透支", "pass": False,
                        "reason": f"距MA60+{ma60_pct:.0f}% RSI={rsi}，严重透支"})
        passed = False
    elif ma60_pct > 60 and rsi > 75:
        results.append({"layer": "L3高位透支", "pass": True,
                        "reason": f"距MA60+{ma60_pct:.0f}% RSI={rsi}", "warning": "高位回调风险"})
    else:
        results.append({"layer": "L3高位透支", "pass": True,
                        "reason": f"距MA60+{ma60_pct:.0f}% RSI={rsi}"})

    # L4 暴雷风险
    is_st = "ST" in name.upper()
    if is_st:
        results.append({"layer": "L4暴雷风险", "pass": False,
                        "reason": "ST股，退市/债务风险极高"})
        passed = False
    else:
        results.append({"layer": "L4暴雷风险", "pass": True, "reason": "非ST"})

    # L5 筹码结构
    turnover = q.get("turnover_rate", 0) or 0
    if turnover > 30:
        results.append({"layer": "L5筹码结构", "pass": False,
                        "reason": f"换手{turnover:.1f}%异常高"})
        passed = False
    elif turnover < 0.5:
        results.append({"layer": "L5筹码结构", "pass": False,
                        "reason": f"换手{turnover:.1f}%极低"})
        passed = False
    else:
        results.append({"layer": "L5筹码结构", "pass": True,
                        "reason": f"换手{turnover:.1f}%"})

    pass_count = sum(1 for r in results if r["pass"])
    warnings = [r for r in results if r.get("warning")]

    return {
        "code": code, "name": name, "industry": industry,
        "passed": passed, "pass_count": f"{pass_count}/5",
        "layers": results, "warnings": warnings,
        "score": pass_count * 2 - len(warnings),
    }


def screen_portfolio() -> dict:
    """全持仓严筛"""
    results = {}
    elite_pool, watch_list, reject_list = [], [], []

    for s in config.stocks:
        r = screen_stock(s["code"], s["name"], s.get("industry", ""))
        results[s["code"]] = r
        if r["passed"] and not r["warnings"]:
            elite_pool.append(r)
        elif r["passed"]:
            watch_list.append(r)
        else:
            reject_list.append(r)

    summary = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total": len(config.stocks),
        "elite": len(elite_pool), "watch": len(watch_list), "reject": len(reject_list),
        "elite_pool": [{"code": r["code"], "name": r["name"], "score": r["score"]}
                       for r in sorted(elite_pool, key=lambda x: x["score"], reverse=True)],
        "watch_list": [{"code": r["code"], "name": r["name"], "warnings": r["warnings"]} for r in watch_list],
        "reject_list": [{"code": r["code"], "name": r["name"],
                         "failed_layers": [l["layer"] for l in r["layers"] if not l["pass"]]} for r in reject_list],
    }

    f = os.path.join(SCREENER_DIR, f"screen_{datetime.now().strftime('%Y%m%d')}.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump({**summary, "details": results}, fh, ensure_ascii=False, indent=2)

    return summary
