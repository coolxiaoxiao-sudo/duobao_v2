"""交易纪律引擎 — 证伪思维+模式区分+仓位自适应+纪律执行

最终收官定版功能：
1. 预期差核心交易思维 — 挖掘认知不足、价值未兑现标的
2. 强弱分化对比交易法 — 只做强不做弱，强者恒强
3. 波段高低切换逻辑 — 主升持有，见顶离场
4. 稳健复利核心宗旨 — 高胜率、合理盈亏比、严控回撤
5. 追高检测 — 严禁盲目追高连续拉升个股，远离无业绩炒作
6. 盈亏比优先筛选 — 交易决策先看盈亏比，再看胜率
"""
from __future__ import annotations
import json, os
from datetime import datetime
from typing import Dict, List
import numpy as np
from core.config import config
from core.database import db

DISCIPLINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "discipline")
os.makedirs(DISCIPLINE_DIR, exist_ok=True)

TRADING_MODES = {
    "左侧埋伏": {"适用行情": "下跌末期", "入场": "跌破布林下轨+RSI<30+缩量", "离场": "反弹至中轨止盈", "周期": "1-4周", "仓位": "10-20%", "禁止": "趋势下跌中加仓"},
    "右侧追涨": {"适用行情": "趋势确立", "入场": "放量突破MA20+MACD金叉", "离场": "破突破位-3%止损", "周期": "1-3日", "仓位": "20-30%", "禁止": "追高超5%"},
    "趋势持有": {"适用行情": "均线多头排列", "入场": "MA5>MA10>MA20+ADX>25", "离场": "破MA10减仓，破MA20清仓", "周期": "1-4周", "仓位": "30-40%", "禁止": "因波动提前离场"},
    "超跌反弹": {"适用行情": "快速急跌", "入场": "连跌4天+RSI<30+缩量", "离场": "反弹至MA5减仓", "周期": "1-5日", "仓位": "10-15%", "禁止": "下跌中继抄底"},
}

def detect_trading_mode(code):
    try:
        from layer3_analysis.technical import compute
        from layer3_analysis.trend import compute_all as trend_compute
        tech = compute(code)
        tr = trend_compute(code, 60)
        rsi, vol, trend = tech.get("rsi14",50), tech.get("vol_ratio",1), tr.get("trend_total",5)
        ma_status, adx = tr.get("ma_status","unknown"), tr.get("adx",0)
        modes = []
        if rsi < 35 and vol < 0.8 and trend < 4: modes.append(("左侧埋伏",0.8))
        if trend >= 6 and vol > 1.3 and ma_status in ("bullish","bullish_weak"): modes.append(("右侧追涨",0.9))
        if ma_status == "bullish" and adx > 25 and trend >= 7: modes.append(("趋势持有",0.95))
        rows = db.query("SELECT close FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 5", (code,))
        if len(rows) >= 5:
            closes = [r["close"] for r in rows]
            if sum(1 for i in range(len(closes)-1) if closes[i] < closes[i+1]) >= 4 and rsi < 35:
                modes.append(("超跌反弹",0.7))
        if not modes: return {"mode":"观望","confidence":0}
        best = max(modes, key=lambda x:x[1])
        return {"mode":best[0],"confidence":best[1],"config":TRADING_MODES[best[0]],"warning":"严禁混用" if len(modes)>1 else None}
    except Exception as e:
        return {"error":str(e),"mode":"未知"}

def chase_risk_check(code, name):
    """追高风险检测 — 严禁盲目追高连续大幅拉升个股，远离无业绩炒作"""
    risks = []
    try:
        from layer1_data.tencent_api import get_quote
        from layer3_analysis.technical import compute
        
        q = get_quote(code)
        tech = compute(code)
        pe = q.get("pe", 0) or 0
        rsi = tech.get("rsi14", 50)
        
        rows = db.query("SELECT close,vol FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 60", (code,))
        if len(rows) < 10:
            return {"code":code,"name":name,"risks":[],"pass":True,"action":"数据不足，暂不判断"}
        
        closes = [r["close"] for r in rows]
        vols = [r["vol"] for r in rows]
        
        # 1. 连续大幅拉升检测（近10日涨幅>30%）
        if len(closes) >= 10:
            chg_10d = (closes[0] / closes[9] - 1) * 100 if closes[9] > 0 else 0
            if chg_10d > 30:
                risks.append(f"连续拉升: 10日涨幅{chg_10d:.0f}%")
            elif chg_10d > 20:
                risks.append(f"短期急涨: 10日涨幅{chg_10d:.0f}%")
        
        # 2. 高位RSI过热
        if rsi > 75:
            risks.append(f"RSI过热: {rsi:.0f}")
        elif rsi > 70:
            risks.append(f"RSI偏热: {rsi:.0f}")
        
        # 3. 无业绩支撑炒作
        if pe < 0:
            risks.append("业绩亏损，纯情绪炒作风险")
        elif pe > 200:
            risks.append(f"PE={pe:.0f}极高估值，透支严重")
        
        # 4. 放天量（可能出货）
        if len(vols) >= 20:
            avg_vol = np.mean(vols[1:20])
            if vols[0] > avg_vol * 3:
                risks.append("放天量: 可能主力出货")
        
        # 5. 涨速过快（3日内涨幅>15%）
        if len(closes) >= 3:
            chg_3d = (closes[0] / closes[2] - 1) * 100 if closes[2] > 0 else 0
            if chg_3d > 15:
                risks.append(f"急拉: 3日涨幅{chg_3d:.0f}%")
        
        pass_check = len(risks) == 0
        if len(risks) >= 3:
            action = "严禁追入，坚决放弃"
        elif len(risks) >= 1:
            action = "不满足低吸条件，观望"
        else:
            action = "未追高，可低吸布局"
        
        return {
            "code":code,"name":name,
            "risks":risks,"count":len(risks),
            "pass":pass_check,"action":action
        }
    except Exception as e:
        return {"error":str(e),"pass":False}

def risk_reward_filter(code, name, entry_price, stop_loss, target_price):
    """盈亏比优先筛选 — 先看盈亏比，再看胜率。无优质性价比直接观望"""
    if entry_price <= 0 or stop_loss <= 0 or target_price <= 0:
        return {"pass":False,"reason":"参数无效"}
    
    risk = abs(entry_price - stop_loss)
    reward = abs(target_price - entry_price)
    
    if risk == 0:
        return {"pass":False,"reason":"止损价等于入场价"}
    
    rr_ratio = reward / risk
    risk_pct = (risk / entry_price) * 100
    reward_pct = (reward / entry_price) * 100
    
    if rr_ratio >= 3:
        level, action = "A", "极品盈亏比，优先参与"
    elif rr_ratio >= 2:
        level, action = "B", "优质盈亏比，可参与"
    elif rr_ratio >= 1.5:
        level, action = "C", "盈亏比一般，谨慎参与"
    elif rr_ratio >= 1:
        level, action = "D", "盈亏比不足，轻仓试探"
    else:
        level, action = "F", "盈亏比<1，严禁参与"
    
    return {
        "code":code,"name":name,
        "entry":entry_price,"stop":stop_loss,"target":target_price,
        "risk_pct":round(risk_pct,1),"reward_pct":round(reward_pct,1),
        "rr_ratio":round(rr_ratio,1),
        "pass":rr_ratio >= 1.5,
        "level":level,"action":action
    }

def expectation_gap_analysis(code, name, industry):
    try:
        from layer1_data.tencent_api import get_quote
        from layer3_analysis.technical import compute
        q = get_quote(code)
        tech = compute(code)
        pe = q.get("pe", 0) or 0
        rsi = tech.get("rsi14", 50)
        rows = db.query("SELECT close FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 20", (code,))
        change_20d = 0
        if len(rows) >= 20:
            change_20d = (rows[0]["close"] / rows[-1]["close"] - 1) * 100
        gap_score = 5
        factors = []
        if 0 < pe < 30: gap_score += 1.5; factors.append("PE低估")
        elif pe > 100 or pe < 0: gap_score -= 2; factors.append("PE过高")
        if change_20d < -15: gap_score += 1.5; factors.append("近期深跌")
        elif change_20d > 30: gap_score -= 2; factors.append("近期大涨")
        if rsi < 30: gap_score += 1; factors.append("RSI超卖")
        elif rsi > 70: gap_score -= 1; factors.append("RSI超买")
        if industry in ["计算机", "电子", "电力"]: gap_score += 0.5
        gap_score = max(0, min(10, gap_score))
        if gap_score >= 7: gap_type, advice = "高预期差", "优先挖掘，价值有望兑现"
        elif gap_score <= 3: gap_type, advice = "一致高位", "远离高位透支行情"
        else: gap_type, advice = "中等预期", "观望等待"
        return {"code":code,"name":name,"gap_score":round(gap_score,1),"gap_type":gap_type,"factors":factors,"advice":advice}
    except Exception as e:
        return {"error":str(e)}

def falsification_analysis(code, name):
    try:
        from layer3_analysis.technical import compute
        from layer3_analysis.trend import compute_all as trend_compute
        tech, tr = compute(code), trend_compute(code, 60)
        signals = []
        if tech.get("rsi14",50) > 80: signals.append("RSI超买")
        if tr.get("macd_divergence") == "bearish_divergence": signals.append("MACD顶背离")
        if tr.get("trend_total",5) < 4: signals.append("趋势转空")
        if tech.get("vol_ratio",1) < 0.5: signals.append("缩量上涨")
        if tech.get("vol_ratio",1) > 2: signals.append("放量下跌")
        try:
            from layer1_data.tencent_api import get_quote
            pe = get_quote(code).get("pe",0) or 0
            if pe > 150: signals.append("PE高估")
            elif pe < 0: signals.append("亏损股")
        except: pass
        if len(signals) >= 3: verdict, action = "强烈证伪", "坚决放弃"
        elif len(signals) >= 1: verdict, action = "部分证伪", "谨慎参与"
        else: verdict, action = "未证伪", "可继续研究"
        return {"code":code,"name":name,"signals":signals,"count":len(signals),"verdict":verdict,"action":action}
    except Exception as e:
        return {"error":str(e)}

def strength_comparison(stock_list):
    try:
        from layer3_analysis.trend import compute_all as trend_compute
        from layer1_data.tencent_api import get_quote
        rankings = []
        for s in stock_list:
            try:
                tr = trend_compute(s["code"], 20)
                q = get_quote(s["code"])
                strength = tr.get("trend_total",5)*0.4 + (q.get("change",0)/10)*0.3 + (tr.get("adx",0)/50)*0.3
                rankings.append({"code":s["code"],"name":s["name"],"strength":round(strength,2)})
            except: continue
        rankings.sort(key=lambda x:x["strength"], reverse=True)
        n = len(rankings)
        return {"strong":rankings[:n//3],"medium":rankings[n//3:2*n//3],"weak":rankings[2*n//3:],"principle":"只做强不做弱"}
    except Exception as e:
        return {"error":str(e)}

def band_switch_logic(code):
    try:
        from layer3_analysis.trend import compute_all as trend_compute
        tr = trend_compute(code, 60)
        ma_status, adx, trend_total = tr.get("ma_status"), tr.get("adx",0), tr.get("trend_total",5)
        if ma_status == "bullish" and adx > 25 and trend_total >= 7:
            return {"band_position":"主升浪","action":"坚定持有不轻易下车"}
        elif tr.get("macd_divergence") == "bearish_divergence":
            return {"band_position":"顶部区域","action":"果断止盈离场"}
        elif trend_total < 4:
            return {"band_position":"下跌趋势","action":"空仓观望"}
        else:
            return {"band_position":"震荡整理","action":"观望等待"}
    except Exception as e:
        return {"error":str(e)}

def adaptive_position(grade, heat, idx_pos):
    base = {"A":0.35,"B":0.25,"C":0.15,"D":0.05}.get(grade,0.1)
    heat_mult = {"冰点":1.3,"回暖":1.1,"亢奋":0.6,"退潮":0.4}.get(heat,1.0)
    idx_mult = {"低位":1.2,"中位":1.0,"高位":0.7}.get(idx_pos,1.0)
    final = max(0,min(0.5,base*heat_mult*idx_mult))
    level = "重仓" if final>=0.4 else ("半仓" if final>=0.25 else ("轻仓" if final>=0.1 else "空仓"))
    return {"final_pct":round(final,2),"level":level}

def enforce_plan(plan):
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    pid = plan["code"] + "_" + ts
    record = {"plan_id":pid,"timestamp":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),**plan,"status":"LOCKED"}
    with open(os.path.join(DISCIPLINE_DIR,"plan_"+pid+".json"),"w",encoding="utf-8") as f:
        json.dump(record,f,ensure_ascii=False,indent=2)
    return {"plan_id":pid,"status":"LOCKED","warning":"计划已锁定，严禁更改"}

def batch_check():
    results = {}
    for s in config.stocks:
        code = s["code"]
        chase = chase_risk_check(code, s["name"])
        rr = risk_reward_filter(code, s["name"], s["cost"], s["stop"], s["target"])
        results[code] = {
            "name":s["name"],
            "mode":detect_trading_mode(code),
            "chase_risk":chase,
            "risk_reward":rr,
            "falsify":falsification_analysis(code, s["name"]),
            "expectation_gap":expectation_gap_analysis(code, s["name"], s.get("industry","")),
            "band":band_switch_logic(code),
        }
    results["_strength_rank"] = strength_comparison(config.stocks)
    return results
