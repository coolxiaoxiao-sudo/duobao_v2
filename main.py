"""
多宝 v2.0 — 一键入口
====================
用法:
  python main.py              全量分析
  python main.py --brief      快速行情
  python main.py --audit      持仓审计
  python main.py --monitor    预警检查
  python main.py --selfcheck  系统自检
  python main.py --7dim       7维综合评分
  python main.py --backtest   回测评估
  python main.py --health     健康检查
  python main.py --dashboard  启动Web看板
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
from ai.deepseek import deepseek
from output.obsidian import save_daily, save_audit

logger = get_logger("main")

BANNER = """
╔══════════════════════════════════════╗
║   🔮 多宝 v2.0  股票分析系统         ║
║   7层架构 · DeepSeek驱动 · SOLO调度   ║
╚══════════════════════════════════════╝"""

def signal_tag(sig):
    m = {"BUY": "买入", "WATCH": "关注", "HOLD": "持有", "AVOID": "回避",
         "ADD": "加仓", "REDUCE": "减仓", "CLOSE": "清仓",
         "STRONG": "强势", "MODERATE": "中性", "WEAK": "弱势"}
    return m.get(sig, sig)


def full():
    print(BANNER)
    print("═" * 50)
    now = datetime.now()

    # 0. 数据库自修复
    from core.dbfix import run as dbfix_run
    dbfix_run(auto_fix=True)

    # 1. 管线
    print("\n[1/6] 数据管线")
    pl = pipeline()
    print(f"  状态:{pl['status']}  耗时:{pl['elapsed']}s")

    # 2. 六因子均值回归评分
    print("\n[2/6] 六因子均值回归评分 (0-10制)")
    sc = score_all()
    for c, s in sc.items():
        print(f"  {s.get('name'):<8} 总分:{s.get('total',0):.1f}  信号:{signal_tag(s.get('signal','?'))}")

    # 3. 7维综合评分
    print("\n[3/6] 7维综合评分")
    from layer3_analysis.seven_dim import compute_all as seven_dim_all
    sd = seven_dim_all()
    for c, s in sd.items():
        dims = s.get("dimensions", {})
        print(f"  {s.get('name','?'):<8} 总分:{s.get('total',0):.1f}  信号:{signal_tag(s.get('signal','?'))}")

    # 4. 持仓审计 T/B/F/R
    print("\n[4/6] 持仓审计 T/B/F/R")
    au = audit()
    for c, a in au.items():
        print(f"  {a.get('name',c):<8} 总分:{a.get('total',0):.1f}  建议:{signal_tag(a.get('action','HOLD'))}")

    # 5. 预警监控
    print("\n[5/6] 预警监控")
    mn = get_monitor()
    print(f"  止损预警:{len(mn['stops'])}  止盈信号:{len(mn['targets'])}")
    for a in mn["stops"]:
        print(f"    {a['severity']} {a['name']}: {a['type']} 现价{a['price']} 止损{a['stop']}")

    # 6. 回测快照 + DeepSeek AI
    print("\n[6/6] DeepSeek AI + 回测快照")
    from layer6_evolution.backtester import save_snapshot, evaluate
    save_snapshot(datetime.now().strftime("%Y-%m-%d"), sc, au, sd)

    if not config.deepseek_key:
        print("  [SKIP] Key未配置")
        report = f"## 大盘概况\n{json.dumps(get_indices(), ensure_ascii=False, indent=2)}\n\n## 六因子评分排名\n"
        for c, s in sc.items():
            report += f"- {s['name']}: {s['total']:.1f} ({s['signal']})\n"
        report += "\n## 7维综合评分\n"
        for c, s in sd.items():
            report += f"- {s.get('name','?')}: {s.get('total',0):.1f} ({s.get('signal','?')})\n"
        report += "\n## 持仓审计\n"
        for c, a in au.items():
            report += f"- {a['name']}: {a['total']}分 → {a['action']}\n"
        save_daily(report)
        if au: save_audit(au)
        print("  日报已写入Obsidian")
    else:
        ctx = {"indices": get_indices(), "scores": {}}
        for c, s in sc.items():
            ctx["scores"][c] = {"name": s["name"], "total": s["total"], "signal": s["signal"]}
        review = deepseek.market_review(ctx)
        top = sorted(sc.values(), key=lambda x: x.get("total", 0) or 0, reverse=True)[:3]
        reports = []
        for s in top:
            rr = deepseek.analyze_stock(s["name"], s["code"], {
                "quote": s.get("technicals", {}),
                "factors": s.get("factors", {}),
                "cost": s.get("cost"), "target": s.get("target"), "stop": s.get("stop"),
            })
            reports.append(f"## {s['name']}\n{rr}")
        full_report = f"## AI大盘复盘\n{review}\n\n---\n\n## AI个股分析\n{chr(10).join(reports)}"
        save_daily(full_report)
        if au: save_audit(au)
        print(f"  {review[:300]}...")
        print("  AI报告已写入Obsidian")

    elapsed = (datetime.now() - now).total_seconds()
    print(f"\n{'═' * 50}")
    print(f"  分析完成 · 耗时 {elapsed:.0f}s")
    print(f"{'═' * 50}")


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
    else:
        full()

if __name__ == "__main__":
    main()
