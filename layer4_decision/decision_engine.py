"""Layer 4 决策融合引擎 — 综合 Layer3+Layer5+Layer7 输出统一决策

门控逻辑（逐级否决）:
Gate 1: 系统性风险 -> 大盘走弱则整体降仓
Gate 2: 追高检测   -> 击中追高->不买
Gate 3: 六大雷区   -> >=3个雷区->不买
Gate 4: 证伪检查   -> 强烈证伪->不买
Gate 5: 盈亏比     -> <1.5->降级, <1->拒绝
Gate 6: 三层一致性 -> 不一致->降级
Final: 加权综合 六因子(0.35)+7维(0.25)+审计(0.20)+趋势(0.10)+盈亏比(0.10) -> 输出决策
"""
from __future__ import annotations
import json, os
from datetime import datetime
from core.config import config
from core.logging import get_logger

logger = get_logger("decision_engine")
DECISION_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "decisions")
os.makedirs(DECISION_DIR, exist_ok=True)

CORE_PRINCIPLES = [
    "预期差优先: 挖掘市场认知不足、价值未兑现标的",
    "强弱分化: 只做强不做弱，弱势坚决放弃",
    "盈亏比优先: 盈亏比>=1.5才参与，<1严禁",
    "严禁追高: 连续拉升/RSI过热/无业绩炒作一律不追",
    "系统避险: 大盘走弱第一时间降仓减仓或空仓",
    "三层一致: 短中长三期趋势必须共振才确认",
    "稳健复利: 不追求极端暴利，严控回撤优先",
]

def decide(code, name, industry, cost, stop, target, six_factor, seven_dim, audit_result):
    """单票综合决策 — 门控逻辑 + 加权融合"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    sf_total = six_factor.get("total", 5)
    sf_signal = six_factor.get("signal", "HOLD")
    sd_total = seven_dim.get("total", 5)
    sd_signal = seven_dim.get("signal", "STRONG")
    aud_total = audit_result.get("total", 5)
    aud_action = audit_result.get("action", "HOLD")
    
    gates = []
    veto = []
    rr_ratio = 1.5
    danger_count = 0
    chase_risks = []
    fa_verdict = "未知"
    band_pos = "未知"
    gap_type = "中等预期"
    direction = "未知"
    trend_score = 5
    
    # Gate 1: 系统性风险
    systemic_level = "安全"
    try:
        from layer7_evolution.danger_zone import systemic_risk_check
        systemic_level = systemic_risk_check().get("level", "安全")
    except: pass
    
    # Gate 2: 追高检测
    try:
        from layer7_evolution.trading_discipline import chase_risk_check
        chase = chase_risk_check(code, name)
        chase_risks = chase.get("risks", [])
        if not chase.get("pass", True) and len(chase_risks) >= 3:
            veto.append("Gate2追高: " + "; ".join(chase_risks[:2]))
        elif chase_risks:
            gates.append("Gate2追高: " + "; ".join(chase_risks[:2]))
    except: pass
    
    # Gate 3: 六大雷区
    try:
        from layer7_evolution.danger_zone import check_six_dangers
        danger_result = check_six_dangers(code, name)
        danger_count = danger_result.get("count", 0)
        dangers = danger_result.get("dangers", [])
        if danger_count >= 3:
            veto.append("Gate3雷区: " + "; ".join(dangers[:2]))
        elif danger_count >= 1:
            gates.append("Gate3雷区: " + "; ".join(dangers[:2]))
    except: pass
    
    # Gate 4: 证伪检查
    try:
        from layer7_evolution.trading_discipline import falsification_analysis
        fa = falsification_analysis(code, name)
        fa_verdict = fa.get("verdict", "")
        if "强烈证伪" in fa_verdict or "显著证伪" in fa_verdict:
            veto.append("Gate4证伪: " + fa_verdict)
        elif "部分证伪" in fa_verdict:
            gates.append("Gate4证伪: " + fa_verdict)
    except: pass
    
    # Gate 5: 盈亏比
    try:
        from layer7_evolution.trading_discipline import risk_reward_filter
        rr = risk_reward_filter(code, name, cost, stop, target)
        rr_ratio = rr.get("rr_ratio", 1.5)
        rr_level = rr.get("level", "C")
        if rr_level == "F":
            veto.append("Gate5盈亏比: {:.1f}:1 < 1:1".format(rr_ratio))
        elif rr_level == "D":
            gates.append("Gate5盈亏比: {:.1f}:1 勉强".format(rr_ratio))
    except: pass
    
    # Gate 6: 三层一致性
    try:
        from layer7_evolution.signal_filter import three_layer_validation
        tl = three_layer_validation(code)
        consistent = tl.get("consistent", False)
        direction = tl.get("direction", "")
        if not consistent:
            gates.append("Gate6三层: 周期分歧")
        else:
            gates.append("Gate6三层: " + direction)
    except: pass
    
    # Gate 7: 波段位置
    try:
        from layer7_evolution.trading_discipline import band_switch_logic
        band = band_switch_logic(code)
        band_pos = band.get("band_position", "未知")
        band_action = band.get("action", "")
        gates.append("Gate7波段: {} -> {}".format(band_pos, band_action))
    except: pass
    
    # Gate 8: 预期差
    try:
        from layer7_evolution.trading_discipline import expectation_gap_analysis
        gap = expectation_gap_analysis(code, name, industry)
        gap_type = gap.get("gap_type", "中等预期")
        gates.append("Gate8预期差: " + gap_type)
    except: pass
    
    # Gate 9: 趋势分
    try:
        from layer3_analysis.trend import compute_all as trend_compute
        tr = trend_compute(code, 60)
        trend_score = tr.get("trend_total", 5)
    except: pass
    
    # ===== 综合评分 =====
    composite = sf_total * 0.35 + sd_total * 0.25 + aud_total * 0.20 + (trend_score - 5) * 0.10
    
    rr_bonus = max(0, min((rr_ratio - 1) * 0.5, 1.0))
    composite += rr_bonus * 0.10
    composite = round(max(0, min(10, composite)), 1)
    
    # 系统性风险降权
    systemic_penalty = {"一级预警": 2.0, "二级预警": 1.0, "三级关注": 0.5}.get(systemic_level, 0)
    final_score = max(0, composite - systemic_penalty)
    
    # ===== 最终决策 =====
    if len(veto) >= 2:
        final_decision = "AVOID"
        confidence = 9
        rationale = "多重否决: " + " | ".join(veto[:2])
    elif len(veto) == 1:
        final_decision = "AVOID"
        confidence = 8
        rationale = "否决: " + veto[0]
    elif final_score >= 8:
        final_decision = "BUY"
        confidence = round(final_score)
        rationale = "高分共振: 六因子{:.1f}+7维{:.0f}+审计{:.1f}".format(sf_total, sd_total, aud_total)
    elif final_score >= 6.5:
        final_decision = "ADD"
        confidence = round(final_score)
        rationale = "趋势确立，可加仓"
    elif final_score >= 5:
        final_decision = "HOLD"
        confidence = round(final_score)
        rationale = "持有观望"
    elif final_score >= 3.5:
        final_decision = "REDUCE"
        confidence = round(final_score)
        rationale = "信号偏弱，建议减仓"
    else:
        final_decision = "AVOID"
        confidence = round(max(3, final_score))
        rationale = "评分过低，回避"
    
    # 仓位建议
    pos_map = {"AVOID": (0, "空仓"), "REDUCE": (0.10, "轻仓"), "HOLD": (0.25, "半仓"), "ADD": (0.30, "半仓"), "BUY": (0.35, "重仓")}
    pos_pct, pos_level = pos_map[final_decision]
    if systemic_level != "安全" and final_decision in ("BUY", "ADD"):
        pos_level = "半仓" if systemic_level in ("二级预警","三级关注") else "轻仓"
    
    return {
        "code": code, "name": name, "timestamp": now,
        "scores": {"六因子": round(sf_total,1), "7维": sd_total, "审计": round(aud_total,1), "趋势": trend_score, "综合": round(final_score,1)},
        "gates": gates, "veto": veto, "systemic": systemic_level,
        "decision": {"final": final_decision, "confidence": confidence, "rationale": rationale, "position_pct": pos_pct, "position_level": pos_level},
        "details": {"追高": len(chase_risks), "雷区": danger_count, "盈亏比": round(rr_ratio,1), "证伪": fa_verdict, "三层": direction, "波段": band_pos, "预期差": gap_type},
    }


def decide_all(scores, seven_dim, audit_data):
    """全组合决策"""
    results = {}
    
    for s in config.stocks:
        code = s["code"]
        sf = scores.get(code, {"total": 5, "signal": "HOLD"})
        sd = seven_dim.get(code, {"total": 5, "signal": "STRONG"})
        au = audit_data.get(code, {"total": 5, "action": "HOLD"})
        results[code] = decide(code, s["name"], s.get("industry",""), s["cost"], s["stop"], s["target"], sf, sd, au)
    
    ranked = sorted(results.items(), key=lambda x: x[1]["scores"]["综合"], reverse=True)
    
    dist = {}
    for code, r in results.items():
        d = r["decision"]["final"]
        dist[d] = dist.get(d, 0) + 1
    
    today = datetime.now().strftime("%Y%m%d")
    with open(os.path.join(DECISION_DIR, "decision_" + today + ".json"), "w", encoding="utf-8") as f:
        json.dump({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "distribution": dist, "decisions": {k:v for k,v in results.items()}}, f, ensure_ascii=False, indent=2)
    
    return {"distribution": dist, "ranked": [(c, {"name": r["name"], "decision": r["decision"]["final"], "score": r["scores"]["综合"]}) for c, r in ranked], "details": results, "principles": CORE_PRINCIPLES}


def summary(decision_result):
    lines = []
    lines.append("决策分布: {}".format(decision_result.get("distribution", {})))
    lines.append("")
    emoji = {"BUY": "O", "ADD": "B", "HOLD": "H", "REDUCE": "R", "AVOID": "X"}
    for code, r in decision_result.get("ranked", []):
        tag = emoji.get(r["decision"], "?")
        lines.append("  {} {:<8} {:<6} {:.1f}".format(tag, r["name"], r["decision"], r["score"]))
    return "\n".join(lines)
