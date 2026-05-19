"""估值动态锚定系统 — 结合行业景气度、市场情绪、整体水位动态调整估值区间

摒弃固定PE/PB标准，根据：
  1. 行业景气度（周期位置）
  2. 市场情绪水位（贪婪/恐慌）
  3. 市场整体估值（全市场PE中位数）
动态计算个股的低估/合理/高估三档估值
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, Optional

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("dynamic_valuation")

VAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "valuation")
os.makedirs(VAL_DIR, exist_ok=True)


# 行业景气度系数（周期位置）
INDUSTRY_CYCLE = {
    "计算机": 1.2, "电子": 1.15, "医药生物": 1.1,  # 成长型，给高估值
    "电力": 0.9, "传媒": 0.95, "汽车": 1.0,       # 稳定型
    "有色金属": 0.8, "电力设备": 1.05,              # 周期型
}


def get_market_sentiment_factor() -> float:
    """市场情绪系数 0.7-1.3"""
    try:
        from layer1_data.tencent_api import get_indices
        indices = get_indices()
        pcts = [d.get("pct_chg", 0) or 0 for d in indices.values() if isinstance(d, dict)]
        avg_pct = np.mean(pcts) if pcts else 0
        # 情绪高涨时估值容忍度高
        return 1.0 + avg_pct * 0.1  # -0.3 to +0.3
    except:
        return 1.0


def get_market_valuation_level() -> float:
    """市场整体估值水位 0.8-1.2"""
    try:
        # 简化：用创业板指PE作为代理
        rows = db.query(
            "SELECT close FROM stock_daily WHERE ts_code='sz399006' ORDER BY trade_date DESC LIMIT 60")
        if not rows:
            return 1.0
        # 假设创业板PE与价格正相关（简化）
        current = rows[0]["close"]
        ma60 = np.mean([r["close"] for r in rows])
        return current / ma60 if ma60 > 0 else 1.0
    except:
        return 1.0


def analyze_valuation(code: str, name: str = "", industry: str = "") -> dict:
    """动态估值分析"""
    try:
        from layer1_data.tencent_api import get_quote
        q = get_quote(code)
        pe = q.get("pe", 0) or 0
        pb = q.get("pb", 0) or 0
        price = q.get("price", 0) or 0
    except:
        return {"error": "无法获取估值数据", "code": code, "name": name}

    if pe <= 0:
        return {"code": code, "name": name, "status": "亏损股", "pe": pe, "pb": pb}

    # 基础估值区间
    base_pe_low, base_pe_mid, base_pe_high = 15, 25, 40

    # 行业景气度调整
    ind_factor = INDUSTRY_CYCLE.get(industry, 1.0)

    # 市场情绪调整
    sent_factor = get_market_sentiment_factor()

    # 市场整体估值调整
    mkt_factor = get_market_valuation_level()

    # 综合调整系数
    adjust = ind_factor * sent_factor * mkt_factor
    adjust = max(0.6, min(1.5, adjust))  # 限制范围

    # 动态估值区间
    pe_undervalued = base_pe_low * adjust
    pe_fair = base_pe_mid * adjust
    pe_overvalued = base_pe_high * adjust

    # 当前位置判断
    if pe < pe_undervalued:
        status = "低估洼地"
        upside = (pe_fair / pe - 1) * 100
        advice = f"估值低于合理区间{upside:.0f}%，价值修复空间大"
    elif pe < pe_fair:
        status = "合理偏低"
        upside = (pe_fair / pe - 1) * 100
        advice = f"估值合理，仍有{upside:.0f}%修复空间"
    elif pe < pe_overvalued:
        status = "合理偏高"
        downside = (1 - pe_fair / pe) * 100
        advice = f"估值偏高，注意{downside:.0f}%回调风险"
    else:
        status = "高估泡沫"
        downside = (1 - pe_fair / pe) * 100
        advice = f"严重高估，泡沫风险{downside:.0f}%，建议减仓"

    return {
        "code": code, "name": name, "industry": industry,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "price": price, "pe": pe, "pb": pb,
        "adjust_factors": {
            "industry": ind_factor,
            "sentiment": round(sent_factor, 2),
            "market_level": round(mkt_factor, 2),
            "total": round(adjust, 2),
        },
        "valuation_zones": {
            "undervalued": round(pe_undervalued, 1),
            "fair": round(pe_fair, 1),
            "overvalued": round(pe_overvalued, 1),
        },
        "status": status, "advice": advice,
    }


def batch_valuation() -> dict:
    """全持仓动态估值"""
    results = {}
    zones = {"低估洼地": [], "合理偏低": [], "合理偏高": [], "高估泡沫": [], "亏损股": []}

    for s in config.stocks:
        try:
            r = analyze_valuation(s["code"], s["name"], s.get("industry", ""))
            results[s["code"]] = r
            st = r.get("status", "?")
            if st in zones:
                zones[st].append({"code": s["code"], "name": s["name"], "pe": r.get("pe", 0)})
        except Exception as e:
            results[s["code"]] = {"error": str(e), "name": s["name"]}

    f = os.path.join(VAL_DIR, f"val_{datetime.now().strftime('%Y%m%d')}.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "zones": {k: len(v) for k, v in zones.items()},
        "details": zones,
        "full_results": results,
    }
