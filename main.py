"""
多宝 v2.6 最终收官定版 — 7层架构完整
====================
Layer 1: 数据采集    Layer 2: 数据管线    Layer 3: 多维分析
Layer 4: 决策融合    Layer 5: 审计执行    Layer 6: 回测进化
Layer 7: 自主进化    Database: investment.db 数据累积

用法:
  python main.py              全量分析（默认 --final）
  python main.py --decide     Layer4 决策融合
  python main.py --discipline 交易纪律检查
  python main.py --danger     高危雷区排雷+系统性风险
  python main.py --filter     信号过滤降噪
  python main.py --review     每日自查复盘
  python main.py --audit      持仓审计 T/B/F/R
  python main.py --monitor    预警检查
  python main.py --selfcheck  系统自检
  python main.py --dashboard  Web看板
"""
import json, sys, os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from core import config
from core.logging import get_logger
from layer1_data.tencent_api import get_indices
from layer2_pipeline.pipeline import run as pipeline, health
from layer3_analysis.technical import score_all
from layer5_execution.audit import audit
from layer5_execution.monitor import get_all as get_monitor
from output.obsidian import save_daily, save_audit

logger = get_logger("main")

BANNER = """
╔═══════════════════════════════════════════════════╗
║   🔮 多宝 v2.6  7层架构完整 · 决策融合 · 稳健复利  ║
╚═══════════════════════════════════════════════════╝"""

def signal_tag(sig):
    m = {"BUY": "买入", "WATCH": "关注", "HOLD": "持有", "AVOID": "回避",
         "ADD": "加仓", "REDUCE": "减仓", "CLOSE": "清仓",
         "STRONG": "强势", "MODERATE": "中性", "WEAK": "弱势"}
    return m.get(sig, sig)

def decision_emoji(d):
    return {"BUY": "🟢", "ADD": "🔵", "HOLD": "⚪", "REDUCE": "🟡", "AVOID": "🔴"}.get(d, "⚪")


def final_analysis():
    """全量分析 — 7层+决策融合"""
    print(BANNER)
    print("═" * 60)
    print("  🎯 全量分析 — 7层架构 + Layer4决策融合")
    print("═" * 60)
    now = datetime.now()

    # Layer 1+2: 数据
    print("\n[Layer 1+2] 数据采集+管线")
    from core.dbfix import run as dbfix_run
    dbfix_run(auto_fix=True)
    pl = pipeline()
    print(f"  状态:{pl['status']}  耗时:{pl['elapsed']}s")

    # 系统性风险
    print("\n[风险前置] 系统性风险预警")
    try:
        from layer7_evolution.danger_zone import systemic_risk_check
        sr = systemic_risk_check()
        print(f"  等级: {sr.get('level','?')} | {sr.get('action','?')}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # Layer 3: 多维分析
    print("\n[Layer 3] 多维分析")
    sc = score_all()
    from layer3_analysis.seven_dim import compute_all as seven_dim_all
    sd = seven_dim_all()
    for c, s in sc.items():
        s7 = sd.get(c, {}).get("total", 0)
        print("  {:<8} 六因子:{:.1f} 7维:{:.0f} {}".format(s.get('name'), s.get('total',0), s7, signal_tag(s.get('signal','?'))))

    # Layer 5: 审计
    print("\n[Layer 5] 持仓审计 T/B/F/R")
    au = audit()
    for c, a in au.items():
        print("  {:<8} T/B/F/R:{:.1f} {}".format(a.get('name',c), a.get('total',0), signal_tag(a.get('action','HOLD'))))

    # === Layer 4: 决策融合（核心新增） ===
    print("\n" + "═" * 60)
    print("  [Layer 4] 🔥 决策融合引擎 — 8道门控逐级筛选")
    print("═" * 60)
    try:
        from layer4_decision.decision_engine import decide_all, summary
        decision = decide_all(sc, sd, au)
        print("  决策分布:", decision.get("distribution", {}))
        print()
        for code, r in decision.get("ranked", []):
            details = decision["details"].get(code, {})
            dd = details.get("decision", {})
            ds = details.get("scores", {})
            veto = details.get("veto", [])
            em = decision_emoji(dd.get("final", "HOLD"))
            print("  {} {:<8} {:<6} 综合{:.1f} 仓位{} 置信度{}".format(
                em, r["name"], dd.get("final","HOLD"),
                ds.get("综合", 0), dd.get("position_level","?"), dd.get("confidence","?")))
            if veto:
                for v in veto:
                    print("    ❌ " + v)
            rationale = dd.get("rationale", "")
            if rationale:
                print("    → " + rationale)
    except Exception as e:
        print("  [SKIP] " + str(e))
        decision = None
    
    # Layer 7: 专项检查
    print("\n[Layer 7] 专项检查")
    try:
        from layer7_evolution.trading_discipline import chase_risk_check, risk_reward_filter
        for s in config.stocks[:5]:
            chase = chase_risk_check(s["code"], s["name"])
            rr = risk_reward_filter(s["code"], s["name"], s["cost"], s["stop"], s["target"])
            chase_ok = "✅" if chase.get("pass") else "❌({}项)".format(len(chase.get("risks",[])))
            print("  {:<8} 追高:{} 盈亏比:{:.1f}:1".format(s["name"], chase_ok, rr.get("rr_ratio",0)))
    except Exception as e:
        print("  [SKIP] " + str(e))

    # 信号过滤
    print()
    try:
        from layer7_evolution.signal_filter import batch_filter, three_layer_validation
        filt = batch_filter()
        print("  信号过滤: {}/{}只通过".format(filt["passed"], filt["total"]))
        for s in config.stocks[:5]:
            tl = three_layer_validation(s["code"])
            if isinstance(tl.get("short"), dict):
                print("  {:<8} 短[{}] 中[{}] 长[{}]".format(
                    s["name"], tl["short"]["label"], tl["mid"]["label"], tl["long"]["label"]))
    except Exception as e:
        print("  [SKIP] " + str(e))

    # 预警监控
    print()
    mn = get_monitor()
    print("  止损预警:{} 止盈信号:{}".format(len(mn["stops"]), len(mn["targets"])))

    # 回测快照
    from layer6_evolution.backtester import save_snapshot
    save_snapshot(datetime.now().strftime("%Y-%m-%d"), sc, au, sd)

    # 数据累积
    print()
    try:
        from layer7_evolution.data_accumulator import full_accumulate
        acc = full_accumulate(sc, au, sd)
        print("  数据累积: signal_history:+{} analysis:+{} forecast:+{} 校验:{}".format(
            acc["signals"], acc["analysis"], acc["forecast"], acc.get("verified", 0)))
    except Exception as e:
        print("  [SKIP] " + str(e))

    # 报告
    report = "## 多宝 v2.6 分析报告\n\n### 大盘\n" + json.dumps(get_indices(), ensure_ascii=False, indent=2)
    if decision:
        report += "\n\n### Layer4 决策\n"
        for code, r in decision.get("ranked", []):
            d = decision["details"][code]["decision"]
            report += "- {} {}: {} 仓位:{}\n".format(r["name"], r["decision"], d.get("rationale",""), d.get("position_level",""))
    save_daily(report)
    if au: save_audit(au)
    print("  报告已写入Obsidian")

    elapsed = (datetime.now() - now).total_seconds()
    print("\n" + "═" * 60)
    print("  🏆 完成 · {}s · 7层架构完整".format(int(elapsed)))
    print("═" * 60)


def main():
    if "--dashboard" in sys.argv:
        from dashboard.app import run as run_dash
        return run_dash()
    if "--selfcheck" in sys.argv:
        from core.selfcheck import run as selfcheck_run
        selfcheck_run(print_json=False)
    elif "--7dim" in sys.argv:
        from layer3_analysis.seven_dim import compute_all as seven_dim_all
        print(json.dumps(seven_dim_all(), ensure_ascii=False, indent=2))
    elif "--brief" in sys.argv:
        print(json.dumps(pipeline(True), ensure_ascii=False, indent=2))
    elif "--audit" in sys.argv:
        print(json.dumps(audit(), ensure_ascii=False, indent=2))
    elif "--monitor" in sys.argv:
        print(json.dumps(get_monitor(), ensure_ascii=False, indent=2))
    elif "--health" in sys.argv:
        print(json.dumps(health(), ensure_ascii=False, indent=2))
    elif "--backtest" in sys.argv:
        from layer6_evolution.backtester import evaluate
        print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
    elif "--decide" in sys.argv:
        sc = score_all()
        from layer3_analysis.seven_dim import compute_all as seven_dim_all
        sd = seven_dim_all()
        au = audit()
        from layer4_decision.decision_engine import decide_all
        print(json.dumps(decide_all(sc, sd, au), ensure_ascii=False, indent=2))
    elif "--discipline" in sys.argv:
        from layer7_evolution.trading_discipline import batch_check
        print(json.dumps(batch_check(), ensure_ascii=False, indent=2))
    elif "--danger" in sys.argv:
        from layer7_evolution.danger_zone import batch_danger_check
        print(json.dumps(batch_danger_check(), ensure_ascii=False, indent=2))
    elif "--filter" in sys.argv:
        from layer7_evolution.signal_filter import batch_filter
        print(json.dumps(batch_filter(), ensure_ascii=False, indent=2))
    elif "--review" in sys.argv:
        from layer7_evolution.trade_reviewer import self_check
        print(json.dumps(self_check(), ensure_ascii=False, indent=2))
    else:
        final_analysis()

if __name__ == "__main__":
    main()
