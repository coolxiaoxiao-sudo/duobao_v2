"""盈亏归因细分库 — 踏空/拿不住/追高/抄底过早/逻辑错误分类优化

目标：每一类错误只犯一次，持续压缩决策失误率
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List

from core.config import config
from core.logging import get_logger

logger = get_logger("pnl_attribution")

ATTR_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "attribution")
os.makedirs(ATTR_DIR, exist_ok=True)


# 错误类型定义
ERROR_TYPES = {
    "踏空": {
        "desc": "看好但未买入，错过上涨",
        "cause": ["犹豫观望", "等待回调", "仓位不足", "被其他标的占用资金"],
        "solution": "设好买点直接挂条件单，不追求完美买点",
    },
    "拿不住": {
        "desc": "过早卖出，错过后续涨幅",
        "cause": ["恐惧回撤", "小利即安", "被洗盘震出", "缺乏趋势信仰"],
        "solution": "移动止盈法，不破关键均线不出",
    },
    "追高": {
        "desc": "高位买入，随即回调被套",
        "cause": ["FOMO情绪", "追涨杀跌", "突破假信号", "缺乏耐心"],
        "solution": "严格区分真突破与假突破，放量突破后回踩确认再进",
    },
    "抄底过早": {
        "desc": "左侧买入，继续下跌深套",
        "cause": ["试图买在最低点", "忽视趋势", "估值陷阱", "接飞刀"],
        "solution": "等底部结构确认（双底/头肩底），不猜底",
    },
    "逻辑错误": {
        "desc": "分析逻辑错误，导致方向判断错误",
        "cause": ["信息不全", "过度自信", "锚定效应", "幸存者偏差"],
        "solution": "多维度交叉验证，设置证伪条件",
    },
    "止损不及时": {
        "desc": "跌破止损线未执行，损失扩大",
        "cause": ["侥幸心理", "不愿割肉", "幻想反弹", "沉没成本"],
        "solution": "机械止损，触发即执行，不犹豫",
    },
    "止盈过早": {
        "desc": "趋势未结束即止盈，错失主升浪",
        "cause": ["恐高", "小利即安", "缺乏趋势跟踪"],
        "solution": "让利润奔跑，移动止盈",
    },
    "仓位失控": {
        "desc": "单票仓位过重或过轻",
        "cause": ["过度看好", "恐惧", "缺乏仓位管理规则"],
        "solution": "单票不超过30%，按确定性分级配置",
    },
}


def record_trade_outcome(code: str, name: str, direction: str, entry_price: float,
                         exit_price: float, entry_date: str, exit_date: str,
                         error_type: str = "", notes: str = "") -> dict:
    """记录交易结果及归因"""
    pnl_pct = (exit_price / entry_price - 1) * 100 if direction == "LONG" else (1 - exit_price / entry_price) * 100

    # 自动识别错误类型
    auto_error = ""
    if error_type == "":
        if pnl_pct > 20 and "拿不住" not in notes:
            auto_error = "拿不住"  # 大涨但提前卖
        elif pnl_pct < -15 and "止损不及时" not in notes:
            auto_error = "止损不及时"  # 深套
        elif pnl_pct < -5 and entry_price > exit_price * 1.1:
            auto_error = "追高"  # 高位买入

    record = {
        "code": code, "name": name, "direction": direction,
        "entry_price": entry_price, "exit_price": exit_price,
        "entry_date": entry_date, "exit_date": exit_date,
        "pnl_pct": round(pnl_pct, 2),
        "error_type": error_type or auto_error,
        "notes": notes,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # 保存到文件
    f = os.path.join(ATTR_DIR, "trade_records.json")
    records = []
    if os.path.exists(f):
        try:
            with open(f, encoding="utf-8") as fh:
                records = json.load(fh)
        except:
            pass
    records.append(record)
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)

    return record


def analyze_errors() -> dict:
    """分析错误分布及改进建议"""
    f = os.path.join(ATTR_DIR, "trade_records.json")
    if not os.path.exists(f):
        return {"error": "暂无交易记录"}

    with open(f, encoding="utf-8") as fh:
        records = json.load(fh)

    # 按错误类型统计
    error_counts = {}
    error_pnl = {}
    for r in records:
        et = r.get("error_type", "其他")
        if et:
            error_counts[et] = error_counts.get(et, 0) + 1
            if et not in error_pnl:
                error_pnl[et] = []
            error_pnl[et].append(r.get("pnl_pct", 0))

    # 计算各错误类型的平均亏损
    error_stats = {}
    for et, pnls in error_pnl.items():
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0
        error_stats[et] = {
            "count": error_counts[et],
            "avg_pnl": round(avg_pnl, 2),
            "total_loss": round(sum(p for p in pnls if p < 0), 2),
        }

    # 排序找出最严重错误
    sorted_errors = sorted(error_stats.items(), key=lambda x: x[1]["total_loss"])

    # 生成改进建议
    suggestions = []
    for et, stats in sorted_errors[:3]:
        if et in ERROR_TYPES:
            info = ERROR_TYPES[et]
            suggestions.append({
                "error_type": et,
                "count": stats["count"],
                "total_loss": stats["total_loss"],
                "solution": info["solution"],
            })

    return {
        "total_trades": len(records),
        "error_distribution": error_stats,
        "top_errors": sorted_errors[:3],
        "improvement_plan": suggestions,
    }


def get_error_summary() -> dict:
    """获取错误总结"""
    analysis = analyze_errors()
    if "error" in analysis:
        return analysis

    summary = f"共记录{analysis['total_trades']}笔交易，"
    if analysis["top_errors"]:
        top = analysis["top_errors"][0]
        summary += f"最严重错误：{top[0]}（{top[1]['count']}次，总亏损{top[1]['total_loss']}%）"

    return {
        "summary": summary,
        "details": analysis,
        "error_types": list(ERROR_TYPES.keys()),
    }
