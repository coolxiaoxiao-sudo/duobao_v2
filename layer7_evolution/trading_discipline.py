"""交易纪律引擎 — 证伪思维+模式区分+仓位自适应+纪律执行"""
from __future__ import annotations
import json, os
from datetime import datetime
from typing import Dict
from core.config import config
from core.database import db

DISCIPLINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "discipline")
os.makedirs(DISCIPLINE_DIR, exist_ok=True)

TRADING_MODES = {
    "左侧埋伏": {"适用行情": "下跌末期", "入场": "跌破布林下轨+RSI<30+缩量", "离场": "反弹至中轨止盈，破前低止损", "周期": "1-4周", "仓位": "10-20%", "禁止": "趋势下跌中加仓，重仓左侧"},
    "右侧追涨": {"适用行情": "趋势确立", "入场": "放量突破MA20+MACD金叉", "离场": "破突破位-3%止损", "周期": "1-3日", "仓位": "20-30%", "禁止": "追高超5%，缩量突破追涨"},
    "趋势持有": {"适用行情": "均线多头排列", "入场": "MA5>MA10>MA20+ADX>25", "离场": "破MA10减仓，破MA20清仓", "周期": "1-4周", "仓位": "30-40%", "禁止": "因波动提前离场，逆势加仓"},
    "超跌反弹": {"适用行情": "快速急跌", "入场": "连跌4天+RSI<30+缩量", "离场": "反弹至MA5减仓，破前低止损", "周期": "1-5日", "仓位": "10-15%", "禁止": "下跌中继抄底，重仓博反弹"},
}

def detect_trading_mode(code: str) -> dict:
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

def falsification_analysis(code: str, name: str) -> dict:
    try:
        from layer3_analysis.technical import compute
        from layer3_analysis.trend import compute_all as trend_compute
        tech, tr = compute(code), trend_compute(code, 60)
        signals = []
        if tech.get("rsi14",50) > 80: signals.append("RSI超买")
        if tr.get("macd_divergence") == "bearish_divergence": signals.append("MACD顶背离")
        if tr.get("trend_total",5) < 4: signals.append("趋势转空")
        if tech.get("vol_ratio",1) < 0.5 and tech.get("price",0) > tr.get("ma20",0): signals.append("缩量上涨")
        if tech.get("vol_ratio",1) > 2 and tech.get("price",0) < tr.get("ma5",0): signals.append("放量下跌")
        try:
            from layer1_data.tencent_api import get_quote
            pe = get_quote(code).get("pe",0) or 0
            if pe > 100: signals.append(f"PE={pe}高估")
            elif pe < 0: signals.append("亏损股")
        except: pass
        verdict = "强烈看空" if len(signals)>=3 else ("谨慎" if len(signals)>=1 else "暂无重大利空")
        return {"code":code,"name":name,"signals":signals,"count":len(signals),"verdict":verdict}
    except Exception as e:
        return {"error":str(e)}

def adaptive_position(grade: str, heat: str, idx_pos: str) -> dict:
    base = {"A":0.35,"B":0.25,"C":0.15,"D":0.05}.get(grade,0.1)
    final = base * {"冰点":1.3,"回暖":1.1,"亢奋":0.6,"退潮":0.4}.get(heat,1.0) * {"低位":1.2,"中位":1.0,"高位":0.7}.get(idx_pos,1.0)
    final = max(0,min(0.5,final))
    level = "重仓" if final>=0.4 else ("半仓" if final>=0.25 else ("轻仓" if final>=0.1 else ("迷你仓" if final>0 else "空仓")))
    return {"final_pct":round(final,2),"level":level}

def enforce_plan(plan: dict) -> dict:
    pid = f"{plan['code']}_{datetime.now().strftime('%Y%m%d_%H%M')}"
    record = {"plan_id":pid,"timestamp":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),**plan,"status":"LOCKED","mods":[]}
    with open(os.path.join(DISCIPLINE_DIR,f"plan_{pid}.json"),"w",encoding="utf-8") as f:
        json.dump(record,f,ensure_ascii=False,indent=2)
    return {"plan_id":pid,"status":"LOCKED","warning":"计划已锁定，严禁更改"}

def batch_check() -> dict:
    return {s["code"]:{"name":s["name"],"mode":detect_trading_mode(s["code"]),"falsify":falsification_analysis(s["code"],s["name"])} for s in config.stocks}
