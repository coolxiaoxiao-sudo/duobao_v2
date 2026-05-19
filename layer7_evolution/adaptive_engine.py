"""自适应策略引擎 — 动态权重调整 + 市场风格识别 + 仓位规则优化

核心能力：
1. 感知当前市场风格（趋势/震荡/恐慌/亢奋）
2. 根据风格动态调整因子权重
3. 优化仓位规则和止盈止损参数
4. 定期自我评估，剔除低效逻辑
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("adaptive_engine")

ADAPTIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "adaptive")
os.makedirs(ADAPTIVE_DIR, exist_ok=True)

# 市场风格定义
MARKET_STYLES = {
    "TREND_UP": "趋势上涨 — 权重向趋势因子倾斜，放宽止盈，收紧止损",
    "TREND_DOWN": "趋势下跌 — 权重向超卖/支撑因子倾斜，收紧止损，快速止盈",
    "SIDEWAYS": "震荡整理 — 权重向波动收敛/均值回归倾斜，网格思维",
    "VOLATILE": "高波动 — 权重向风控倾斜，收紧仓位，扩大止损容忍",
    "PANIC": "恐慌杀跌 — 权重向超卖/估值倾斜，现金为王",
    "EUPHORIA": "亢奋追涨 — 权重向RSI/资金面倾斜，警惕反转",
}


def detect_market_style(indices: dict = None) -> str:
    """感知当前市场风格"""
    if indices is None:
        try:
            from layer1_data.tencent_api import get_indices
            indices = get_indices()
        except:
            return "SIDEWAYS"

    # 从指数推断
    trends = []
    for name, data in indices.items():
        if not isinstance(data, dict):
            continue
        pct = data.get("pct_chg", 0) or 0
        vol = data.get("volume_ratio", 1) or 1
        trends.append({"name": name, "pct": pct, "vol_ratio": vol})

    if not trends:
        return "SIDEWAYS"

    avg_pct = np.mean([t["pct"] for t in trends])
    avg_vol = np.mean([t["vol_ratio"] for t in trends])

    if avg_pct < -3 and avg_vol > 1.5:
        return "PANIC"
    elif avg_pct > 2 and avg_vol > 1.5:
        return "EUPHORIA"
    elif avg_pct > 1:
        return "TREND_UP"
    elif avg_pct < -1:
        return "TREND_DOWN"
    elif avg_vol > 1.5:
        return "VOLATILE"
    else:
        return "SIDEWAYS"


def get_adaptive_weights(style: str) -> dict:
    """根据市场风格动态调权"""
    base = config.weights.copy()
    if not base:
        base = {"回撤深度": 0.0155, "支撑强度": 0.1789, "波动收敛": 0.3327,
                "超卖强度": 0.1944, "连跌衰竭": 0.1079, "量价背离": 0.1705}

    adjustments = {
        "TREND_UP": {"支撑强度": 1.3, "波动收敛": 0.7, "超卖强度": 0.6},
        "TREND_DOWN": {"超卖强度": 1.5, "量价背离": 1.3, "支撑强度": 1.2, "波动收敛": 0.6},
        "SIDEWAYS": {"波动收敛": 1.3, "支撑强度": 1.2, "回撤深度": 1.3},
        "VOLATILE": {"支撑强度": 0.7, "波动收敛": 0.6, "连跌衰竭": 0.7},
        "PANIC": {"超卖强度": 1.8, "支撑强度": 1.4, "量价背离": 1.5, "波动收敛": 0.3},
        "EUPHORIA": {"超卖强度": 0.4, "量价背离": 0.6, "连跌衰竭": 0.5},
    }

    adj = adjustments.get(style, {})
    result = {}
    total = 0
    for k, v in base.items():
        factor = adj.get(k, 1.0)
        result[k] = v * factor
        total += result[k]

    # 重新归一化
    if total > 0:
        result = {k: v / total for k, v in result.items()}

    return result


def get_adaptive_params(style: str) -> dict:
    """根据市场风格调整仓位/止损/止盈参数"""
    base_params = {
        "max_position_pct": 0.30,       # 单票最大仓位
        "stop_loss_pct": -0.08,         # 止损线
        "take_profit_pct": 0.20,        # 止盈线
        "trailing_stop_pct": 0.05,      # 移动止损回撤
        "max_drawdown_tolerance": 0.15, # 最大回撤容忍
        "cash_reserve": 0.20,           # 现金储备
    }

    adjustments = {
        "TREND_UP": {
            "max_position_pct": 0.35, "stop_loss_pct": -0.06,
            "take_profit_pct": 0.25, "trailing_stop_pct": 0.07,
            "cash_reserve": 0.10,
        },
        "TREND_DOWN": {
            "max_position_pct": 0.15, "stop_loss_pct": -0.05,
            "take_profit_pct": 0.10, "trailing_stop_pct": 0.03,
            "cash_reserve": 0.50,
        },
        "SIDEWAYS": {
            "max_position_pct": 0.20, "stop_loss_pct": -0.06,
            "take_profit_pct": 0.12,
        },
        "VOLATILE": {
            "max_position_pct": 0.15, "stop_loss_pct": -0.10,
            "take_profit_pct": 0.15, "cash_reserve": 0.35,
        },
        "PANIC": {
            "max_position_pct": 0.10, "stop_loss_pct": -0.04,
            "take_profit_pct": 0.08,
            "max_drawdown_tolerance": 0.10, "cash_reserve": 0.70,
        },
        "EUPHORIA": {
            "max_position_pct": 0.25, "stop_loss_pct": -0.12,
            "take_profit_pct": 0.30, "trailing_stop_pct": 0.10,
        },
    }

    adj = adjustments.get(style, {})
    result = {**base_params, **adj}
    return result


def compute_position_size(code: str, score: float, confidence: float,
                          style: str, portfolio_value: float = 100000) -> tuple:
    """计算建议仓位 — 返回 (股数, 仓位占比, 建议)
    根据：评分×置信度 + 市场风格 + 最大仓位规则
    """
    params = get_adaptive_params(style)
    max_pct = params["max_position_pct"]
    cash_reserve = params["cash_reserve"]

    # 评分映射到仓位 (5分=半仓max, 10分=满仓max)
    score_factor = max(0, (score - 2.5) / 7.5) if score > 2.5 else 0

    # 置信度因子
    conf_factor = min(1.5, max(0.3, confidence * 1.5))

    # 最终仓位占比
    position_pct = score_factor * max_pct * conf_factor
    # 现金储备约束
    position_pct = min(position_pct, 1 - cash_reserve)

    # 分散度控制（与持仓数成反比）
    n_stocks = len(config.stocks)
    if n_stocks > 5:
        position_pct = min(position_pct, 0.25)

    # 建议标签
    if position_pct > 0.2:
        suggestion = "重仓"
    elif position_pct > 0.1:
        suggestion = "标准仓位"
    elif position_pct > 0.05:
        suggestion = "轻仓"
    else:
        suggestion = "观望/不参与"

    amount = portfolio_value * position_pct
    return (round(amount, 0), round(position_pct * 100, 1), suggestion)


def evaluate_strategy_efficacy(factor_weights: dict, lookback_days: int = 60) -> dict:
    """评估当前策略效能 — 滑动窗口验证
    返回各因子的实际IC，识别低效因子
    """
    try:
        from layer6_evolution.backtester import evaluate
        result = evaluate(horizon_days=lookback_days)
        return {
            "status": result.get("status", "unknown"),
            "win_rate": result.get("win_rate", 0),
            "buy_avg_return": result.get("buy_avg_return", 0),
            "factor_discrimination": result.get("factor_discrimination", 0),
        }
    except Exception as e:
        logger.warning(f"策略评估失败: {e}")
        return {"status": "error", "message": str(e)}


def get_evolution_log() -> list:
    """读取策略进化日志"""
    log_file = os.path.join(ADAPTIVE_DIR, "evolution_log.json")
    if os.path.exists(log_file):
        try:
            with open(log_file, encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return []


def log_evolution(version: str, action: str, detail: dict):
    """记录进化事件"""
    log_file = os.path.join(ADAPTIVE_DIR, "evolution_log.json")
    logs = get_evolution_log()
    logs.append({
        "version": version,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "detail": detail,
    })
    # 只保留最近500条
    if len(logs) > 500:
        logs = logs[-500:]
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


def daily_adaptation() -> dict:
    """每日自适应检查 — 感知市场 → 调整参数 → 评估效能 → 记录日志"""
    style = detect_market_style()
    weights = get_adaptive_weights(style)
    params = get_adaptive_params(style)
    efficacy = evaluate_strategy_efficacy(weights)

    log_evolution("v2.2", "daily_adaptation", {
        "market_style": style,
        "weights": {k: round(v, 4) for k, v in weights.items()},
        "params": params,
        "efficacy": efficacy,
    })

    description = MARKET_STYLES.get(style, "未知风格")
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "market_style": style,
        "style_description": description,
        "adaptive_weights": {k: round(v, 4) for k, v in weights.items()},
        "adaptive_params": params,
        "efficacy": efficacy,
    }
