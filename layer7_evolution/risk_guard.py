"""风控前置预判模块 — 个股/板块/大盘三重风险预警

核心理念：
在损失发生前预判风险，而非事后被动止损。
三层防线：个股级 → 板块级 → 大盘级
每层输出风险等级、触发条件和应对方案
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("risk_guard")

RISK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "risk")
os.makedirs(RISK_DIR, exist_ok=True)


def individual_risk(code: str, name: str, cost: float, stop: float, target: float) -> dict:
    """个股级风险预判"""
    try:
        from layer3_analysis.technical import compute
        from layer3_analysis.trend import compute_all as trend_compute
        tech = compute(code)
        tr = trend_compute(code, 60)
    except:
        return {"risk_level": "UNKNOWN", "score": 0}

    price = tech.get("price", 0)
    rsi = tech.get("rsi14", 50)
    vol_ratio = tech.get("vol_ratio", 1)
    atr_pct = tech.get("atr_pct", 5)
    cons_days = tech.get("cons_days", 0)
    trend = tr.get("trend_total", 5)

    risks = []
    risk_score = 0  # 越高越危险

    # 1. 连续下跌风险
    if cons_days < -3:
        risk_score += 3
        risks.append({"type": "连跌风险", "detail": f"连跌{abs(cons_days)}天", "severity": "HIGH"})
    elif cons_days < 0:
        risk_score += 1
        risks.append({"type": "轻微下跌", "detail": f"小跌{abs(cons_days)}天", "severity": "LOW"})

    # 2. 趋势破位风险
    if trend < 3:
        risk_score += 4
        risks.append({"type": "趋势破位", "detail": f"趋势分仅{trend}", "severity": "CRITICAL"})
    elif trend < 5:
        risk_score += 2
        risks.append({"type": "趋势走弱", "detail": f"趋势分{trend}偏弱", "severity": "MEDIUM"})

    # 3. 接近止损风险
    if stop and price:
        dts = (price / stop - 1) * 100
        if dts < 3:
            risk_score += 5
            risks.append({"type": "止损逼近", "detail": f"仅距{dts:.1f}%", "severity": "CRITICAL"})
        elif dts < 8:
            risk_score += 2
            risks.append({"type": "接近止损", "detail": f"距止损{dts:.1f}%", "severity": "MEDIUM"})

    # 4. 高波动风险
    if atr_pct > 8:
        risk_score += 3
        risks.append({"type": "高波动", "detail": f"ATR{atr_pct:.1f}%", "severity": "HIGH"})

    # 5. RSI极端风险
    if rsi > 85:
        risk_score += 3
        risks.append({"type": "极端超买", "detail": f"RSI={rsi}", "severity": "HIGH"})
    elif rsi < 25:
        risk_score += 2
        risks.append({"type": "极端超卖", "detail": f"RSI={rsi}", "severity": "MEDIUM"})

    # 6. 量能萎缩风险
    if vol_ratio < 0.4:
        risk_score += 2
        risks.append({"type": "流动性风险", "detail": "极度缩量", "severity": "MEDIUM"})

    # 风险等级
    if risk_score >= 8:
        level = "CRITICAL"
    elif risk_score >= 5:
        level = "HIGH"
    elif risk_score >= 3:
        level = "MEDIUM"
    else:
        level = "LOW"

    # 应对方案
    if level == "CRITICAL":
        action = "立即评估是否减仓/清仓。主因: " + "; ".join(r["type"] for r in risks if r["severity"] == "CRITICAL")
    elif level == "HIGH":
        action = "减仓至半仓以下，设严格止损，不补仓"
    elif level == "MEDIUM":
        action = "密切关注，设好止损单"
    else:
        action = "正常持有，按计划操作"

    return {
        "code": code, "name": name, "price": price,
        "risk_level": level, "risk_score": risk_score,
        "risks": risks, "action_plan": action,
    }


def sector_risk(portfolio: list = None) -> dict:
    """板块级别风险预判 — 判断是否有板块退潮风险"""
    if portfolio is None:
        portfolio = config.stocks

    results = {}
    sectors = {}
    for s in portfolio:
        ind = s.get("industry", "其他")
        if ind not in sectors:
            sectors[ind] = {"stocks": [], "risk_scores": []}
        sectors[ind]["stocks"].append(s)

    for ind, data in sectors.items():
        for s in data["stocks"]:
            try:
                risk = individual_risk(s["code"], s["name"], s.get("cost", 0),
                                       s.get("stop", 0), s.get("target", 0))
                data["risk_scores"].append(risk["risk_score"])
            except:
                pass

        avg_risk = np.mean(data["risk_scores"]) if data["risk_scores"] else 0
        if avg_risk >= 6:
            warning = f"{ind}板块整体风险偏高，有退潮风险"
        elif avg_risk >= 4:
            warning = f"{ind}板块需关注"
        else:
            warning = f"{ind}板块风险可控"

        results[ind] = {
            "avg_risk": round(avg_risk, 1),
            "stock_count": len(data["stocks"]),
            "warning": warning,
        }

    # 找出风险最高的板块
    if results:
        max_risk = max(results.items(), key=lambda x: x[1]["avg_risk"])
    else:
        max_risk = (None, None)

    return {
        "sector_risks": results,
        "highest_risk_sector": max_risk[0] if max_risk[0] else None,
    }


def market_systemic_risk() -> dict:
    """大盘系统性风险预判"""
    try:
        from layer1_data.tencent_api import get_indices
        indices = get_indices()
    except:
        indices = {}

    risk_score = 0
    signals = []

    for name, data in indices.items():
        if not isinstance(data, dict):
            continue
        pct = data.get("pct_chg", 0) or 0
        vol = data.get("volume_ratio", 1) or 1

        if pct < -2 and vol > 1.5:
            risk_score += 3
            signals.append(f"{name}放量暴跌{pct:.1f}%")
        elif pct < -1:
            risk_score += 1
            signals.append(f"{name}下跌{pct:.1f}%")

    # 广度和深度
    declining = sum(1 for _, data in indices.items()
                    if isinstance(data, dict) and (data.get("pct_chg", 0) or 0) < 0)
    if declining >= 5:
        risk_score += 3
        signals.append(f"普跌格局({declining}个指数下跌)")
    elif declining >= 3:
        risk_score += 1

    if risk_score >= 8:
        level = "系统性风险"
        action = "大幅减仓至2成以下，现金为王"
    elif risk_score >= 5:
        level = "高风险"
        action = "减仓至3-4成，严控风险"
    elif risk_score >= 3:
        level = "中等风险"
        action = "仓位控制在5-6成，注意防守"
    else:
        level = "低风险"
        action = "正常仓位，按计划操作"

    return {
        "risk_level": level, "risk_score": risk_score,
        "signals": signals, "action_plan": action,
    }


def full_risk_assessment() -> dict:
    """三重风控预判"""
    # 1. 大盘
    market = market_systemic_risk()

    # 2. 板块
    sector = sector_risk()

    # 3. 个股
    individuals = {}
    for s in config.stocks:
        try:
            individuals[s["code"]] = individual_risk(
                s["code"], s["name"], s.get("cost", 0), s.get("stop", 0), s.get("target", 0))
        except Exception as e:
            individuals[s["code"]] = {"error": str(e), "name": s["name"]}

    # 综合风险等级
    critical_count = sum(1 for i in individuals.values()
                         if isinstance(i, dict) and i.get("risk_level") == "CRITICAL")
    high_count = sum(1 for i in individuals.values()
                     if isinstance(i, dict) and i.get("risk_level") == "HIGH")

    if market["risk_level"] == "系统性风险":
        overall = "RED_ALERT"
        overall_action = "全市场系统性风险，大幅减仓"
    elif critical_count >= 3:
        overall = "RED"
        overall_action = f"多只个股({critical_count}只)触发严重风险预警"
    elif high_count >= 5:
        overall = "ORANGE"
        overall_action = f"多数持仓({high_count}只)处于高风险区间"
    elif high_count >= 2:
        overall = "YELLOW"
        overall_action = "部分持仓偏高，注意防守"
    else:
        overall = "GREEN"
        overall_action = "风险可控，按计划操作"

    result = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "overall": overall, "overall_action": overall_action,
        "market_risk": market, "sector_risk": sector,
        "individual_risks": individuals,
        "critical_count": critical_count, "high_count": high_count,
    }

    # 保存
    risk_file = os.path.join(RISK_DIR, f"risk_{datetime.now().strftime('%Y%m%d')}.json")
    with open(risk_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result
