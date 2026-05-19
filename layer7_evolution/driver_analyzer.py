"""个股驱动逻辑深度拆解模块 — 每次研判附带完整因果链

输出结构：
  1. 核心驱动因子（利好/利空各列出，附影响力度1-5）
  2. 走势推演路径（乐观/中性/悲观三条路径）
  3. 确定性等级 A/B/C/D + 推导逻辑
  4. 潜在隐患与应对预案
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("driver_analyzer")

DRIVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "drivers")
os.makedirs(DRIVER_DIR, exist_ok=True)


def analyze_drivers(code: str, name: str, industry: str = "",
                    cost: float = 0, stop: float = 0, target: float = 0) -> dict:
    """深度拆解个股驱动逻辑"""
    drivers_bullish = []  # 利好
    drivers_bearish = []  # 利空

    try:
        from layer3_analysis.technical import compute
        from layer3_analysis.trend import compute_all as trend_compute
        tech = compute(code)
        tr = trend_compute(code, 60)
    except:
        return {"error": "数据不足"}

    price = tech.get("price", 0)
    rsi = tech.get("rsi14", 50)
    vol_ratio = tech.get("vol_ratio", 1)
    trend = tr.get("trend_total", 5)
    ma_status = tr.get("ma_status", "unknown")
    trend_signal = tr.get("trend_signal", "NEUTRAL")
    macd_div = tr.get("macd_divergence", "none")
    adx = tr.get("adx", 0)
    rel_strength = tr.get("rel_strength", 50)

    # === 利好因子 ===

    # 趋势驱动
    if trend >= 7:
        drivers_bullish.append({
            "factor": "趋势强势", "impact": 5,
            "logic": f"趋势总分{trend}/12，MA排列{ma_status}，ADX={adx}趋势明确",
            "sustainability": "中期持续（1-3个月）"
        })
    elif trend >= 5:
        drivers_bullish.append({
            "factor": "趋势偏多", "impact": 3,
            "logic": f"趋势总分{trend}/12，{ma_status}，方向偏上但力度一般",
            "sustainability": "短期（1-2周）"
        })

    # 超卖反弹
    if rsi < 35:
        drivers_bullish.append({
            "factor": "超卖反弹", "impact": 3,
            "logic": f"RSI={rsi}进入超卖区，短期抛压衰竭，技术性反弹概率高",
            "sustainability": "短期（3-5天）"
        })

    # 量能驱动
    if vol_ratio > 1.5:
        drivers_bullish.append({
            "factor": "放量资金流入", "impact": 4,
            "logic": f"成交量{vol_ratio:.1f}倍均量，资金积极介入",
            "sustainability": "需观察持续性，1-2天确认"
        })

    # MACD底背离
    if macd_div == "bullish_divergence":
        drivers_bullish.append({
            "factor": "MACD底背离", "impact": 4,
            "logic": "价格创新低但MACD不创新低，下跌动能衰竭信号",
            "sustainability": "中期反转信号（2-4周）"
        })

    # 相对强度
    if rel_strength > 60:
        drivers_bullish.append({
            "factor": "相对强度领先", "impact": 3,
            "logic": f"相对大盘强度{rel_strength}/100，跑赢大盘",
            "sustainability": "中期持续"
        })

    # 成本优势
    if cost and price > cost:
        pnl = (price / cost - 1) * 100
        drivers_bullish.append({
            "factor": "持仓浮盈", "impact": 2,
            "logic": f"浮盈{pnl:.1f}%，成本优势",
            "sustainability": "持续"
        })

    # === 利空因子 ===

    # 趋势弱势
    if trend < 4:
        drivers_bearish.append({
            "factor": "趋势弱势", "impact": 4,
            "logic": f"趋势总分仅{trend}/12，{ma_status}，方向不明或偏空",
            "sustainability": "中期压力"
        })

    # 超买风险
    if rsi > 80:
        drivers_bearish.append({
            "factor": "严重超买", "impact": 5,
            "logic": f"RSI={rsi}极端超买，短期回调概率极高",
            "sustainability": "短期（1-3天）"
        })
    elif rsi > 70:
        drivers_bearish.append({
            "factor": "超买", "impact": 3,
            "logic": f"RSI={rsi}偏高，追涨风险增大",
            "sustainability": "短期"
        })

    # 量能萎缩
    if vol_ratio < 0.5:
        drivers_bearish.append({
            "factor": "严重缩量", "impact": 3,
            "logic": f"成交量仅{vol_ratio:.1f}倍均量，资金冷清",
            "sustainability": "可能持续"
        })

    # MACD顶背离
    if macd_div == "bearish_divergence":
        drivers_bearish.append({
            "factor": "MACD顶背离", "impact": 5,
            "logic": "价格创新高但MACD不创新高，上涨动能衰竭",
            "sustainability": "中期反转信号（2-4周）"
        })

    # 止损逼近
    if stop and price:
        dts = (price / stop - 1) * 100
        if dts < 5:
            drivers_bearish.append({
                "factor": "止损逼近", "impact": 5,
                "logic": f"距止损仅{dts:.1f}%，随时可能触发",
                "sustainability": "即时风险"
            })
        elif dts < 10:
            drivers_bearish.append({
                "factor": "接近止损", "impact": 3,
                "logic": f"距止损{dts:.1f}%，需关注",
                "sustainability": "短期"
            })

    # 深套
    if cost and price < cost:
        pnl = (price / cost - 1) * 100
        if pnl < -30:
            drivers_bearish.append({
                "factor": "深度套牢", "impact": 4,
                "logic": f"浮亏{pnl:.1f}%，解套难度大",
                "sustainability": "长期压力"
            })

    # 相对弱势
    if rel_strength < 40:
        drivers_bearish.append({
            "factor": "相对弱势", "impact": 3,
            "logic": f"相对大盘强度{rel_strength}/100，跑输大盘",
            "sustainability": "中期"
        })

    # === 综合评估 ===
    bull_score = sum(d["impact"] for d in drivers_bullish)
    bear_score = sum(d["impact"] for d in drivers_bearish)
    net_score = bull_score - bear_score

    # 确定性等级
    if bull_score >= 10 and bear_score <= 3:
        grade = "A"
        grade_desc = "高度确定，多因子共振看多"
    elif bull_score >= 7 and bear_score <= 5:
        grade = "B"
        grade_desc = "偏多确定，但存在一定隐患"
    elif abs(net_score) <= 4:
        grade = "C"
        grade_desc = "多空分歧，方向不明，需等待催化"
    elif bear_score >= 10 and bull_score <= 3:
        grade = "D"
        grade_desc = "高度确定看空，多因子共振看空"
    else:
        grade = "C"
        grade_desc = "多空交织，需进一步确认"

    # === 走势推演 ===
    bb_lower = tech.get("bb_lower", price * 0.95)
    bb_upper = tech.get("bb_upper", price * 1.05)
    ma20 = tech.get("ma20", price)

    scenarios = {
        "乐观": {
            "target": round(bb_upper * 1.05, 2),
            "probability": f"{min(40, max(15, 25 + net_score * 2))}%",
            "path": "放量突破MA20 → 测试布林上轨 → 向上拓展",
            "condition": "需成交量放大至1.5倍+，MACD金叉确认"
        },
        "中性": {
            "target": round(ma20, 2),
            "probability": f"{min(60, max(30, 50 - abs(net_score)))}%",
            "path": "在布林带中轨附近震荡 → 等待方向选择",
            "condition": "维持当前量能水平"
        },
        "悲观": {
            "target": round(bb_lower * 0.95, 2),
            "probability": f"{min(40, max(15, 25 - net_score * 2))}%",
            "path": "跌破MA20 → 测试布林下轨 → 可能加速下行",
            "condition": "缩量下跌或放量破位"
        },
    }

    # === 潜在隐患 ===
    hazards = []
    if rsi > 75:
        hazards.append("超买回调风险：RSI偏高，短期可能3-5%回撤")
    if vol_ratio < 0.7:
        hazards.append("流动性风险：缩量状态下突破概率低")
    if trend < 4:
        hazards.append("趋势风险：均线空头排列，反弹可能是陷阱")
    if bear_score > bull_score:
        hazards.append("多空失衡：利空因子占优，需等待利空出尽")
    if not hazards:
        hazards.append("当前无明显隐患，但需持续跟踪量能变化")

    # === 应对预案 ===
    if grade in ("A", "B"):
        plan = f"偏多操作：可在支撑位附近布局，止损设于{round(bb_lower, 2)}，目标{scenarios['乐观']['target']}"
    elif grade == "C":
        plan = f"观望为主：等待方向确认，若放量突破{round(ma20, 2)}可轻仓跟进"
    else:
        plan = f"偏空操作：反弹减仓，止损严格执行，不抄底"

    return {
        "code": code, "name": name, "industry": industry,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "price": price,
        "grade": grade, "grade_desc": grade_desc,
        "bull_score": bull_score, "bear_score": bear_score,
        "net_score": net_score,
        "drivers_bullish": drivers_bullish,
        "drivers_bearish": drivers_bearish,
        "scenarios": scenarios,
        "hazards": hazards,
        "action_plan": plan,
        "top_bullish": drivers_bullish[0]["factor"] if drivers_bullish else "无",
        "top_bearish": drivers_bearish[0]["factor"] if drivers_bearish else "无",
    }


def batch_analyze_drivers() -> dict:
    """全持仓驱动逻辑拆解"""
    results = {}
    for s in config.stocks:
        try:
            results[s["code"]] = analyze_drivers(
                s["code"], s["name"], s.get("industry", ""),
                s.get("cost", 0), s.get("stop", 0), s.get("target", 0))
        except Exception as e:
            results[s["code"]] = {"error": str(e), "name": s["name"]}

    # 按确定性等级分组
    grades = {"A": [], "B": [], "C": [], "D": []}
    for code, r in results.items():
        g = r.get("grade", "C")
        if g in grades:
            grades[g].append({"code": code, "name": r.get("name", code),
                              "net": r.get("net_score", 0)})

    f = os.path.join(DRIVER_DIR, f"drivers_{datetime.now().strftime('%Y%m%d')}.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "grades": grades,
        "details": results,
    }
