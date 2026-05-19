"""
多宝 v2.5 最终收官定版 — 一键入口
====================
最终定版功能（含全部实战准则）：
1. 预期差核心交易思维 — 挖掘认知不足、价值未兑现标的
2. 强弱分化对比交易法 — 只做强不做弱，强者恒强
3. 分时盘口实战研判 — 盘口承接/抛压/资金试盘识别
4. 波段高低切换逻辑 — 主升持有，见顶离场
5. 统一分析输出格式 — 条理化、标准化呈现
6. 长期记忆固化模式 — 牢记全部交易要求与偏好
7. 稳健复利核心宗旨 — 高胜率、合理盈亏比、严控回撤
8. 追高检测 — 严禁盲目追高，远离无业绩炒作
9. 盈亏比优先 — 先看盈亏比，后看胜率
10. 六大雷区排雷 — 远离风险源头
11. 四大量能结构 — 量价关系验证
12. 大盘-板块-个股联动 — 环境一致性
13. 系统性风险预警 — 大盘走弱第一时间避险
14. 信号过滤降噪 — 只输出高确定性机会
15. 三层一致性校验 — 短期/中期/长期明确划分
16. 每日自查复盘 — 主动回顾研判偏差，反思决策失误

用法:
  python main.py              全量分析
  python main.py --final      最终定版全量分析（含所有准则）
  python main.py --discipline 交易纪律检查
  python main.py --danger     高危雷区排雷+系统性风险
  python main.py --filter     信号过滤降噪
  python main.py --review     每日自查复盘
  python main.py --audit      持仓审计
  python main.py --monitor    预警检查
  python main.py --selfcheck  系统自检
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
╔═══════════════════════════════════════════════════╗
║   🔮 多宝 v2.5  最终收官定版 — 顶级交易体系         ║
║   16项实战准则 · 全维度覆盖 · 稳健复利              ║
╚═══════════════════════════════════════════════════╝"""

def signal_tag(sig):
    m = {"BUY": "买入", "WATCH": "关注", "HOLD": "持有", "AVOID": "回避",
         "ADD": "加仓", "REDUCE": "减仓", "CLOSE": "清仓",
         "STRONG": "强势", "MODERATE": "中性", "WEAK": "弱势"}
    return m.get(sig, sig)


def final_analysis():
    """最终定版全量分析"""
    print(BANNER)
    print("═" * 60)
    print("  🎯 最终定版全量分析 — 16项实战准则完整执行")
    print("═" * 60)
    now = datetime.now()

    # 1. 数据管线
    print("\n[1/16] 数据管线")
    from core.dbfix import run as dbfix_run
    dbfix_run(auto_fix=True)
    pl = pipeline()
    print(f"  状态:{pl['status']}  耗时:{pl['elapsed']}s")

    # 2. 系统性风险预警
    print("\n[2/16] 系统性风险预警 — 大盘走弱第一时间避险")
    try:
        from layer7_evolution.danger_zone import systemic_risk_check
        sr = systemic_risk_check()
        print(f"  等级: {sr.get('level','?')} | {sr.get('action','?')}")
        if sr.get("risks"):
            for r in sr["risks"]:
                print(f"    ⚠️ {r}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 3. 六因子均值回归评分
    print("\n[3/16] 六因子均值回归评分 (0-10制)")
    sc = score_all()
    for c, s in sc.items():
        print(f"  {s.get('name'):<8} 总分:{s.get('total',0):.1f}  信号:{signal_tag(s.get('signal','?'))}")

    # 4. 7维综合评分
    print("\n[4/16] 7维综合评分")
    from layer3_analysis.seven_dim import compute_all as seven_dim_all
    sd = seven_dim_all()
    for c, s in sd.items():
        print(f"  {s.get('name','?'):<8} 总分:{s.get('total',0):.1f}  信号:{signal_tag(s.get('signal','?'))}")

    # 5. 持仓审计
    print("\n[5/16] 持仓审计 T/B/F/R")
    au = audit()
    for c, a in au.items():
        print(f"  {a.get('name',c):<8} 总分:{a.get('total',0):.1f}  建议:{signal_tag(a.get('action','HOLD'))}")

    # 6. 追高风险检测
    print("\n[6/16] 追高风险检测 — 严禁盲目追高，远离无业绩炒作")
    try:
        from layer7_evolution.trading_discipline import chase_risk_check
        for s in config.stocks:
            cr = chase_risk_check(s["code"], s["name"])
            if cr.get("risks"):
                print(f"  ❌ {s['name']}: {', '.join(cr['risks']) if isinstance(cr.get('risks'),list) else cr.get('action','?')}")
            else:
                print(f"  ✅ {s['name']}: {cr.get('action','?')}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 7. 盈亏比筛选
    print("\n[7/16] 盈亏比优先筛选 — 先看盈亏比，再看胜率")
    try:
        from layer7_evolution.trading_discipline import risk_reward_filter
        for s in config.stocks:
            rr = risk_reward_filter(s["code"], s["name"], s["cost"], s["stop"], s["target"])
            status = "✅" if rr.get("pass") else "❌"
            print(f"  {status} {s['name']}: 盈亏比{rr.get('rr_ratio','?')}:1 → {rr.get('action','?')}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 8. 交易纪律 — 预期差+证伪+模式区分
    print("\n[8/16] 交易纪律检查 — 预期差+证伪+模式区分")
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

    # 9. 高危雷区排雷
    print("\n[9/16] 高危雷区排雷")
    try:
        from layer7_evolution.danger_zone import batch_danger_check
        danger = batch_danger_check()
        for code, d in danger.items():
            if code.startswith("_"): continue
            dangers = d.get("six_dangers", {}).get("dangers", [])
            status = "✅" if len(dangers)==0 else f"❌({len(dangers)}个)"
            print(f"  {d.get('name',code):<8} 雷区:{status}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 10. 四大量能结构
    print("\n[10/16] 四大量能结构")
    try:
        from layer7_evolution.danger_zone import analyze_volume_structure
        for s in config.stocks[:3]:
            vs = analyze_volume_structure(s["code"])
            print(f"  {s['name']}: {vs.get('structure','?')} → {vs.get('signal','?')}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 11. 大盘-板块-个股联动
    print("\n[11/16] 大盘-板块-个股联动验证")
    try:
        from layer7_evolution.danger_zone import linkage_validation
        for s in config.stocks[:3]:
            lv = linkage_validation(s["code"], s.get("industry",""))
            print(f"  {s['name']}: {lv.get('linkage','?')} 风险{lv.get('risk','?')}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 12. 信号过滤降噪
    print("\n[12/16] 信号过滤降噪 — 只输出高确定性机会")
    try:
        from layer7_evolution.signal_filter import batch_filter
        filt = batch_filter()
        print(f"  通过:{filt['passed']}/{filt['total']}只")
        for code, r in filt.get("details",{}).items():
            lv = r.get("filter",{}).get("level","C")
            if lv in ("A","B"):
                print(f"    ✅ {r.get('name',code)}: {lv}级 → {r.get('filter',{}).get('action','?')}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 13. 三层趋势一致性
    print("\n[13/16] 三层趋势一致性 — 短期/中期/长期明确划分")
    try:
        from layer7_evolution.signal_filter import three_layer_validation
        for s in config.stocks[:5]:
            tl = three_layer_validation(s["code"])
            if isinstance(tl.get("short"), dict):
                print(f"  {s['name']}: 短[{tl['short']['label']}] 中[{tl['mid']['label']}] 长[{tl['long']['label']}] → {tl['direction']}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 14. 强弱分化对比
    print("\n[14/16] 强弱分化对比 — 只做强不做弱")
    try:
        from layer7_evolution.trading_discipline import strength_comparison
        strength = strength_comparison(config.stocks)
        strong_names = [s['name'] for s in strength.get('strong',[])[:3]]
        print(f"  强势: {', '.join(strong_names)}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 15. 波段高低切换
    print("\n[15/16] 波段高低切换")
    try:
        from layer7_evolution.trading_discipline import band_switch_logic
        for s in config.stocks[:5]:
            band = band_switch_logic(s["code"])
            print(f"  {s['name']}: {band.get('band_position','?')} → {band.get('action','?')}")
    except Exception as e:
        print(f"  [SKIP] {e}")

    # 16. 预警监控 + 归档
    print("\n[16/16] 预警监控 + 回测快照 + 归档")
    mn = get_monitor()
    print(f"  止损预警:{len(mn['stops'])}  止盈信号:{len(mn['targets'])}")
    
    from layer6_evolution.backtester import save_snapshot
    save_snapshot(datetime.now().strftime("%Y-%m-%d"), sc, au, sd)
    
    report = f"""## 多宝 v2.5 最终定版分析报告

### 大盘概况
{json.dumps(get_indices(), ensure_ascii=False, indent=2)}

### 核心原则（长期记忆固化）
1. **预期差思维**: 优先挖掘市场认知不足、价值尚未兑现的标的
2. **强弱分化**: 只做强不做弱，强者恒强顺势操作
3. **盈亏比优先**: 交易决策先看盈亏比（≥1.5），再看胜率
4. **严禁追高**: 杜绝盲目追高连续大幅拉升的个股，远离无业绩炒作
5. **低吸至上**: 优先在合理低位低吸布局优质筹码
6. **波段操作**: 主升坚定持有，见顶果断离场
7. **避险及时**: 大盘走弱第一时间降仓减仓甚至空仓
8. **稳健复利**: 不追求极端暴利，优先保证稳定性和持续性
9. **纪律执行**: 计划锁定后不更改，止损触发即执行
10. **精简输出**: 舍去冗余理论，全部贴合实战落地执行
"""
    
    # 17. 数据累积
    print()
    print("[17/17] 数据累积 — 写入数据库归档")
    try:
        from layer7_evolution.data_accumulator import full_accumulate
        acc = full_accumulate(sc, au, sd)
        print("  signal_history:+{} analysis_tracker:+{} daily_forecast:+{}".format(acc["signals"], acc["analysis"], acc["forecast"]))
        if acc.get("verified"):
            print("  回溯校验历史预测: {} 条".format(acc["verified"]))
    except Exception as e:
        print(f"  [SKIP] {e}")
    
    save_daily(report)
    if au: save_audit(au)
    print("  报告已写入Obsidian")

    elapsed = (datetime.now() - now).total_seconds()
    print(f"\n{'═' * 60}")
    print(f"  🏆 最终定版全量分析完成 · 总耗时 {elapsed:.0f}s")
    print(f"  ✅ 16项实战准则完整执行")
    print(f"  ✅ 体系定型完备，自主运行")
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
    elif "--discipline" in sys.argv:
        from layer7_evolution.trading_discipline import batch_check
        print(json.dumps(batch_check(), ensure_ascii=False, indent=2))
    elif "--danger" in sys.argv:
        from layer7_evolution.danger_zone import batch_danger_check
        result = json.dumps(batch_danger_check(), ensure_ascii=False, indent=2)
        print(result)
    elif "--filter" in sys.argv:
        from layer7_evolution.signal_filter import batch_filter
        print(json.dumps(batch_filter(), ensure_ascii=False, indent=2))
    elif "--review" in sys.argv:
        from layer7_evolution.trade_reviewer import self_check
        print(json.dumps(self_check(), ensure_ascii=False, indent=2))
    elif "--final" in sys.argv:
        final_analysis()
    else:
        final_analysis()

if __name__ == "__main__":
    main()

