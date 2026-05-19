"""信号过滤降噪+三层一致性校验+盈亏比优先

最终收官定版功能：
1. 盈亏比优先 — 先看盈亏比，再看胜率，无优质性价比观望
2. 三层一致性校验 — 短期/中期/长期明确划分，多周期共振
3. 信号过滤降噪 — 只输出高确定性A/B级机会
4. 每日净化 — 沉淀核心逻辑，杜绝随意频繁交易
"""
from __future__ import annotations
import json, os
from datetime import datetime
from typing import Dict
from core.config import config

FILTER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "filter")
os.makedirs(FILTER_DIR, exist_ok=True)

def risk_reward_first(entry_price, stop_loss, target_price, win_rate):
    """盈亏比优先 — 先看盈亏比，再看胜率"""
    if entry_price <= 0 or stop_loss <= 0 or target_price <= 0:
        return {"pass":False,"reason":"参数无效","level":"F"}
    
    risk = abs(entry_price - stop_loss)
    reward = abs(target_price - entry_price)
    
    if risk == 0:
        return {"pass":False,"reason":"止损价等于入场价","level":"F"}
    
    rr = reward / risk
    
    # 盈亏比优先决策矩阵
    if rr >= 3.0:
        level = "A"
        action = "极品盈亏比>3:1，胜率>50%即重仓"
        req_win = 0.4
    elif rr >= 2.0:
        level = "B"
        action = "优质盈亏比>2:1，胜率>50%可参与"
        req_win = 0.5
    elif rr >= 1.5:
        level = "C"
        action = "合格盈亏比>1.5:1，胜率>55%可轻仓"
        req_win = 0.55
    elif rr >= 1.0:
        level = "D"
        action = "勉强合格，胜率>60%才考虑"
        req_win = 0.6
    else:
        return {"pass":False,"reason":f"盈亏比{r:.1f}<1，严禁参与","level":"F"}
    
    win_ok = win_rate >= req_win
    
    if win_ok:
        return {"pass":True,"level":level,"action":action,"rr":round(rr,1),"win_rate":win_rate,"required_win":req_win}
    else:
        return {"pass":False,"level":"C","action":f"盈亏比达标但胜率{win_rate:.0%}<{req_win:.0%}，观望","rr":round(rr,1)}

def filter_signal(code, short_score, mid_score, long_score, rr_level, win_rate):
    """信号过滤 — 先盈亏比后一致性"""
    # 盈亏比不合格直接拒绝
    if rr_level in ("F",):
        return {"pass":False,"level":"F","reason":"盈亏比不达标，直接拒绝","action":"放弃"}
    
    # 三层一致性
    aligned = (short_score > 5 and mid_score > 5 and long_score > 5) or (short_score < 5 and mid_score < 5 and long_score < 5)
    consistency = abs(short_score - mid_score) < 2 and abs(mid_score - long_score) < 2
    
    # 综合判断（盈亏比权重优先）
    if rr_level == "A" and aligned and consistency and win_rate > 0.45:
        return {"pass":True,"level":"A","reason":"极品盈亏比+三层一致","action":"重仓参与"}
    elif rr_level in ("A","B") and aligned and win_rate > 0.5:
        return {"pass":True,"level":"B","reason":"优质盈亏比+方向一致","action":"标准仓位"}
    elif rr_level in ("A","B","C") and aligned:
        return {"pass":True,"level":"B","reason":"盈亏比合格+方向一致","action":"轻仓参与"}
    else:
        return {"pass":False,"level":"C","reason":"不满足综合条件","action":"观望等待更好机会"}

def three_layer_validation(code):
    """三层走势划分 — 短期/中期/长期明确标注"""
    try:
        from layer3_analysis.technical import compute
        from layer3_analysis.trend import compute_all as trend_compute
        from layer7_evolution.cross_cycle import cross_cycle_analysis
        
        # 短期（日线/1-5日）
        tech = compute(code)
        rsi = tech.get("rsi14", 50)
        short_score = rsi / 10
        if short_score > 7: short_label = "强势"
        elif short_score > 5: short_label = "偏强"
        elif short_score > 3: short_label = "偏弱"
        else: short_label = "弱势"
        
        # 中期（周线代理：20日趋势）
        tr = trend_compute(code, 20)
        mid_score = tr.get("trend_total", 5)
        mid_ma = tr.get("ma_status", "unknown")
        if mid_ma == "bullish": mid_label = "多头排列"
        elif mid_ma == "bullish_weak": mid_label = "偏多整理"
        else: mid_label = "偏空运行"
        
        # 长期（跨周期/60日）
        cyc = cross_cycle_analysis(code)
        long_score = cyc.get("big_trend_score", 5)
        long_phase = cyc.get("cycle", "不明")
        
        # 一致性判断
        all_bull = short_score > 5 and mid_score > 5 and long_score > 5
        all_bear = short_score < 5 and mid_score < 5 and long_score < 5
        consistent = all_bull or all_bear
        
        if all_bull: direction = "多周期共振向上 [短强+中多+长多]"
        elif all_bear: direction = "多周期共振向下 [短弱+中空+长空]"
        else: direction = "周期分歧 — 无一致性方向"
        
        return {
            "short": {"score": round(short_score,1), "label": short_label, "period": "1-5日"},
            "mid": {"score": mid_score, "label": mid_label, "period": "5-20日"},
            "long": {"score": round(long_score,1), "label": long_phase, "period": "20-60日"},
            "consistent": consistent,
            "direction": direction,
            "valid": consistent,
        }
    except Exception as e:
        return {"error": str(e), "valid": False}

def daily_purification():
    """每日净化 — 拒绝随意频繁交易，沉淀核心逻辑"""
    core_principles = [
        "趋势跟随：均线多头排列持有，破位清仓",
        "量价验证：放量突破跟进，缩量上涨警惕",
        "纪律执行：计划锁定后不更改",
        "风控优先：止损触发即执行",
        "盈亏比先：盈亏比<1.5绝不参与",
        "低吸至上：严禁追高，优先合理低位布局",
        "强者恒强：只做强势方向，放弃弱势机会",
    ]
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "purged": ["频繁交易", "追高冲动", "情绪炒作", "逆势操作", "高胜率低盈亏比陷阱"],
        "retained": core_principles,
        "note": "精选机会，控制出手次数，无优质性价比直接观望",
    }

def batch_filter():
    """全持仓信号过滤"""
    results = {}
    for s in config.stocks:
        three = three_layer_validation(s["code"])
        rr_level = "B"  # 默认等级
        try:
            from layer7_evolution.trading_discipline import risk_reward_filter
            rr_result = risk_reward_filter(s["code"], s["name"], s["cost"], s["stop"], s["target"])
            rr_level = rr_result.get("level", "B")
        except: pass
        
        filt = filter_signal(s["code"],
                           three.get("short",{}).get("score",5) if isinstance(three.get("short"),dict) else three.get("short",5),
                           three.get("mid",{}).get("score",5) if isinstance(three.get("mid"),dict) else three.get("mid",5),
                           three.get("long",{}).get("score",5) if isinstance(three.get("long"),dict) else three.get("long",5),
                           rr_level, 0.55)
        results[s["code"]] = {"name":s["name"], "three_layer":three, "filter":filt}
    
    with open(os.path.join(FILTER_DIR,"filter_"+datetime.now().strftime("%Y%m%d")+".json"),"w",encoding="utf-8") as f:
        json.dump(results,f,ensure_ascii=False,indent=2)
    
    passed = sum(1 for r in results.values() if r["filter"].get("pass"))
    return {"total":len(results), "passed":passed, "filtered":len(results)-passed, "details":results}
