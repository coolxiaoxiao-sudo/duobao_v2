"""
多宝 v2.3 自主进化版 — 一键入口
====================
用法:
  python main.py              全量分析（含进化层）
  python main.py --brief      快速行情
  python main.py --audit      持仓审计
  python main.py --monitor    预警检查
  python main.py --selfcheck  系统自检
  python main.py --7dim       7维综合评分
  python main.py --backtest   回测评估
  python main.py --health     健康检查
  python main.py --dashboard  启动Web看板
  python main.py --evolve     自主进化运行（全模块）
  python main.py --risk       风控评估
  python main.py --scan       市场扫描
  python main.py --points     买卖临界点
  python main.py --multi      多智能体协同研判
  python main.py --learn      策略研习总结
  python main.py --cycle      跨周期联动分析
  python main.py --capital    资金层级拆解
  python main.py --valuation  动态估值锚定
  python main.py --events     事件驱动推演
  python main.py --emotion    情绪量化打分
  python main.py --peer       同行业横向对比
  python main.py --precision  多层精准测算
  python main.py --scenario   多场景策略适配
  python main.py --swan       黑天鹅防御
  python main.py --screen     多层严筛
  python main.py --drivers    驱动逻辑拆解
  python main.py --review     自动复盘
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
║   🔮 多宝 v2.3  自主进化股票分析系统    ║
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
    elif "--evolve" in sys.argv:
        evolve_full()
    elif "--risk" in sys.argv:
        from layer7_evolution.risk_guard import full_risk_assessment
        print(json.dumps(full_risk_assessment(), ensure_ascii=False, indent=2))
    elif "--scan" in sys.argv:
        from layer7_evolution.market_scanner import full_market_scan
        print(json.dumps(full_market_scan(), ensure_ascii=False, indent=2))
    elif "--points" in sys.argv:
        from layer7_evolution.critical_point import batch_compute_all
        print(json.dumps(batch_compute_all(), ensure_ascii=False, indent=2))
    elif "--multi" in sys.argv:
        from layer7_evolution.multi_agent import portfolio_batch_analyze
        print(json.dumps(portfolio_batch_analyze(), ensure_ascii=False, indent=2))
    elif "--learn" in sys.argv:
        from layer7_evolution.strategy_learner import get_daily_learning_summary
        print(json.dumps(get_daily_learning_summary(), ensure_ascii=False, indent=2))
    else:
        full()


def evolve_full():
    """自主进化完整运行 — v2.3 核心"""
    print(BANNER)
    print("=" * 50)
    now = datetime.now()

    # Layer 7: 市场底层逻辑扫描
    print("\n[Layer 7.1] 市场底层逻辑扫描")
    try:
        from layer7_evolution.market_scanner import full_market_scan
        scan = full_market_scan()
        print(f"  大盘形态: {scan['market_trend']['phase']}")
        print(f"  板块热度: {scan['sector_rotation'].get('rotation_signal','N/A')}")
        for code, sc in scan.get('stock_scans', {}).items():
            cyc = sc.get('cycle', {}).get('cycle', '?')
            manip = sc.get('manipulation', {}).get('pattern', '?')
            print(f"  {sc.get('name',code):<8} 周期:{cyc:<8} 主力:{manip}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 7: 自适应策略引擎
    print("\n[Layer 7.2] 自适应策略引擎")
    try:
        from layer7_evolution.adaptive_engine import daily_adaptation
        adapt = daily_adaptation()
        print(f"  市场风格: {adapt['market_style']} ({adapt['style_description'][:30]}...)")
        print(f"  仓位参数: 最大单票{adapt['adaptive_params']['max_position_pct']:.0%}, "
              f"现金{adapt['adaptive_params']['cash_reserve']:.0%}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 7: 风控前置预判
    print("\n[Layer 7.3] 风控前置预判")
    try:
        from layer7_evolution.risk_guard import full_risk_assessment
        risk = full_risk_assessment()
        print(f"  综合风险: {risk['overall']} | {risk['overall_action']}")
        print(f"  CRITICAL:{risk['critical_count']}只 HIGH:{risk['high_count']}只")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 7: 多智能体协同研判
    print("\n[Layer 7.4] 多智能体协同研判")
    try:
        from layer7_evolution.multi_agent import portfolio_batch_analyze
        multi = portfolio_batch_analyze()
        sig_dist = multi.get('signal_distribution', {})
        print(f"  信号分布: {sig_dist}")
        for code, r in multi.get('results', {}).items():
            v = r.get('verdict', {})
            if v:
                print(f"  {v.get('name',code):<8} 综合{v.get('final_score',0):.1f} "
                      f"信号:{v.get('signal','?')} 共识:{v.get('consensus','?')}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 7: 买卖临界点
    print("\n[Layer 7.5] 买卖临界点精算")
    try:
        from layer7_evolution.critical_point import batch_compute_all
        points = batch_compute_all()
        for code, pt in points.items():
            if 'error' in pt: continue
            print(f"  {pt.get('name',code):<8} 入:{pt.get('entry_point')} "
                  f"止盈1:{pt.get('take_profit_1')} 止损:{pt.get('stop_loss')}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 7: 策略研习
    print("\n[Layer 7.6] 策略研习")
    try:
        from layer7_evolution.strategy_learner import get_daily_learning_summary
        learn = get_daily_learning_summary()
        print(f"  可用策略: {learn['total_strategies']}个")
        for s in learn.get('recommended_strategies', [])[:3]:
            print(f"  推荐: {s['name']} ({s['type']}) 胜率{s['win_rate_expected']:.0%}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 7: 多层严筛
    print("\n[Layer 7.7] 多层严筛")
    try:
        from layer7_evolution.stock_screener import screen_portfolio
        scr = screen_portfolio()
        print(f"  精选池:{scr['elite']}只 关注:{scr['watch']}只 淘汰:{scr['reject']}只")
        if scr['elite_pool']:
            for e in scr['elite_pool'][:3]:
                print(f"    精选: {e['name']} 评分{e['score']}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 7: 驱动逻辑拆解
    print("\n[Layer 7.8] 驱动逻辑拆解")
    try:
        from layer7_evolution.driver_analyzer import batch_analyze_drivers
        drv = batch_analyze_drivers()
        grades = drv.get('grades', {})
        for g in ['A','B','C','D']:
            stocks = grades.get(g, [])
            if stocks:
                names = ', '.join(f"{s['name']}({s['net']:+d})" for s in stocks)
                print(f"  等级{g}: {names}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 7: 自动复盘
    print("\n[Layer 7.9] 自动复盘")
    try:
        from layer7_evolution.trade_reviewer import generate_review_report
        rev = generate_review_report()
        wr = rev.get('patterns', {}).get('overall_win_rate', 0)
        print(f"  历史胜率: {wr:.0%} | 快照数: {rev.get('snapshots_count',0)}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 8: 跨周期联动
    print("\n[Layer 8.1] 跨周期联动")
    try:
        from layer7_evolution.cross_cycle import batch_cross_cycle
        cyc = batch_cross_cycle()
        print(f"  多周期共振向上:{cyc.get('strong_bull',0)}只 向下:{cyc.get('strong_bear',0)}只")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 8: 资金层级拆解
    print("\n[Layer 8.2] 资金层级拆解")
    try:
        from layer7_evolution.capital_flow import batch_capital_flow
        cap = batch_capital_flow()
        for flow, stocks in cap.get('by_flow', {}).items():
            names = ', '.join(s['name'] for s in stocks[:3])
            print(f"  {flow}: {names}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 8: 动态估值
    print("\n[Layer 8.3] 动态估值锚定")
    try:
        from layer7_evolution.dynamic_valuation import batch_valuation
        val = batch_valuation()
        print(f"  估值分布: {val.get('zones', {})}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 8: 情绪量化
    print("\n[Layer 8.4] 情绪量化打分")
    try:
        from layer7_evolution.emotion_quant import full_emotion_analysis
        emo = full_emotion_analysis()
        m = emo.get('market', {})
        print(f"  大盘情绪: {m.get('stage')}({m.get('score')}) | {m.get('advice')[:30]}...")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 8: 黑天鹅防御
    print("\n[Layer 8.5] 黑天鹅前置防御")
    try:
        from layer7_evolution.black_swan import black_swan_defense
        swan = black_swan_defense()
        print(f"  防御等级: {swan.get('overall')} | {swan.get('defense_action')}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    print("\n[Layer 7.9] 自动复盘")
    try:
        from layer7_evolution.trade_reviewer import generate_review_report
        rev = generate_review_report()
        wr = rev.get('patterns', {}).get('overall_win_rate', 0)
        print(f"  历史胜率: {wr:.0%} | 快照数: {rev.get('snapshots_count',0)}")
        for sug in rev.get('suggestions', [])[:3]:
            print(f"  建议: {sug}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # 运行传统 full 分析

    print("\n" + "=" * 50)
    print("  进化层完成，运行传统六层分析...")
    print("=" * 50)
    full()

    elapsed = (datetime.now() - now).total_seconds()
    print(f"\n{'═' * 50}")
    print(f"  🧬 自主进化分析完成 · 总耗时 {elapsed:.0f}s")
    print(f"{'═' * 50}")

if __name__ == "__main__":
    main()
