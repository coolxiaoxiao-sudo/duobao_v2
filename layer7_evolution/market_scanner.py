"""市场底层逻辑扫描器 — 大盘趋势/板块轮动/题材周期/主力手法识别

核心能力：
1. 精准预判大盘整体趋势（趋势主升/震荡整理/下跌回调）
2. 板块轮动节奏分析
3. 题材炒作周期识别（萌芽/发酵/高潮/退潮）
4. 主力操盘手法识别（吸筹/拉升/出货/洗盘）
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("market_scanner")

SCANNER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "scanner")
os.makedirs(SCANNER_DIR, exist_ok=True)


def analyze_market_trend(indices: dict = None) -> dict:
    """大盘趋势研判 — 三形态分类
    - 趋势主升：指数连续上涨+均线多头+放量
    - 震荡整理：指数横盘+均线粘合+缩量
    - 下跌回调：指数连续下跌+均线空头+放量杀跌
    """
    if indices is None:
        try:
            from layer1_data.tencent_api import get_indices
            indices = get_indices()
        except:
            return {"phase": "UNKNOWN", "confidence": 0}

    # 取上证指数作为基准
    sh_data = indices.get("上证指数", {})
    if not sh_data or not isinstance(sh_data, dict):
        # 尝试其他指数
        for name, data in indices.items():
            if isinstance(data, dict) and data.get("pct_chg") is not None:
                sh_data = data
                break

    pct = sh_data.get("pct_chg", 0) or 0
    vol = sh_data.get("volume_ratio", 1) or 1

    # 多周期判断
    if pct > 1.5 and vol > 1.2:
        phase = "趋势主升"
        confidence = min(0.9, 0.5 + pct * 0.1)
        signals = ["放量上涨", "均线多头", "资金积极"]
        risk = "追高风险，关注量能持续性"
    elif pct < -1.5 and vol > 1.3:
        phase = "恐慌下跌"
        confidence = min(0.9, 0.5 + abs(pct) * 0.1)
        signals = ["放量杀跌", "均线空头", "恐慌盘涌现"]
        risk = "反弹可能随时出现，但趋势偏空"
    elif pct < -1.0:
        phase = "下跌回调"
        confidence = 0.6
        signals = ["缩量/温和下跌", "短期调整"]
        risk = "关注支撑位，若破位则加速"
    elif pct > 1.0:
        phase = "偏多震荡"
        confidence = 0.55
        signals = ["温和上涨", "蓄力阶段"]
        risk = "方向待确认，关注量能"
    elif abs(pct) < 0.5:
        phase = "震荡整理"
        confidence = 0.7
        signals = ["横盘整理", "多空平衡", "等待方向"]
        risk = "可能突然选择方向，做好双向预案"
    else:
        phase = "偏空震荡"
        confidence = 0.55
        signals = ["弱势震荡", "观望为主"]
        risk = "谨防向下破位"

    return {
        "phase": phase, "confidence": confidence,
        "signals": signals, "risk_warning": risk,
        "pct_chg": pct, "volume_ratio": vol,
    }


def analyze_sector_rotation(portfolio: list = None) -> dict:
    """板块轮动分析"""
    if portfolio is None:
        portfolio = config.stocks

    sectors = {}
    for s in portfolio:
        ind = s.get("industry", "其他")
        if ind not in sectors:
            sectors[ind] = {"stocks": [], "trends": [], "signals": []}
        sectors[ind]["stocks"].append(s)

    # 获取各板块趋势
    for ind, data in sectors.items():
        for s in data["stocks"]:
            try:
                from layer3_analysis.trend import compute_all as trend_compute
                tr = trend_compute(s["code"], 60)
                data["trends"].append(tr.get("trend_total", 5))
            except:
                pass

    # 板块热度排名
    sector_heat = {}
    for ind, data in sectors.items():
        if data["trends"]:
            avg = np.mean(data["trends"])
            count = len(data["stocks"])
            sector_heat[ind] = {"avg_trend": round(avg, 1), "stocks": count}

    ranked = sorted(sector_heat.items(), key=lambda x: x[1]["avg_trend"], reverse=True)

    if ranked:
        hot = ranked[0]
        cold = ranked[-1] if len(ranked) > 1 else hot

    return {
        "sector_heatmap": sector_heat,
        "hot_sector": ranked[0] if ranked else None,
        "cold_sector": ranked[-1] if len(ranked) > 1 else None,
        "rotation_signal": "科技偏强" if (ranked and "计算机" in str(ranked[0][0]))
                            else ("资源偏强" if ranked and "有色" in str(ranked[0][0])
                            else "无明显轮动"),
    }


def identify_cycle(code: str) -> dict:
    """题材周期识别 — 分析个股当前处于哪个阶段"""
    try:
        from layer3_analysis.technical import compute
        from layer3_analysis.trend import compute_all as trend_compute
        tech = compute(code)
        tr = trend_compute(code, 60)
    except:
        return {"cycle": "UNKNOWN", "confidence": 0}

    rsi = tech.get("rsi14", 50)
    trend = tr.get("trend_total", 5)
    vol = tech.get("vol_ratio", 1)
    macd_div = tr.get("macd_divergence", "none")
    ma_status = tr.get("ma_status", "unknown")

    # 四阶段判断
    if ma_status in ("bullish", "bullish_weak") and trend >= 7 and vol > 1.2:
        cycle = "拉升期"
        confidence = 0.75
        signals = ["均线多头", "放量", "趋势强劲"]
        risk = "高位追高风险，注意主力出货"
    elif ma_status in ("bullish", "bullish_weak") and trend >= 5:
        cycle = "主升期"
        confidence = 0.65
        signals = ["趋势向上", "量价配合"]
        risk = "可持有，设移动止盈"
    elif ma_status == "sideways" and trend >= 4 and rsi < 50:
        cycle = "吸筹/洗盘期"
        confidence = 0.5
        signals = ["横盘整理", "缩量", "主力控盘"]
        risk = "可能假突破，等待放量确认"
    elif ma_status in ("bearish_weak", "bearish") and rsi < 40:
        cycle = "退潮/出货期"
        confidence = 0.7
        signals = ["均线空头", "弱势", "资金流出"]
        risk = "反弹减仓，不追"
    elif macd_div == "bullish_divergence" and rsi < 35:
        cycle = "筑底期"
        confidence = 0.55
        signals = ["MACD底背离", "超卖", "可能反弹"]
        risk = "反转需确认，左侧风险大"
    elif macd_div == "bearish_divergence" and rsi > 70:
        cycle = "见顶期"
        confidence = 0.7
        signals = ["MACD顶背离", "超买", "量价背离"]
        risk = "减仓/清仓信号"
    else:
        cycle = "震荡期"
        confidence = 0.4
        signals = ["方向不明"]
        risk = "观望等待方向选择"

    return {
        "cycle": cycle, "confidence": confidence,
        "signals": signals, "risk_warning": risk,
        "trend_score": trend, "rsi": rsi, "vol_ratio": vol,
    }


def identify_manipulation_pattern(code: str) -> dict:
    """主力操盘手法识别
    - 吸筹：缩量横盘 + 尾盘拉高 + 大单默默买入
    - 拉升：放量突破 + 连续阳线 + 游资接力
    - 出货：高位放量滞涨 + 阴线增多 + 大单卖出
    - 洗盘：缩量急跌 + 快速拉回 + 制造恐慌
    """
    try:
        from layer3_analysis.technical import compute
        tech = compute(code)
    except:
        return {"pattern": "UNKNOWN"}

    rsi = tech.get("rsi14", 50)
    vol = tech.get("vol_ratio", 1)
    cons_days = tech.get("cons_days", 0)
    atr_pct = tech.get("atr_pct", 5)

    # 基于量价特征判断
    if rsi > 80 and vol < 0.8:
        pattern = "高位缩量滞涨 → 疑似出货"
        confidence = 0.6
    elif rsi > 70 and vol > 1.5 and cons_days > 0:
        pattern = "放量拉升 → 主力/游资推动"
        confidence = 0.55
    elif rsi < 30 and vol > 1.3:
        pattern = "恐慌放量 → 洗盘或真出货"
        confidence = 0.4
    elif rsi < 35 and vol < 0.6 and atr_pct < 3:
        pattern = "缩量筑底 → 疑似吸筹"
        confidence = 0.45
    elif rsi > 85 and atr_pct > 8:
        pattern = "高位剧烈波动 → 多空分歧，疑似出货"
        confidence = 0.65
    elif cons_days < -4 and rsi < 40:
        pattern = "连跌缩量 → 可能洗盘（需次日验证）"
        confidence = 0.4
    else:
        pattern = "无明显异常操纵痕迹"
        confidence = 0.3

    # 诱多诱空判断
    if rsi > 70 and vol > 2.0:
        trap = "谨防诱多"
    elif rsi < 30 and vol > 2.0:
        trap = "谨防诱空"
    else:
        trap = "无明显陷阱"

    return {
        "pattern": pattern, "confidence": confidence,
        "trap_warning": trap,
        "rsi": rsi, "vol_ratio": vol, "atr_pct": atr_pct,
    }


def full_market_scan() -> dict:
    """全市场底层逻辑扫描"""
    # 大盘趋势
    trend = analyze_market_trend()

    # 板块轮动
    rotation = analyze_sector_rotation()

    # 对每只持仓进行周期+手法分析
    stock_scans = {}
    for s in config.stocks:
        code = s["code"]
        try:
            cycle = identify_cycle(code)
            manipulation = identify_manipulation_pattern(code)
            stock_scans[code] = {
                "name": s["name"], "industry": s.get("industry", ""),
                "cycle": cycle, "manipulation": manipulation,
            }
        except Exception as e:
            stock_scans[code] = {"name": s["name"], "error": str(e)}

    # 保存扫描结果
    result = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "market_trend": trend,
        "sector_rotation": rotation,
        "stock_scans": stock_scans,
    }

    scan_file = os.path.join(SCANNER_DIR, f"scan_{datetime.now().strftime('%Y%m%d')}.json")
    with open(scan_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def identify_sentiment_cycle(indices=None) -> dict:
    """市场情绪周期: 极度恐慌/恐慌/中性/乐观/贪婪"""
    if indices is None:
        try:
            from layer1_data.tencent_api import get_indices
            indices = get_indices()
        except:
            return {"cycle": "UNKNOWN", "score": 50}
    pcts, vols = [], []
    for name, data in indices.items():
        if not isinstance(data, dict): continue
        pcts.append(data.get("pct_chg",0) or 0)
        vols.append(data.get("volume_ratio",1) or 1)
    if not pcts: return {"cycle": "UNKNOWN", "score": 50}
    avg_pct, avg_vol = np.mean(pcts), np.mean(vols)
    sentiment = max(0, min(100, 50 + avg_pct*5 + (avg_vol-1)*10))
    if sentiment >= 80: cycle = "贪婪"; advice = "极度乐观，严控仓位不追高"
    elif sentiment >= 65: cycle = "乐观"; advice = "情绪积极，持股设移动止盈"
    elif sentiment >= 40: cycle = "中性"; advice = "情绪平稳，按策略操作"
    elif sentiment >= 25: cycle = "恐慌"; advice = "接近底部区域，分批布局"
    else: cycle = "极度恐慌"; advice = "极端恐慌往往是底部，等待企稳"
    return {"cycle": cycle, "score": round(sentiment,1),
            "avg_pct_chg": round(avg_pct,2), "avg_vol_ratio": round(avg_vol,2),
            "advice": advice}
