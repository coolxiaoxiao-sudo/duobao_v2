"""信号过滤降噪+三层一致性校验"""
from __future__ import annotations
import json, os
from datetime import datetime
from typing import Dict
from core.config import config

FILTER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "filter")
os.makedirs(FILTER_DIR, exist_ok=True)

def filter_signal(code: str, short_score: float, mid_score: float, long_score: float,
                  win_rate: float, profit_loss: float) -> dict:
    """信号过滤 — 只输出高确定性机会"""
    # 三层一致性校验
    aligned = (short_score > 5 and mid_score > 5 and long_score > 5) or (short_score < 5 and mid_score < 5 and long_score < 5)
    consistency = abs(short_score - mid_score) < 2 and abs(mid_score - long_score) < 2
    
    # 高确定性标准
    high_confidence = win_rate > 0.6 and profit_loss > 2.0 and aligned and consistency
    medium_confidence = win_rate > 0.5 and profit_loss > 1.5 and aligned
    
    if high_confidence:
        return {"pass":True,"level":"A","reason":"高胜率+高盈亏比+三层一致","action":"重仓参与"}
    elif medium_confidence:
        return {"pass":True,"level":"B","reason":"中等胜率+三层一致","action":"标准仓位"}
    else:
        return {"pass":False,"level":"C","reason":"不满足高确定性标准","action":"观望"}

def three_layer_validation(code: str) -> dict:
    """短期/中期/长期三层走势一致性校验"""
    try:
        from layer3_analysis.technical import compute
        from layer3_analysis.trend import compute_all as trend_compute
        from layer7_evolution.cross_cycle import cross_cycle_analysis
        
        # 短期（日线）
        tech = compute(code)
        short_trend = tech.get("rsi14",50) / 10  # 0-10分
        
        # 中期（周线代理：20日趋势）
        tr = trend_compute(code, 20)
        mid_trend = tr.get("trend_total", 5)
        
        # 长期（跨周期）
        cyc = cross_cycle_analysis(code)
        long_trend = cyc.get("big_trend_score", 5)
        
        # 一致性判断
        all_bull = short_trend > 5 and mid_trend > 5 and long_trend > 5
        all_bear = short_trend < 5 and mid_trend < 5 and long_trend < 5
        consistent = all_bull or all_bear
        
        return {
            "short": round(short_trend,1), "mid": mid_trend, "long": round(long_trend,1),
            "consistent": consistent,
            "direction": "多周期共振向上" if all_bull else ("多周期共振向下" if all_bear else "周期分歧"),
            "valid": consistent,
        }
    except Exception as e:
        return {"error": str(e), "valid": False}

def daily_purification() -> dict:
    """每日清空无效思路，沉淀核心逻辑"""
    core_principles = [
        "趋势跟随：均线多头排列持有，破位清仓",
        "量价验证：放量突破跟进，缩量上涨警惕",
        "纪律执行：计划锁定后不更改",
        "风控优先：止损触发即执行",
        "高确定性：只参与A/B级信号",
    ]
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "purged": ["复杂指标叠加", "主观臆测", "频繁交易", "逆势操作"],
        "retained": core_principles,
        "note": "体系越精简，执行越纯粹",
    }

def batch_filter() -> dict:
    """全持仓信号过滤"""
    results = {}
    for s in config.stocks:
        three = three_layer_validation(s["code"])
        # 简化胜率盈亏比
        filt = filter_signal(s["code"], three.get("short",5), three.get("mid",5), three.get("long",5),
                            0.55, 2.0)  # 默认中等水平
        results[s["code"]] = {"name":s["name"], "three_layer":three, "filter":filt}
    
    with open(os.path.join(FILTER_DIR,f"filter_{datetime.now().strftime('%Y%m%d')}.json"),"w",encoding="utf-8") as f:
        json.dump(results,f,ensure_ascii=False,indent=2)
    
    passed = sum(1 for r in results.values() if r["filter"].get("pass"))
    return {"total":len(results), "passed":passed, "filtered":len(results)-passed, "details":results}
