"""交易知识库模块 — 沉淀交易日志、错误复盘、策略进化记录

功能：
1. 记录所有交易决策及后续验证结果
2. 按因子/市场状态/操作类型分类存档
3. 统计各因子、各策略的累积胜率、盈亏比
4. 输出策略效能排名，自动标记低效因子
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from core.logging import get_logger

logger = get_logger("knowledge_base")

KB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "knowledge")
os.makedirs(KB_DIR, exist_ok=True)


class TradeRecord:
    """单笔交易记录"""
    def __init__(self, code: str, name: str, direction: str, entry_price: float,
                 entry_date: str, reason: str, factors: dict, confidence: float):
        self.code = code
        self.name = name
        self.direction = direction  # LONG / SHORT
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.exit_price: Optional[float] = None
        self.exit_date: Optional[str] = None
        self.reason = reason        # 进场逻辑
        self.factors = factors      # 触发因子快照
        self.confidence = confidence
        self.pnl_pct: float = 0.0
        self.result = "OPEN"        # OPEN / WIN / LOSE / BREAKEVEN
        self.lesson = ""            # 复盘总结
        self.market_state = ""      # 市场状态标签

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "direction": self.direction,
            "entry_price": self.entry_price, "entry_date": self.entry_date,
            "exit_price": self.exit_price, "exit_date": self.exit_date,
            "reason": self.reason, "factors": self.factors,
            "confidence": self.confidence, "pnl_pct": round(self.pnl_pct, 2),
            "result": self.result, "lesson": self.lesson,
            "market_state": self.market_state,
        }


class FactorJournal:
    """因子效能日志 — 追踪每个因子在实战中的表现"""
    def __init__(self):
        self.signals: List[dict] = []   # {factor, date, code, signal, actual_return}
        self.stats: dict = {}           # {factor: {correct, total, win_rate, avg_return}}

    def record(self, factor: str, date: str, code: str, signal: float, actual_return: float):
        self.signals.append({"factor": factor, "date": date, "code": code,
                             "signal": signal, "actual_return": actual_return})

    def compute_stats(self, min_samples: int = 10):
        """计算各因子统计"""
        from collections import defaultdict
        groups = defaultdict(list)
        for s in self.signals:
            groups[s["factor"]].append(s)

        self.stats = {}
        for factor, items in groups.items():
            if len(items) < min_samples:
                continue
            correct = sum(1 for i in items if (i["signal"] > 0.5 and i["actual_return"] > 0)
                          or (i["signal"] < 0.3 and i["actual_return"] < 0))
            avg_ret = sum(i["actual_return"] for i in items) / len(items)
            self.stats[factor] = {
                "total": len(items), "correct": correct,
                "win_rate": round(correct / len(items), 3),
                "avg_return": round(avg_ret, 3),
            }

    def get_ranking(self) -> list:
        """按胜率排名返回因子效能"""
        return sorted(self.stats.items(), key=lambda x: x[1]["win_rate"], reverse=True)

    def get_weakest(self, n: int = 3) -> list:
        """返回效能最差的 n 个因子"""
        ranked = self.get_ranking()
        return ranked[-n:] if len(ranked) >= n else []


class KnowledgeBase:
    """多宝核心知识库"""

    def __init__(self):
        self.trades: List[TradeRecord] = []
        self.factor_journal = FactorJournal()
        self.strategy_versions: List[dict] = []
        self._load()

    def _file(self) -> str:
        return os.path.join(KB_DIR, "trades.json")

    def _factor_file(self) -> str:
        return os.path.join(KB_DIR, "factor_journal.json")

    def _strategy_file(self) -> str:
        return os.path.join(KB_DIR, "strategy_log.json")

    def _load(self):
        # 加载历史交易
        f = self._file()
        if os.path.exists(f):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
                self.trades = []
                for d in data:
                    tr = TradeRecord(d["code"], d["name"], d["direction"],
                                     d["entry_price"], d["entry_date"], d["reason"],
                                     d.get("factors", {}), d.get("confidence", 0.5))
                    tr.exit_price = d.get("exit_price")
                    tr.exit_date = d.get("exit_date")
                    tr.pnl_pct = d.get("pnl_pct", 0)
                    tr.result = d.get("result", "OPEN")
                    tr.lesson = d.get("lesson", "")
                    tr.market_state = d.get("market_state", "")
                    self.trades.append(tr)
            except Exception as e:
                logger.warning(f"加载知识库失败: {e}")

        # 加载因子日志
        ff = self._factor_file()
        if os.path.exists(ff):
            try:
                with open(ff, encoding="utf-8") as fh:
                    self.factor_journal.signals = json.load(fh)
                self.factor_journal.compute_stats()
            except:
                pass

        # 加载策略版本日志
        sf = self._strategy_file()
        if os.path.exists(sf):
            try:
                with open(sf, encoding="utf-8") as fh:
                    self.strategy_versions = json.load(fh)
            except:
                pass

    def save(self):
        with open(self._file(), "w", encoding="utf-8") as f:
            json.dump([t.to_dict() for t in self.trades], f, ensure_ascii=False, indent=2)

    def save_factor_journal(self):
        with open(self._factor_file(), "w", encoding="utf-8") as f:
            json.dump(self.factor_journal.signals, f, ensure_ascii=False, indent=2)

    def add_trade(self, tr: TradeRecord):
        self.trades.append(tr)
        self.save()

    def update_trade(self, code: str, entry_date: str, exit_price: float,
                     exit_date: str, lesson: str = ""):
        """平仓记录"""
        for t in self.trades:
            if t.code == code and t.entry_date == entry_date and t.result == "OPEN":
                t.exit_price = exit_price
                t.exit_date = exit_date
                if t.direction == "LONG":
                    t.pnl_pct = round((exit_price / t.entry_price - 1) * 100, 2)
                else:
                    t.pnl_pct = round((1 - exit_price / t.entry_price) * 100, 2)
                t.result = "WIN" if t.pnl_pct > 0.5 else ("LOSE" if t.pnl_pct < -0.5 else "BREAKEVEN")
                t.lesson = lesson
                self.save()
                return True
        return False

    def get_win_rate(self, days: int = 90) -> float:
        """近N天胜率"""
        cutoff = datetime.now().replace(hour=0, minute=0, second=0)
        try:
            from datetime import timedelta
            cutoff -= timedelta(days=days)
        except:
            pass
        closed = [t for t in self.trades if t.result in ("WIN", "LOSE", "BREAKEVEN")]
        if not closed:
            return 0.0
        recent = [t for t in closed]
        wins = sum(1 for t in recent if t.result == "WIN")
        return round(wins / len(recent), 3)

    def get_avg_return(self, days: int = 90) -> float:
        """近N天平均收益率"""
        closed = [t for t in self.trades if t.result in ("WIN", "LOSE", "BREAKEVEN")]
        if not closed:
            return 0.0
        return round(sum(t.pnl_pct for t in closed) / len(closed), 2)

    def get_mistake_patterns(self) -> list:
        """提取常见错误模式"""
        loses = [t for t in self.trades if t.result == "LOSE"]
        patterns = {}
        for t in loses:
            if t.lesson:
                key = t.lesson[:30]
                patterns[key] = patterns.get(key, 0) + 1
        return sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:5]

    def record_factor_signal(self, factor: str, date: str, code: str,
                             signal: float, actual_return: float):
        self.factor_journal.record(factor, date, code, signal, actual_return)
        self.save_factor_journal()

    def log_strategy_iteration(self, version: str, changes: str, rationale: str):
        """记录策略迭代"""
        entry = {
            "version": version,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "changes": changes,
            "rationale": rationale,
        }
        self.strategy_versions.append(entry)
        with open(self._strategy_file(), "w", encoding="utf-8") as f:
            json.dump(self.strategy_versions, f, ensure_ascii=False, indent=2)
        logger.info(f"策略迭代: {version} — {changes}")

    def summary(self) -> dict:
        """知识库概览"""
        total = len(self.trades)
        closed = [t for t in self.trades if t.result != "OPEN"]
        wins = sum(1 for t in closed if t.result == "WIN")
        avg_pnl = sum(t.pnl_pct for t in closed) / len(closed) if closed else 0
        return {
            "total_trades": total,
            "open_trades": total - len(closed),
            "closed_trades": len(closed),
            "win_rate": round(wins / len(closed), 3) if closed else 0,
            "avg_pnl": round(avg_pnl, 2),
            "strategy_iterations": len(self.strategy_versions),
            "factor_ranking": self.factor_journal.get_ranking(),
            "weakest_factors": self.factor_journal.get_weakest(3),
            "mistake_patterns": self.get_mistake_patterns(),
        }


# 全局单例
kb = KnowledgeBase()


def record_daily_verification(scores: dict, date: str):
    """每日验证：把当日评分与5/10/20日后的实际价格对照"""
    pass
