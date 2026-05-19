"""情绪量化打分机制 — 大盘/板块/个股三级情绪量化

四阶段划分：
  冰点（0-25）：极度悲观，恐慌盘涌出，布局良机
  回暖（26-50）：情绪修复，可逐步建仓
  亢奋（51-75）：乐观情绪，持股但警惕风险
  退潮（76-100）：极度乐观，随时见顶，减仓避险

严格根据情绪等级匹配仓位与交易手法
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("emotion_quant")

EMOTION_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "emotion")
os.makedirs(EMOTION_DIR, exist_ok=True)


def calc_emotion_score(pct_chg: float, vol_ratio: float, rsi: float,
                       up_ratio: float, ma_pos: float) -> float:
    """计算情绪分 0-100"""
    # 涨跌贡献 -20~+20
    price_score = pct_chg * 10
    price_score = max(-20, min(20, price_score))

    # 量能贡献 -15~+15
    vol_score = (vol_ratio - 1) * 15
    vol_score = max(-15, min(15, vol_score))

    # RSI贡献 0~25
    rsi_score = (rsi - 30) / 40 * 25
    rsi_score = max(0, min(25, rsi_score))

    # 涨跌家数比贡献 -10~+10
    breadth_score = (up_ratio - 0.5) * 20
    breadth_score = max(-10, min(10, breadth_score))

    # 均线位置贡献 -10~+10
    ma_score = (ma_pos - 1) * 20
    ma_score = max(-10, min(10, ma_score))

    base = 50 + price_score + vol_score + rsi_score + breadth_score + ma_score
    return max(0, min(100, base))


def get_emotion_stage(score: float) -> tuple:
    """情绪阶段 + 交易建议"""
    if score <= 25:
        return "冰点", "极度悲观，恐慌盘涌出，分批布局优质标的，仓位可逐步提升至7-8成"
    elif score <= 50:
        return "回暖", "情绪修复，可逐步建仓，仓位5-6成，优选强势板块"
    elif score <= 75:
        return "亢奋", "乐观情绪蔓延，持股但设移动止盈，仓位控制在5成以内"
    else:
        return "退潮", "极度乐观，随时见顶，大幅减仓至3成以下，现金为王"


def analyze_market_emotion() -> dict:
    """大盘情绪量化"""
    try:
        from layer1_data.tencent_api import get_indices
        indices = get_indices()
    except:
        return {"error": "无法获取指数数据"}

    pcts = [d.get("pct_chg", 0) or 0 for d in indices.values() if isinstance(d, dict)]
    vols = [d.get("volume_ratio", 1) or 1 for d in indices.values() if isinstance(d, dict)]

    avg_pct = np.mean(pcts) if pcts else 0
    avg_vol = np.mean(vols) if vols else 1

    # 涨跌家数比（简化：用指数涨跌代理）
    up_ratio = sum(1 for p in pcts if p > 0) / len(pcts) if pcts else 0.5

    # RSI和均线位置用上证指数代理
    sh_pct = indices.get("上证指数", {}).get("pct_chg", 0) or 0
    rsi = 50 + sh_pct * 5  # 简化估计
    ma_pos = 1 + sh_pct * 0.01  # 简化估计

    score = calc_emotion_score(avg_pct, avg_vol, rsi, up_ratio, ma_pos)
    stage, advice = get_emotion_stage(score)

    return {
        "level": "大盘", "score": round(score, 1), "stage": stage, "advice": advice,
        "components": {"price": round(avg_pct, 2), "volume": round(avg_vol, 2),
                       "breadth": round(up_ratio, 2)},
    }


def analyze_sector_emotion(industry: str) -> dict:
    """板块情绪量化"""
    # 获取该行业所有股票
    stocks = [s for s in config.stocks if s.get("industry") == industry]
    if not stocks:
        return {"error": "无该行业持仓"}

    scores = []
    for s in stocks:
        try:
            from layer3_analysis.technical import compute
            from layer3_analysis.trend import compute_all as trend_compute
            tech = compute(s["code"])
            tr = trend_compute(s["code"], 60)

            pct = tech.get("price", 0) / tech.get("ma20", tech.get("price", 1)) - 1
            vol = tech.get("vol_ratio", 1)
            rsi = tech.get("rsi14", 50)
            trend = tr.get("trend_total", 5)

            score = calc_emotion_score(pct * 100, vol, rsi, 0.6 if trend > 5 else 0.4, trend / 5)
            scores.append(score)
        except:
            pass

    if not scores:
        return {"error": "数据不足"}

    avg_score = np.mean(scores)
    stage, advice = get_emotion_stage(avg_score)

    return {
        "level": "板块", "industry": industry,
        "score": round(avg_score, 1), "stage": stage, "advice": advice,
        "stocks_count": len(scores),
    }


def analyze_stock_emotion(code: str, name: str = "") -> dict:
    """个股情绪量化"""
    try:
        from layer3_analysis.technical import compute
        from layer3_analysis.trend import compute_all as trend_compute
        tech = compute(code)
        tr = trend_compute(code, 60)

        price = tech.get("price", 0)
        ma20 = tech.get("ma20", price)
        pct = (price / ma20 - 1) * 100 if ma20 else 0
        vol = tech.get("vol_ratio", 1)
        rsi = tech.get("rsi14", 50)
        trend = tr.get("trend_total", 5)

        # 连涨天数作为涨跌比代理
        rows = db.query(
            "SELECT close FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 5",
            (code,))
        closes = [r["close"] for r in rows]
        up_days = sum(1 for i in range(len(closes)-1) if closes[i] > closes[i+1])
        up_ratio = up_days / max(1, len(closes)-1)

        score = calc_emotion_score(pct, vol, rsi, up_ratio, trend / 5)
        stage, advice = get_emotion_stage(score)

        return {
            "level": "个股", "code": code, "name": name,
            "score": round(score, 1), "stage": stage, "advice": advice,
        }
    except Exception as e:
        return {"error": str(e), "code": code, "name": name}


def full_emotion_analysis() -> dict:
    """三级情绪量化"""
    market = analyze_market_emotion()

    # 板块情绪
    sectors = {}
    for s in config.stocks:
        ind = s.get("industry", "其他")
        if ind not in sectors:
            sectors[ind] = analyze_sector_emotion(ind)

    # 个股情绪
    stocks = {}
    for s in config.stocks:
        stocks[s["code"]] = analyze_stock_emotion(s["code"], s["name"])

    # 综合建议
    m_score = market.get("score", 50)
    if m_score <= 25:
        overall = "大盘冰点，积极布局"
    elif m_score >= 75:
        overall = "大盘退潮，严控风险"
    else:
        overall = "大盘震荡，精选个股"

    result = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "market": market,
        "sectors": sectors,
        "stocks": stocks,
        "overall_advice": overall,
    }

    f = os.path.join(EMOTION_DIR, f"emotion_{datetime.now().strftime('%Y%m%d')}.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    return result
