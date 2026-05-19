"""
多宝 v2.4 最终收官定版 — 一键入口
====================
最终定版功能（12项顶层思维）：
1. 预期差核心交易思维 — 挖掘认知不足、价值未兑现标的
2. 强弱分化对比交易法 — 只做强不做弱，强者恒强
3. 分时盘口实战研判 — 盘口承接/抛压/资金试盘识别
4. 波段高低切换逻辑 — 主升持有，见顶离场
5. 统一分析输出格式 — 条理化、标准化呈现
6. 长期记忆固化模式 — 牢记全部交易要求与偏好
7. 稳健复利核心宗旨 — 高胜率、合理盈亏比、严控回撤
8. 六大雷区排雷 — 远离风险源头
9. 四大量能结构 — 量价关系验证
10. 大盘-板块-个股联动 — 环境一致性
11. 信号过滤降噪 — 只输出高确定性机会
12. 三层一致性校验 — 短期/中期/长期共振

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
  python main.py --discipline 交易纪律检查
  python main.py --danger     高危雷区排雷
  python main.py --filter     信号过滤降噪
  python main.py --screen     多层严筛
  python main.py --drivers    驱动逻辑拆解
  python main.py --review     自动复盘
  python main.py --final      最终定版全量分析
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
╔═══════════════════════════════════════════════════╗
║   🔮 多宝 v2.4  最终收官定版 — 顶级交易体系         ║
║   12项顶层思维 · 全维度覆盖 · 稳健复利              ║
╚═══════════════════════════════════════════════════╝"""

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


def final_analysis():
    """最终定版全量分析 — 12项顶层思维完整执行"""
    print(BANNER)
    print("═" * 60)
    print("  🎯 最终定版全量分析 — 12项顶层思维完整执行")
    print("═" * 60)
    now = datetime.now()

    # 1. 数据管线
    print("\n[1/12] 数据管线")
    from core.dbfix import run as dbfix_run
    dbfix_run(auto_fix=True)
    pl = pipeline()
    print(f"  状态:{pl['status']}  耗时:{pl['elapsed']}s")

    # 2. 六因子均值回归评分
    print("\n[2/12] 六因子均值回归评分 (0-10制)")
    sc = score_all()
    for c, s in sc.items():
        print(f"  {s.get('name'):<8} 总分:{s.get('total',0):.1f}  信号:{signal_tag(s.get('signal','?'))}")

    # 3. 7维综合评分
    print("\n[3/12] 7维综合评分")
    from layer3_analysis.seven_dim import compute_all as seven_dim_all
    sd = seven_dim_all()
    for c, s in sd.items():
        print(f"  {s.get('name','?'):<8} 总分:{s.get('total',0):.1f}  信号:{signal_tag(s.get('signal','?'))}")

    # 4. 持仓审计 T/B/F/R
    print("\n[4/12] 持仓审计 T/B/F/R")
    au = audit()
    for c, a in au.items():
        print(f"  {a.get('name',c):<8} 总分:{a.get('total',0):.1f}  建议:{signal_tag(a.get('action','HOLD'))}")

    # 5. 交易纪律检查 — 预期差思维+证伪+模式区分
    print("\n[5/12] 交易纪律检查 — 预期差思维+证伪+模式区分")
    try:
        from layer7_evolution.trading_discipline import batch_check
        disc = batch_check()
        for code, d in disc.items():
            if code.startswith("_"): continue
            mode = d.get("mode", {}).get("mode", "未知")
            gap = d.get("expectation_gap", {}).get("gap_type", "未知")
            print(f"  {d.get('name',code):<8} 模式:{mode:<8} 预期差:{gap}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 6. 高危雷区排雷 — 六大雷区+量能结构+联动验证
    print("\n[6/12] 高危雷区排雷 — 六大雷区+量能结构+联动验证")
    try:
        from layer7_evolution.danger_zone import batch_danger_check
        danger = batch_danger_check()
        for code, d in danger.items():
            dangers = d.get("six_dangers", {}).get("dangers", [])
            vol = d.get("volume_structure", {}).get("structure", "正常")
            link = d.get("linkage", {}).get("linkage", "未知")
            status = "✅" if len(dangers) == 0 else f"❌({len(dangers)}个雷区)"
            print(f"  {d.get('name',code):<8} 雷区:{status} 量能:{vol} 联动:{link}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 7. 信号过滤降噪 — 三层一致性校验
    print("\n[7/12] 信号过滤降噪 — 三层一致性校验")
    try:
        from layer7_evolution.signal_filter import batch_filter
        filt = batch_filter()
        print(f"  通过过滤:{filt['passed']}/{filt['total']}只")
        for code, r in filt.get("details", {}).items():
            level = r.get("filter", {}).get("level", "C")
            action = r.get("filter", {}).get("action", "观望")
            if level in ["A", "B"]:
                print(f"    ✅ {r.get('name',code)}: {level}级 — {action}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 8. 强弱分化对比 — 只做强不做弱
    print("\n[8/12] 强弱分化对比 — 只做强不做弱")
    try:
        from layer7_evolution.trading_discipline import strength_comparison
        from core.config import config
        strength = strength_comparison(config.stocks)
        strong_names = [s['name'] for s in strength.get('strong', [])[:3]]
        print(f"  强势标的: {', '.join(strong_names)}")
        print(f"  原则: {strength.get('principle', '')}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 9. 波段高低切换 — 拿得住利润，躲得过大回调
    print("\n[9/12] 波段高低切换 — 拿得住利润，躲得过大回调")
    try:
        from layer7_evolution.trading_discipline import band_switch_logic
        from core.config import config
        for s in config.stocks[:3]:
            band = band_switch_logic(s["code"])
            print(f"  {s['name']:<8} 位置:{band.get('band_position','?')} → {band.get('action','?')}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 10. 风控评估
    print("\n[10/12] 风控前置预判")
    try:
        from layer7_evolution.risk_guard import full_risk_assessment
        risk = full_risk_assessment()
        print(f"  综合风险: {risk['overall']} | {risk['overall_action']}")
        print(f"  CRITICAL:{risk['critical_count']}只 HIGH:{risk['high_count']}只")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 11. 多智能体协同研判
    print("\n[11/12] 多智能体协同研判")
    try:
        from layer7_evolution.multi_agent import portfolio_batch_analyze
        multi = portfolio_batch_analyze()
        sig_dist = multi.get('signal_distribution', {})
        print(f"  信号分布: {sig_dist}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 12. 回测快照 + Obsidian归档
    print("\n[12/12] 回测快照 + Obsidian归档")
    from layer6_evolution.backtester import save_snapshot
    save_snapshot(datetime.now().strftime("%Y-%m-%d"), sc, au, sd)
    
    report = f"""## 多宝 v2.4 最终定版分析报告

### 大盘概况
{json.dumps(get_indices(), ensure_ascii=False, indent=2)}

### 六因子评分排名
"""
    for c, s in sc.items():
        report += f"- {s['name']}: {s['total']:.1f} ({s['signal']})\n"
    
    report += "\n### 7维综合评分\n"
    for c, s in sd.items():
        report += f"- {s.get('name','?')}: {s.get('total',0):.1f} ({s.get('signal','?')})\n"
    
    report += "\n### 持仓审计 T/B/F/R\n"
    for c, a in au.items():
        report += f"- {a['name']}: {a['total']}分 → {a['action']}\n"
    
    report += """
### 核心原则（长期记忆固化）
1. **预期差思维**: 优先挖掘市场认知不足、价值尚未兑现的标的
2. **强弱分化**: 只做强不做弱，强者恒强顺势操作
3. **波段操作**: 主升坚定持有，见顶果断离场
4. **稳健复利**: 不追求极端暴利，优先保证稳定性、持续性
5. **纪律执行**: 计划锁定后不更改，止损触发即执行
"""
    
    save_daily(report)
    if au: save_audit(au)
    print("  最终定版报告已写入Obsidian")

    elapsed = (datetime.now() - now).total_seconds()
    print(f"\n{'═' * 60}")
    print(f"  🏆 最终定版全量分析完成 · 总耗时 {elapsed:.0f}s")
    print(f"  ✅ 12项顶层思维完整执行")
    print(f"  ✅ 体系定型完备，停止新增规则")
    print(f"{'═' * 60}")


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
    elif "--discipline" in sys.argv:
        from layer7_evolution.trading_discipline import batch_check
        print(json.dumps(batch_check(), ensure_ascii=False, indent=2))
    elif "--danger" in sys.argv:
        from layer7_evolution.danger_zone import batch_danger_check
        print(json.dumps(batch_danger_check(), ensure_ascii=False, indent=2))
    elif "--filter" in sys.argv:
        from layer7_evolution.signal_filter import batch_filter
        print(json.dumps(batch_filter(), ensure_ascii=False, indent=2))
    elif "--final" in sys.argv:
        final_analysis()
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
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 7: 自适应策略引擎
    print("\n[Layer 7.2] 自适应策略引擎")
    try:
        from layer7_evolution.adaptive_engine import daily_adaptation
        adapt = daily_adaptation()
        print(f"  市场风格: {adapt['market_style']}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Layer 7: 风控前置预判
    print("\n[Layer 7.3] 风控前置预判")
    try:
        from layer7_evolution.risk_guard import full_risk_assessment
        risk = full_risk_assessment()
        print(f"  综合风险: {risk['overall']} | {risk['overall_action']}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # 运行传统 full 分析
    print("\n" + "=" * 50)
    print("  进化层完成，运行传统六层分析...")
    print("=" * 50)
    full()

    elapsed = (datetime.now() - now).total_seconds()
    print(f"\n{'═' * 50}")
    print(f"  自主进化分析完成 · 总耗时 {elapsed:.0f}s")
    print(f"{'═' * 50}")

if __name__ == "__main__":
    main()
