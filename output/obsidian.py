"""Obsidian 输出 — 将分析结果自动写入笔记库"""
import os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import config
from core.logging import get_logger
logger = get_logger("obsidian_out")

def _vault(): return config.get("system", "obsidian_vault", default="")

def save_daily(report_text, date_str=None):
    if not config.get("notifications", "obsidian", "enabled", default=True): return
    ds = date_str or datetime.now().strftime("%Y-%m-%d")
    d = os.path.join(_vault(), config.get("notifications", "obsidian", "daily_report_path", default="30-日报"))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"盘后报告-{ds}.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(f"---\ndate: {ds}\ntags: [日报, 盘后报告]\n---\n\n# 盘后报告 {ds}\n\n{report_text}\n\n---\n> [[../00-主页/HOME|← 返回主页]]\n")
    logger.info(f"日报已存: {p}")

def save_audit(audit_data, date_str=None):
    if not config.get("notifications", "obsidian", "enabled", default=True): return
    ds = date_str or datetime.now().strftime("%Y-%m-%d")
    d = os.path.join(_vault(), config.get("notifications", "obsidian", "trade_log_path", default="10-交易/交易日志"))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"持仓审计-{ds}.md")
    lines = [f"---\ndate: {ds}\ntags: [审计, 持仓]\n---\n\n# 持仓审计 {ds}\n"]
    for c, a in audit_data.items():
        sc = a.get("scores", {})
        lines.append(f"## {a.get('name','?')} — {a.get('action','?')} (总分 {a.get('total','?')})\n")
        lines.append(f"- 现价: {a.get('price','?')} | 成本: {a.get('cost','?')} | RSI: {a.get('rsi','?')}")
        lines.append(f"- T趋势:{sc.get('T','?')} B估值:{sc.get('B','?')} F因子:{sc.get('F','?')} R风险:{sc.get('R','?')} | MA:{a.get('ma_status','?')}\n")
    with open(p, "w", encoding="utf-8") as f: f.write("\n".join(lines))
    logger.info(f"审计已存: {p}")

def save_portfolio_snapshot(seven_dim_data, date_str=None):
    ds = date_str or datetime.now().strftime("%Y-%m-%d")
    d = os.path.join(_vault(), config.get("notifications", "obsidian", "trade_log_path", default="10-交易/交易日志"))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"7维快照-{ds}.md")
    lines = [f"---\ndate: {ds}\ntags: [7维, 快照]\n---\n\n# 7维评分快照 {ds}\n"]
    for c, s in seven_dim_data.items():
        dims = s.get("dimensions", {})
        lines.append(f"## {s.get('name','?')} — {s.get('signal','?')} ({s.get('total','?')})")
        lines.append(f"  趋势:{dims.get('trend','?')} 均值回归:{dims.get('mean_reversion','?')} 波动:{dims.get('volatility','?')} 量价:{dims.get('volume_price','?')} 估值:{dims.get('valuation','?')} 基本面:{dims.get('fundamental','?')} 相对强度:{dims.get('rel_strength','?')}\n")
    with open(p, "w", encoding="utf-8") as f: f.write("\n".join(lines))
    logger.info(f"7维快照已存: {p}")

def save_system_guide(guide_text: str):
    d = os.path.join(_vault(), "20-系统")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "系统说明.md")
    with open(p, "w", encoding="utf-8") as f: f.write(guide_text)
    logger.info(f"系统说明已存: {p}")

def save_action_plan(plan_text: str, date_str=None):
    ds = date_str or datetime.now().strftime("%Y-%m-%d")
    d = os.path.join(_vault(), config.get("notifications", "obsidian", "trade_log_path", default="10-交易/交易日志"))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"行动计划-{ds}.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(f"---\ndate: {ds}\ntags: [行动]\n---\n\n# 行动计划 {ds}\n\n{plan_text}\n")
    logger.info(f"行动计划已存: {p}")

def update_home(content: str):
    d = os.path.join(_vault(), "00-主页")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "HOME.md")
    with open(p, "w", encoding="utf-8") as f: f.write(content)
    logger.info("主页已更新")
