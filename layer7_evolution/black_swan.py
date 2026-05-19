"""黑天鹅前置防御 — 极端行情预判与应对预案

监控信号：
  1. 大盘跳水预警
  2. 板块集体退潮
  3. 突发利空踩踏
  4. 流动性枯竭

应对：减仓/空仓/避险切换
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("black_swan")

SWAN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "blackswan")
os.makedirs(SWAN_DIR, exist_ok=True)


def detect_market_crash_risk() -> dict:
    """大盘跳水风险检测"""
    try:
        from layer1_data.tencent_api import get_indices
        indices = get_indices()
    except:
        return {"error": "数据获取失败"}

    risk_score = 0
    signals = []

    # 1. 连续下跌
    pcts = [d.get("pct_chg", 0) or 0 for d in indices.values() if isinstance(d, dict)]
    if len(pcts) >= 3:
        if all(p < -0.5 for p in pcts[-3:]):
            risk_score += 3
            signals.append("连续3日普跌")

    # 2. 放量杀跌
    vols = [d.get("volume_ratio", 1) or 1 for d in indices.values() if isinstance(d, dict)]
    avg_vol = np.mean(vols) if vols else 1
    if avg_vol > 1.5 and np.mean(pcts) < -1:
        risk_score += 4
        signals.append("放量杀跌，恐慌盘涌出")

    # 3. 跌破关键位
    if np.mean(pcts) < -2:
        risk_score += 3
        signals.append("单日大跌超2%")

    # 4. 波动率飙升
    if np.std(pcts) > 2:
        risk_score += 2
        signals.append("波动率异常，市场不稳定")

    level = "LOW"
    if risk_score >= 8:
        level = "CRITICAL"
    elif risk_score >= 5:
        level = "HIGH"
    elif risk_score >= 3:
        level = "MEDIUM"

    return {
        "type": "大盘跳水", "risk_level": level, "score": risk_score,
        "signals": signals,
        "action": "立即减仓至3成以下" if level == "CRITICAL" else
                  ("减仓至5成" if level == "HIGH" else "密切关注"),
    }


def detect_sector_collapse() -> dict:
    """板块集体退潮检测"""
    industries = {}
    for s in config.stocks:
        ind = s.get("industry", "其他")
        if ind not in industries:
            industries[ind] = []
        industries[ind].append(s["code"])

    at_risk = []
    for ind, codes in industries.items():
        if len(codes) < 2:
            continue
        # 检查板块内股票是否集体下跌
        declines = 0
        for code in codes:
            try:
                rows = db.query(
                    "SELECT close FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 5",
                    (code,))
                if len(rows) >= 2:
                    if rows[0]["close"] < rows[-1]["close"] * 0.95:
                        declines += 1
            except:
                pass

        if declines >= len(codes) * 0.7:  # 70%下跌
            at_risk.append(ind)

    return {
        "type": "板块退潮",
        "at_risk_sectors": at_risk,
        "action": f"{', '.join(at_risk)}板块集体走弱，减仓避险" if at_risk else "无明显板块退潮风险",
    }


def detect_liquidity_crisis() -> dict:
    """流动性危机检测"""
    try:
        from layer1_data.tencent_api import get_indices
        indices = get_indices()
        vols = [d.get("volume_ratio", 1) or 1 for d in indices.values() if isinstance(d, dict)]
        avg_vol = np.mean(vols) if vols else 1

        if avg_vol < 0.6:
            return {
                "type": "流动性枯竭",
                "risk_level": "HIGH",
                "signals": [f"市场极度缩量，成交{avg_vol:.1f}倍均量"],
                "action": "流动性枯竭，减少交易，等待放量",
            }
    except:
        pass
    return {"type": "流动性", "risk_level": "LOW", "action": "正常"}


def black_swan_defense() -> dict:
    """黑天鹅综合防御"""
    market = detect_market_crash_risk()
    sector = detect_sector_collapse()
    liquidity = detect_liquidity_crisis()

    # 综合评级
    risks = [market.get("risk_level", "LOW"),
             "HIGH" if sector.get("at_risk_sectors") else "LOW",
             liquidity.get("risk_level", "LOW")]

    if "CRITICAL" in risks:
        overall = "RED_ALERT"
        defense_action = "【紧急】立即减仓至2成以下，现金为王，暂停新开仓"
    elif risks.count("HIGH") >= 2:
        overall = "RED"
        defense_action = "【高危】减仓至3-4成，只保留最强持仓"
    elif "HIGH" in risks:
        overall = "ORANGE"
        defense_action = "【警戒】减仓至5成，严控风险"
    else:
        overall = "GREEN"
        defense_action = "【正常】风险可控，按计划操作"

    result = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "overall": overall,
        "defense_action": defense_action,
        "market_crash": market,
        "sector_collapse": sector,
        "liquidity": liquidity,
    }

    # 保存
    f = os.path.join(SWAN_DIR, f"swan_{datetime.now().strftime('%Y%m%d')}.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    return result
