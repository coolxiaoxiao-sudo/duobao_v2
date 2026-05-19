"""多场景策略适配 — 牛市主升/震荡市波段/熊市避险/题材炒作/价值轮动五大模型

自动识别市场环境，切换对应策略
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List

import numpy as np

from core.config import config
from core.logging import get_logger

logger = get_logger("scenario_models")

SCENARIO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "scenario")
os.makedirs(SCENARIO_DIR, exist_ok=True)


# 五大场景模型定义
SCENARIOS = {
    "牛市主升": {
        "signals": ["指数20日线上", "成交量持续放大", "普涨格局", "情绪亢奋"],
        "strategy": "趋势跟随，重仓持有龙头，移动止盈",
        "position": "8-10成",
        "entry": "突破买入，回调加仓",
        "exit": "跌破10日线减仓，跌破20日线清仓",
        "stock_selection": "选最强板块最强个股，强者恒强",
    },
    "震荡市波段": {
        "signals": ["指数横盘", "量能萎缩", "板块轮动快", "情绪中性"],
        "strategy": "高抛低吸，波段操作，不追涨杀跌",
        "position": "5-6成",
        "entry": "支撑位低吸，不追高",
        "exit": "压力位止盈，破位止损",
        "stock_selection": "选超跌反弹或突破回调，不追热点",
    },
    "熊市避险": {
        "signals": ["指数20日线下", "成交量萎缩", "普跌格局", "情绪恐慌"],
        "strategy": "现金为王，空仓或轻仓，只做超跌反弹",
        "position": "0-3成",
        "entry": "左侧不抄底，右侧等确认",
        "exit": "反弹即走，不恋战",
        "stock_selection": "选防御性板块，高股息，低估值",
    },
    "题材炒作": {
        "signals": ["热点集中", "连板股多", "游资活跃", "情绪亢奋"],
        "strategy": "快进快出，追龙头，严格止损",
        "position": "3-5成",
        "entry": "首板/二板确认后追入",
        "exit": "不涨停即走，次日不连板即出",
        "stock_selection": "选题材正宗+流通盘小+股性活跃",
    },
    "价值轮动": {
        "signals": ["业绩驱动", "机构主导", "估值修复", "情绪理性"],
        "strategy": "左侧布局，等待估值修复，中期持有",
        "position": "6-8成",
        "entry": "低估时分批建仓",
        "exit": "估值修复到位或基本面恶化",
        "stock_selection": "选行业龙头+业绩稳定+估值合理",
    },
}


def detect_scenario() -> str:
    """识别当前市场场景"""
    try:
        from layer1_data.tencent_api import get_indices
        from layer7_evolution.emotion_quant import analyze_market_emotion

        indices = get_indices()
        emotion = analyze_market_emotion()

        # 提取特征
        pcts = [d.get("pct_chg", 0) or 0 for d in indices.values() if isinstance(d, dict)]
        vols = [d.get("volume_ratio", 1) or 1 for d in indices.values() if isinstance(d, dict)]

        avg_pct = np.mean(pcts) if pcts else 0
        avg_vol = np.mean(vols) if vols else 1
        up_ratio = sum(1 for p in pcts if p > 0) / len(pcts) if pcts else 0.5

        emo_score = emotion.get("score", 50)
        emo_stage = emotion.get("stage", "中性")

        # 场景判断逻辑
        if avg_pct > 1.5 and avg_vol > 1.3 and up_ratio > 0.7 and emo_score > 70:
            return "牛市主升"
        elif avg_pct < -1.5 and avg_vol > 1.2 and up_ratio < 0.3 and emo_score < 30:
            return "熊市避险"
        elif emo_score > 75 and avg_vol > 1.5:
            return "题材炒作"
        elif abs(avg_pct) < 0.5 and avg_vol < 0.9 and 40 < emo_score < 60:
            return "震荡市波段"
        elif 10 < emo_score < 40 and avg_pct > -1:
            return "价值轮动"
        else:
            return "震荡市波段"  # 默认
    except:
        return "震荡市波段"


def get_scenario_strategy(scenario: str = None) -> dict:
    """获取当前场景策略"""
    if scenario is None:
        scenario = detect_scenario()

    model = SCENARIOS.get(scenario, SCENARIOS["震荡市波段"])

    return {
        "current_scenario": scenario,
        "date": datetime.now().strftime("%Y-%m-%d"),
        **model,
    }


def scenario_adaptation() -> dict:
    """场景适配建议"""
    current = detect_scenario()
    strategy = get_scenario_strategy(current)

    # 持仓适配检查
    mismatches = []
    for s in config.stocks:
        # 简化：检查是否符合当前场景选股标准
        if current == "牛市主升" and s.get("industry") in ["电力"]:
            mismatches.append(f"{s['name']}: 防御板块不适合牛市主升")
        elif current == "熊市避险" and s.get("industry") in ["计算机", "电子"]:
            mismatches.append(f"{s['name']}: 成长板块不适合熊市避险")

    return {
        "detected_scenario": current,
        "strategy": strategy,
        "position_recommendation": strategy["position"],
        "mismatches": mismatches,
        "action": "调整持仓以匹配当前市场场景" if mismatches else "持仓与场景匹配",
    }


def save_scenario_log():
    """记录场景切换日志"""
    scenario = detect_scenario()
    f = os.path.join(SCENARIO_DIR, "scenario_log.json")
    logs = []
    if os.path.exists(f):
        try:
            with open(f, encoding="utf-8") as fh:
                logs = json.load(fh)
        except:
            pass

    # 只记录变化
    if not logs or logs[-1].get("scenario") != scenario:
        logs.append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "scenario": scenario,
        })
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(logs, fh, ensure_ascii=False, indent=2)

    return logs
