"""策略研习模块 — 顶级游资/机构交易逻辑吸收 + 策略库迭代

核心能力：
1. 吸收成熟交易逻辑（游资短线 + 机构长线）
2. 策略库管理：注册、评估、淘汰、升级
3. 新旧策略对比测试
4. 自动识别最优策略组合
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List, Optional

from core.logging import get_logger

logger = get_logger("strategy_learner")

LEARNER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "strategies")
os.makedirs(LEARNER_DIR, exist_ok=True)

# 内置策略库
BUILTIN_STRATEGIES = {
    # --- 游资类 ---
    "涨停板接力": {
        "type": "游资短线",
        "description": "首板/二板确认后追入，博弈连板溢价",
        "entry_rule": "昨日涨停 + 今日高开3%以上 + 竞价量>昨日10%",
        "exit_rule": "次日不涨停即卖 / 跌破分时均线清仓",
        "risk_level": "极高",
        "holding_period": "1-3天",
        "win_rate_expected": 0.45,
        "profit_loss_ratio": 2.5,
        "suitable_market": "强势/震荡",
    },
    "超跌反弹": {
        "type": "游资短线",
        "description": "连续急跌后博技术性反弹",
        "entry_rule": "连跌4天以上 + RSI<30 + 缩量企稳",
        "exit_rule": "反弹3-5%止盈 / 跌破前低止损",
        "risk_level": "高",
        "holding_period": "1-5天",
        "win_rate_expected": 0.55,
        "profit_loss_ratio": 1.8,
        "suitable_market": "下跌末期/震荡",
    },
    "龙头首阴": {
        "type": "游资中线",
        "description": "强势龙头股第一根阴线低吸",
        "entry_rule": "前期涨幅>30% + 首阴跌幅<5% + 缩量",
        "exit_rule": "次日若继续跌-3%止损 / 反弹5%止盈",
        "risk_level": "高",
        "holding_period": "1-2天",
        "win_rate_expected": 0.5,
        "profit_loss_ratio": 2.0,
        "suitable_market": "强势",
    },

    # --- 机构类 ---
    "趋势跟随": {
        "type": "机构中长线",
        "description": "均线多头排列 + 基本面扎实，趋势持有",
        "entry_rule": "MA5>MA10>MA20>MA60 + PE<40 + ROE>10%",
        "exit_rule": "MA10死叉MA20 / 基本面恶化 / 达到目标价",
        "risk_level": "中",
        "holding_period": "1-6月",
        "win_rate_expected": 0.6,
        "profit_loss_ratio": 2.0,
        "suitable_market": "趋势上涨/震荡偏多",
    },
    "均值回归": {
        "type": "机构量化",
        "description": "价格严重偏离均线后回归",
        "entry_rule": "价格跌破布林下轨 + RSI<35 + 缩量",
        "exit_rule": "回到布林中轨止盈 / 跌破下轨-3%止损",
        "risk_level": "中低",
        "holding_period": "3-10天",
        "win_rate_expected": 0.65,
        "profit_loss_ratio": 1.5,
        "suitable_market": "震荡",
    },
    "突破买入": {
        "type": "机构/游资混合",
        "description": "关键压力位放量突破后追入",
        "entry_rule": "突破MA60/前高 + 放量1.5倍 + MACD金叉",
        "exit_rule": "回破突破位-3%止损 / 目标涨幅10%止盈",
        "risk_level": "中高",
        "holding_period": "3-15天",
        "win_rate_expected": 0.5,
        "profit_loss_ratio": 2.5,
        "suitable_market": "趋势/震荡偏多",
    },
    "价值埋伏": {
        "type": "机构长线",
        "description": "低估值+高股息+行业龙头，左侧布局",
        "entry_rule": "PE<15 + 股息率>3% + 市值>500亿 + 行业龙头",
        "exit_rule": "PE>30 / 基本面恶化 / 止损-15%",
        "risk_level": "低",
        "holding_period": "6-24月",
        "win_rate_expected": 0.7,
        "profit_loss_ratio": 2.5,
        "suitable_market": "熊市/震荡",
    },
}


def get_strategy_library() -> dict:
    """获取策略库（内置 + 用户自定义）"""
    library = BUILTIN_STRATEGIES.copy()

    # 加载用户自定义策略
    custom_file = os.path.join(LEARNER_DIR, "custom_strategies.json")
    if os.path.exists(custom_file):
        try:
            with open(custom_file, encoding="utf-8") as f:
                custom = json.load(f)
            library.update(custom)
        except:
            pass

    return library


def save_custom_strategy(name: str, config: dict):
    """保存自定义策略"""
    custom_file = os.path.join(LEARNER_DIR, "custom_strategies.json")
    existing = {}
    if os.path.exists(custom_file):
        try:
            with open(custom_file, encoding="utf-8") as f:
                existing = json.load(f)
        except:
            pass

    existing[name] = config
    with open(custom_file, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    logger.info(f"策略已注册: {name}")


def match_strategies(market_style: str, risk_tolerance: str = "MEDIUM") -> list:
    """根据市场风格和风险偏好匹配策略"""
    library = get_strategy_library()
    matched = []

    risk_levels = {"LOW": ["低", "中低"], "MEDIUM": ["低", "中低", "中", "中高"],
                   "HIGH": ["中", "中高", "高", "极高"]}
    acceptable_risk = risk_levels.get(risk_tolerance, risk_levels["MEDIUM"])

    suitable_styles = {
        "TREND_UP": ["趋势上涨", "强势", "震荡偏多"],
        "TREND_DOWN": ["下跌末期/震荡", "熊市/震荡"],
        "SIDEWAYS": ["震荡", "下跌末期/震荡"],
        "VOLATILE": ["震荡", "趋势上涨"],
        "PANIC": ["下跌末期/震荡", "熊市/震荡"],
        "EUPHORIA": ["强势", "趋势上涨"],
    }

    market_keywords = suitable_styles.get(market_style, [])

    for name, cfg in library.items():
        # 风险匹配
        if cfg.get("risk_level", "中") not in acceptable_risk:
            continue
        # 市场匹配
        if market_keywords:
            matched_any = any(kw in cfg.get("suitable_market", "") for kw in market_keywords)
            if not matched_any:
                continue
        matched.append({"name": name, **cfg})

    # 按期望胜率排序
    matched.sort(key=lambda x: x.get("win_rate_expected", 0), reverse=True)
    return matched


def evaluate_strategy(name: str, trade_results: list) -> dict:
    """评估单个策略实战表现"""
    if not trade_results:
        return {"name": name, "status": "insufficient_data"}

    wins = sum(1 for t in trade_results if t.get("result") == "WIN")
    total = len(trade_results)
    avg_return = sum(t.get("pnl_pct", 0) for t in trade_results) / total
    max_drawdown = min(t.get("pnl_pct", 0) for t in trade_results)

    return {
        "name": name, "total_trades": total,
        "win_rate": round(wins / total, 3),
        "avg_return": round(avg_return, 2),
        "max_drawdown": round(max_drawdown, 2),
        "score": round((wins / total) * avg_return * 10, 3),  # 综合评分
    }


def get_daily_learning_summary() -> dict:
    """每日策略研习总结"""
    market_style = "SIDEWAYS"
    try:
        from layer7_evolution.adaptive_engine import detect_market_style
        market_style = detect_market_style()
    except:
        pass

    # 匹配当前最适合的策略
    top_strategies = match_strategies(market_style)

    # 策略库统计
    library = get_strategy_library()
    total = len(library)
    by_type = {}
    for name, cfg in library.items():
        tp = cfg.get("type", "其他")
        by_type[tp] = by_type.get(tp, 0) + 1

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "market_style": market_style,
        "recommended_strategies": top_strategies[:3],
        "total_strategies": total,
        "strategy_types": by_type,
    }
