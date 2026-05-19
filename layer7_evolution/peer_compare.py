"""同行业横向对比 — 只选板块内强势领涨核心标的

对比维度：
  1. 业绩增速（营收/利润增长）
  2. 盈利能力（ROE/毛利率）
  3. 资金认可度（趋势强度/相对强度）
  4. 走势强度（涨幅/波动率）

输出：板块内排名，只关注前30%强势标的
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("peer_compare")

PEER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "peer")
os.makedirs(PEER_DIR, exist_ok=True)


def get_stock_metrics(code: str, name: str) -> dict:
    """获取个股核心指标"""
    try:
        from layer3_analysis.technical import compute
        from layer3_analysis.trend import compute_all as trend_compute
        tech = compute(code)
        tr = trend_compute(code, 60)

        # 走势强度（近20日涨幅）
        rows = db.query(
            "SELECT close FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 20",
            (code,))
        if len(rows) >= 20:
            returns_20d = (rows[0]["close"] / rows[-1]["close"] - 1) * 100
        else:
            returns_20d = 0

        return {
            "code": code, "name": name,
            "trend_score": tr.get("trend_total", 5),
            "rel_strength": tr.get("rel_strength", 50),
            "rsi": tech.get("rsi14", 50),
            "vol_ratio": tech.get("vol_ratio", 1),
            "returns_20d": round(returns_20d, 1),
            "price": tech.get("price", 0),
        }
    except:
        return {"code": code, "name": name, "error": "数据不足"}


def compare_peers(industry: str) -> dict:
    """同行业对比"""
    peers = [s for s in config.stocks if s.get("industry") == industry]
    if len(peers) < 2:
        return {"error": f"{industry}行业持仓不足2只，无法对比", "industry": industry}

    # 获取所有指标
    metrics = []
    for s in peers:
        m = get_stock_metrics(s["code"], s["name"])
        if "error" not in m:
            metrics.append(m)

    if not metrics:
        return {"error": "数据不足", "industry": industry}

    # 计算综合得分
    for m in metrics:
        # 趋势30% + 相对强度25% + 20日涨幅25% + RSI20%
        score = (m["trend_score"] / 10 * 30 +
                 m["rel_strength"] / 100 * 25 +
                 max(-10, min(20, m["returns_20d"])) / 20 * 25 +
                 (m["rsi"] - 30) / 40 * 20)
        m["composite_score"] = round(score, 1)

    # 排序
    ranked = sorted(metrics, key=lambda x: x["composite_score"], reverse=True)

    # 分档
    n = len(ranked)
    leaders = ranked[:max(1, n//3)]      # 前1/3：龙头
    followers = ranked[max(1, n//3):max(1, n*2//3)]  # 中1/3：跟随
    laggards = ranked[max(1, n*2//3):]   # 后1/3：落后

    return {
        "industry": industry,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total": n,
        "leaders": [{"code": r["code"], "name": r["name"], "score": r["composite_score"],
                     "20d_return": r["returns_20d"]} for r in leaders],
        "followers": [{"code": r["code"], "name": r["name"], "score": r["composite_score"]} for r in followers],
        "laggards": [{"code": r["code"], "name": r["name"], "score": r["composite_score"]} for r in laggards],
        "recommendation": f"优先关注龙头：{', '.join(r['name'] for r in leaders)}",
    }


def batch_peer_compare() -> dict:
    """全持仓行业对比"""
    # 按行业分组
    industries = {}
    for s in config.stocks:
        ind = s.get("industry", "其他")
        if ind not in industries:
            industries[ind] = []
        industries[ind].append(s)

    results = {}
    for ind, stocks in industries.items():
        if len(stocks) >= 2:
            results[ind] = compare_peers(ind)
        else:
            results[ind] = {"error": f"仅{len(stocks)}只，无法对比", "stocks": [s["name"] for s in stocks]}

    f = os.path.join(PEER_DIR, f"peer_{datetime.now().strftime('%Y%m%d')}.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)

    return {"date": datetime.now().strftime("%Y-%m-%d"), "industries": results}
