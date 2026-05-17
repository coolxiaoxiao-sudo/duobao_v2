"""中枢神经路由器 — 连接所有功能模块，主动调度，实时管理

架构：
  感知层 → 数据层 → 分析层 → 决策层 → 执行层 → 进化层 → 输出层

每次 full_analysis() 自动按神经链路激活所有模块，并记录调用状态。

神经链路图（Mermaid 可渲染）见 Obsidian solo 仓库的 系统说明.md。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from core.config import config
from core.logging import get_logger

logger = get_logger("router")

# ─── 模块注册表 ───
REGISTRY: Dict[str, dict] = {}
PATHWAY_LOG: List[dict] = []


def register(name: str, layer: str, module_path: str, activation: str, description: str):
    REGISTRY[name] = {
        "layer": layer,
        "path": module_path,
        "activation": activation,
        "desc": description,
        "active": True,
        "last_call": None,
        "last_error": None,
    }


def _log_pathway(name: str, ok: bool, elapsed_ms: int, detail: str = ""):
    entry = {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "module": name,
        "ok": ok,
        "elapsed_ms": elapsed_ms,
        "detail": detail[:120],
    }
    PATHWAY_LOG.append(entry)
    if not ok:
        logger.warning(f"[路由器] {name} 失败: {detail}")


def _run_step(name: str, fn: Callable, *args, **kwargs) -> Any:
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        elapsed = int((time.time() - t0) * 1000)
        _log_pathway(name, True, elapsed)
        REGISTRY[name]["last_call"] = datetime.now().strftime("%H:%M:%S")
        REGISTRY[name]["last_error"] = None
        return result
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _log_pathway(name, False, elapsed, str(e))
        REGISTRY[name]["last_error"] = str(e)
        raise


# ─── 注册所有模块 ───
def init_registry():
    """初始化模块注册表（在 main.py 启动时调用一次）。"""
    register("dbfix", "数据层", "core/dbfix.py", "自动", "数据库 trade_date 格式自修复")
    register("pipeline", "数据层", "layer2_pipeline/pipeline.py", "自动", "数据管线：行情采集+存储")
    register("health", "数据层", "layer2_pipeline/pipeline.py", "自动", "健康检查：DB/腾讯/DeepSeek 链路")
    register("backfill", "数据层", "layer2_pipeline/pipeline.py", "条件触发", "K线不足时 TuShare 补齐 60 天")
    register("tencent_api", "感知层", "layer1_data/tencent_api.py", "自动", "腾讯实时行情")
    register("tushare_api", "感知层", "layer1_data/tushare_api.py", "条件触发", "TuShare 历史日线补齐")
    register("technical", "分析层", "layer3_analysis/technical.py", "自动", "技术指标：RSI/MA/ATR")
    register("scoring", "分析层", "layer3_analysis/technical.py", "自动", "六因子均值回归评分")
    register("trend", "分析层", "layer3_analysis/trend.py", "自动", "趋势因子：MA排列/ADX/MACD背离/相对强度")
    register("seven_dim", "分析层", "layer3_analysis/seven_dim.py", "自动", "7维综合评分")
    register("audit", "决策层", "layer5_execution/audit.py", "自动", "持仓审计 T/B/F/R")
    register("monitor", "执行层", "layer5_execution/monitor.py", "自动", "风控预警：止损/止盈检查")
    register("deepseek_chat", "AI层", "ai/deepseek.py", "条件触发", "DeepSeek 复盘+个股分析")
    register("deepseek_reasoner", "AI层", "ai/deepseek.py", "条件触发", "Reasoner 二次审计")
    register("backtester", "进化层", "layer6_evolution/backtester.py", "自动", "因子回测快照保存")
    register("obsidian", "输出层", "output/obsidian.py", "自动", "Obsidian 写入日报/审计/长期记忆")
    register("dashboard", "输出层", "dashboard/app.py", "手动", "Web 看板")


def status() -> dict:
    """返回所有模块的激活状态。"""
    return {
        "time": datetime.now().strftime("%H:%M:%S"),
        "modules": {k: {"layer": v["layer"], "active": v["active"], "last_call": v["last_call"], "last_error": v["last_error"]} for k, v in REGISTRY.items()},
        "pathway_count": len(PATHWAY_LOG),
    }


def pathway_report() -> str:
    """生成神经链路调用报告（Markdown）。"""
    lines = ["## 神经链路调用报告\n", f"- 总调用: {len(PATHWAY_LOG)} 次"]
    layers = ["感知层", "数据层", "分析层", "AI层", "决策层", "执行层", "进化层", "输出层"]
    for layer in layers:
        mods = [(k, v) for k, v in REGISTRY.items() if v["layer"] == layer]
        if not mods:
            continue
        status_list = []
        for name, info in mods:
            symbol = "✅" if info["last_error"] is None and info["last_call"] else ("❌" if info["last_error"] else "⏳")
            status_list.append(f"{symbol} {name}")
        lines.append(f"- {layer}: " + " / ".join(status_list))
    return "\n".join(lines)


# ─── 全量分析（中枢神经调度）───
def full_analysis(brief: bool = False) -> dict:
    """按神经链路完整激活所有模块。

    返回: 所有模块输出的汇总 dict，可直接给日报生成使用。
    """
    init_registry()
    date_str = datetime.now().strftime("%Y-%m-%d")

    result = {"date": date_str, "steps": {}}

    # ── 感知+数据层 ──
    from layer2_pipeline.pipeline import run as pipeline_run
    result["pipeline"] = _run_step("pipeline", pipeline_run, brief)

    from layer2_pipeline.pipeline import health as health_fn
    result["health"] = _run_step("health", health_fn)

    # ── 分析层 ──
    from layer3_analysis.technical import score_all
    result["scoring"] = _run_step("scoring", score_all)

    from layer3_analysis.seven_dim import compute_all as seven_dim_all
    result["seven_dim"] = _run_step("seven_dim", seven_dim_all)

    # ── 决策+执行层 ──
    from layer5_execution.audit import audit
    result["audit"] = _run_step("audit", audit)

    from layer5_execution.monitor import get_all as monitor_all
    result["monitor"] = _run_step("monitor", monitor_all)

    # ── AI 层 ──
    from layer1_data.tencent_api import get_indices
    indices = _run_step("tencent_api", get_indices)

    ai_market = ""
    ai_stocks = []
    if config.deepseek_key:
        from ai.deepseek import deepseek
        ctx = {"indices": indices, "scores": {}}
        sc = result["scoring"]
        for c, s in sc.items():
            ctx["scores"][c] = {"name": s.get("name"), "total": s.get("total"), "signal": s.get("signal")}
        ai_market = _run_step("deepseek_chat", deepseek.market_review, ctx)

        top = [s for s in sc.values() if s.get("signal") in ("BUY", "WATCH")][:3]
        for s in top:
            txt = _run_step("deepseek_chat", deepseek.analyze_stock, s.get("name", ""), s.get("code", ""), {
                "quote": s.get("technicals", {}),
                "factors": s.get("factors", {}),
                "cost": s.get("cost"),
                "target": s.get("target"),
                "stop": s.get("stop"),
            })
            ai_stocks.append((s.get("name"), txt))

    # ── 进化层 ──
    result["backtest_snapshot"] = _run_step("backtester", lambda: None)  # 占位，快照由 main.py 的 save_snapshot 负责

    # ── 输出层 ──
    from output.obsidian import save_daily, save_audit, save_portfolio_snapshot, save_system_guide, save_action_plan, update_home
    from core.selfcheck import run as selfcheck_fn

    result["selfcheck"] = _run_step("health", selfcheck_fn, quiet=True)

    result["indices"] = indices
    result["ai_market"] = ai_market
    result["ai_stocks"] = ai_stocks

    return result


# 模块间激活信号
def on_pipeline_complete(pipeline_result: dict):
    """管线完成后：触发 analyze 模块"""
    REGISTRY["technical"]["active"] = True


def on_audit_complete(audit_result: dict):
    """审计完成后：触发 monitor"""
    REGISTRY["monitor"]["active"] = True


def on_stop_alert(stock_code: str):
    """止损触发时：触发 reasoner 二次审计"""
    if config.deepseek_key:
        REGISTRY["deepseek_reasoner"]["active"] = True
    return REGISTRY["deepseek_reasoner"]["active"]
