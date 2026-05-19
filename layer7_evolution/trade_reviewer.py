"""自动复盘引擎 — 历史交易自动验证 + 模型淘汰 + 高胜率固化

核心流程：
1. 每日自动对比历史评分 vs 实际价格变化
2. 统计各策略/因子/信号的历史胜率
3. 识别高胜率模式 → 固化为交易模型
4. 识别低效模式 → 标记淘汰
5. 输出复盘报告 + 进化建议
"""
from __future__ import annotations

import json, os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("trade_reviewer")

REVIEW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "review")
os.makedirs(REVIEW_DIR, exist_ok=True)


def load_snapshots() -> list:
    """加载所有历史快照"""
    snap_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "backtest")
    if not os.path.exists(snap_dir):
        return []

    files = sorted(os.listdir(snap_dir))
    snapshots = []
    for f in files:
        if not f.startswith("snapshot_") or not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(snap_dir, f), encoding="utf-8") as fh:
                snapshots.append(json.load(fh))
        except:
            pass
    return snapshots


def verify_signals(snapshots: list, horizon_days: int = 5) -> list:
    """验证历史信号准确率"""
    if len(snapshots) < 2:
        return []

    results = []
    for i in range(len(snapshots) - 1):
        old = snapshots[i]
        new = snapshots[min(i + 1, len(snapshots) - 1)]

        old_date = old.get("date", "?")
        new_date = new.get("date", "?")

        for code, old_data in old.get("stocks", {}).items():
            new_data = new.get("stocks", {}).get(code)
            if not new_data:
                continue

            old_price = old_data.get("price")
            new_price = new_data.get("price")
            if not old_price or not new_price or old_price == 0:
                continue

            actual_return = (new_price / old_price - 1) * 100
            signal = old_data.get("signal", "HOLD")
            total = old_data.get("total", 5)
            audit_action = old_data.get("audit_action", "HOLD")

            # 判断正确性
            if signal in ("BUY", "WATCH") and actual_return > 0:
                correct = True
            elif signal == "AVOID" and actual_return < 0:
                correct = True
            elif signal == "HOLD" and abs(actual_return) < 3:
                correct = True
            elif audit_action == "ADD" and actual_return > 0:
                correct = True
            elif audit_action == "REDUCE" and actual_return < 0:
                correct = True
            else:
                correct = False

            results.append({
                "date": old_date, "code": code,
                "name": old_data.get("name", code),
                "signal": signal, "score": total,
                "audit_action": audit_action,
                "old_price": old_price, "new_price": new_price,
                "actual_return": round(actual_return, 2),
                "correct": correct,
            })

    return results


def analyze_factor_performance(results: list) -> dict:
    """分析各因子表现"""
    from collections import defaultdict

    # 按信号类型分析
    by_signal = defaultdict(list)
    for r in results:
        by_signal[r["signal"]].append(r)

    signal_stats = {}
    for sig, items in by_signal.items():
        if not items:
            continue
        correct = sum(1 for i in items if i["correct"])
        avg_ret = np.mean([i["actual_return"] for i in items])
        signal_stats[sig] = {
            "count": len(items),
            "win_rate": round(correct / len(items), 3),
            "avg_return": round(avg_ret, 2),
        }

    # 按评分区间分析
    by_score_range = defaultdict(list)
    for r in results:
        score = r.get("score", 5)
        if score >= 5.5:
            bucket = "高分(>=5.5)"
        elif score >= 4:
            bucket = "中分(4-5.5)"
        else:
            bucket = "低分(<4)"
        by_score_range[bucket].append(r)

    score_stats = {}
    for bucket, items in by_score_range.items():
        if not items:
            continue
        correct = sum(1 for i in items if i["correct"])
        avg_ret = np.mean([i["actual_return"] for i in items])
        score_stats[bucket] = {
            "count": len(items),
            "win_rate": round(correct / len(items), 3),
            "avg_return": round(avg_ret, 2),
        }

    return {"by_signal": signal_stats, "by_score_range": score_stats}


def identify_patterns(results: list) -> dict:
    """识别高胜率和低效模式"""
    if not results:
        return {}

    # 找出最佳和最差预测
    sorted_by_return = sorted(results, key=lambda x: x["actual_return"], reverse=True)
    top_wins = sorted_by_return[:5]
    top_losses = sorted_by_return[-5:]

    # 高胜率模式
    wins = [r for r in results if r["correct"]]
    losses = [r for r in results if not r["correct"]]

    # 信号+评分组合分析
    combo_stats = {}
    for r in results:
        key = f"{r['signal']}_{r['audit_action']}"
        if key not in combo_stats:
            combo_stats[key] = {"correct": 0, "total": 0, "returns": []}
        combo_stats[key]["total"] += 1
        if r["correct"]:
            combo_stats[key]["correct"] += 1
        combo_stats[key]["returns"].append(r["actual_return"])

    for k, v in combo_stats.items():
        v["win_rate"] = round(v["correct"] / v["total"], 3) if v["total"] > 0 else 0
        v["avg_return"] = round(np.mean(v["returns"]), 2) if v["returns"] else 0

    # 排序找最佳/最差组合
    ranked = sorted(combo_stats.items(), key=lambda x: x[1]["win_rate"], reverse=True)
    best_combo = ranked[0] if ranked else None
    worst_combo = ranked[-1] if ranked else None

    return {
        "top_wins": [{"name": r["name"], "signal": r["signal"],
                       "return": r["actual_return"]} for r in top_wins],
        "top_losses": [{"name": r["name"], "signal": r["signal"],
                         "return": r["actual_return"]} for r in top_losses],
        "best_combo": best_combo,
        "worst_combo": worst_combo,
        "total_correct": len(wins),
        "total_wrong": len(losses),
        "overall_win_rate": round(len(wins) / len(results), 3) if results else 0,
    }


def generate_review_report() -> dict:
    """生成完整复盘报告"""
    snapshots = load_snapshots()
    results = verify_signals(snapshots)
    factor_perf = analyze_factor_performance(results)
    patterns = identify_patterns(results)

    report = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "snapshots_count": len(snapshots),
        "verifications_count": len(results),
        "factor_performance": factor_perf,
        "patterns": patterns,
    }

    # 进化建议
    suggestions = []
    if patterns.get("overall_win_rate", 0) < 0.5:
        suggestions.append("整体胜率低于50%，建议重新审视因子权重")
    if patterns.get("worst_combo"):
        wc = patterns["worst_combo"]
        if wc[1]["win_rate"] < 0.3:
            suggestions.append(f"组合'{wc[0]}'胜率仅{wc[1]['win_rate']:.0%}，建议淘汰或优化")
    if patterns.get("best_combo"):
        bc = patterns["best_combo"]
        if bc[1]["win_rate"] > 0.7:
            suggestions.append(f"组合'{bc[0]}'胜率达{bc[1]['win_rate']:.0%}，建议固化加仓")
    if not suggestions:
        suggestions.append("当前策略表现稳定，继续保持")

    report["suggestions"] = suggestions

    # 保存
    f = os.path.join(REVIEW_DIR, f"review_{datetime.now().strftime('%Y%m%d')}.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    return report
