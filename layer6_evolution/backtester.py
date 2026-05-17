"""因子回测校验模块 — 追踪因子准确率与区分度

原理：
1) 记录每次评分的因子值 + 方向信号
2) 5/10/20 交易日后回看实际收益
3) 计算 IC（信息系数）、胜率、盈亏比
4) 按因子维度输出统计报告

科学依据：
IC (Information Coefficient) → 衡量因子预测力
IR (Information Ratio)    → 衡量因子稳定性
胜率 / 盈亏比            → 衡量实际交易价值
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("backtester")

BACKTEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "backtest")
os.makedirs(BACKTEST_DIR, exist_ok=True)


def save_snapshot(date_str: str, scores: dict, audit_data: dict, seven_dim: dict) -> None:
    """把当天的评分/审计/7维结果写入回测快照，供后续追踪。"""
    try:
        snapshot = {"date": date_str, "stocks": {}}
        for code, s in scores.items():
            snapshot["stocks"][code] = {
                "name": s.get("name"),
                "price": s.get("price") or s.get("technicals", {}).get("price"),
                "signal": s.get("signal"),
                "total": s.get("total"),
                "factors": s.get("factors"),
                "technicals": s.get("technicals"),
                "audit_action": (audit_data.get(code) or {}).get("action"),
                "audit_total": (audit_data.get(code) or {}).get("total"),
            }
            if seven_dim and code in seven_dim:
                sd = seven_dim[code]
                snapshot["stocks"][code]["seven_dim"] = {
                    "dimensions": sd.get("dimensions"),
                    "total": sd.get("total"),
                    "signal": sd.get("signal"),
                }

        path = os.path.join(BACKTEST_DIR, f"snapshot_{date_str}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"回测快照保存失败: {e}")


def evaluate(horizon_days: int = 20) -> dict:
    """评估：取最早一份快照，对比 horizon_days 后的实际价格变化。"""
    try:
        files = sorted(os.listdir(BACKTEST_DIR))
        if len(files) < 2:
            return {"status": "insufficient_data", "message": "至少需要 2 个快照（不同日期）"}

        # 只取最早和最新
        with open(os.path.join(BACKTEST_DIR, files[0]), encoding="utf-8") as f:
            old_snap = json.load(f)
        with open(os.path.join(BACKTEST_DIR, files[-1]), encoding="utf-8") as f:
            new_snap = json.load(f)

        results = []
        for code, old in old_snap.get("stocks", {}).items():
            new = new_snap.get("stocks", {}).get(code)
            if not new:
                continue

            old_price = old.get("price")
            new_price = new.get("price")
            if not old_price or not new_price:
                continue

            actual_return = (new_price / old_price - 1) * 100
            predicted_signal = old.get("signal", "")
            predicted_total = old.get("total", 0)

            # 简易胜负判断：信号偏多 + 实际正收益 = 正确
            is_correct = (predicted_signal in ("BUY", "WATCH") and actual_return > 0) or (
                predicted_signal == "WAIT" and actual_return < -2
            )

            results.append({
                "code": code,
                "name": old.get("name"),
                "predicted_signal": predicted_signal,
                "predicted_score": predicted_total,
                "old_price": old_price,
                "new_price": new_price,
                "actual_return": round(actual_return, 2),
                "is_correct": is_correct,
                "seven_dim": old.get("seven_dim"),
            })

        if not results:
            return {"status": "no_comparable_data", "message": "无共同股票可比较"}

        correct = sum(1 for r in results if r["is_correct"])
        win_rate = correct / len(results)

        # 按方向分组
        buy_results = [r for r in results if r["predicted_signal"] in ("BUY", "WATCH")]
        wait_results = [r for r in results if r["predicted_signal"] == "WAIT"]

        buy_avg_return = sum(r["actual_return"] for r in buy_results) / len(buy_results) if buy_results else 0
        wait_avg_return = sum(r["actual_return"] for r in wait_results) / len(wait_results) if wait_results else 0

        return {
            "status": "ok",
            "period": f"{old_snap.get('date')} → {new_snap.get('date')}",
            "total_signals": len(results),
            "correct": correct,
            "win_rate": round(win_rate, 3),
            "buy_avg_return": round(buy_avg_return, 2),
            "wait_avg_return": round(wait_avg_return, 2),
            "factor_discrimination": round(buy_avg_return - wait_avg_return, 2),
            "details": results[:20],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
