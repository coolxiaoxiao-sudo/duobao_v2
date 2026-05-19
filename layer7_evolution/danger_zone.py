"""高危雷区排雷 — 六大雷区+量能结构+联动验证+系统性风险

最终收官定版功能：
1. 六大高危雷区检测 — 远离风险源头
2. 四大量能结构识别 — 量价关系验证
3. 大盘-板块-个股联动验证 — 环境一致性
4. 系统性风险预警 — 大盘走弱第一时间避险
"""
from __future__ import annotations
import json, os
from datetime import datetime
from typing import Dict, List
import numpy as np
from core.database import db
from core.config import config

DANGER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "danger")
os.makedirs(DANGER_DIR, exist_ok=True)

def check_six_dangers(code, name):
    """六大高危雷区检测"""
    dangers = []
    try:
        rows = db.query("SELECT high,low,close,vol FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 60", (code,))
        if len(rows) < 20: return {"error":"数据不足"}
        closes = [r["close"] for r in rows][::-1]
        highs = [r["high"] for r in rows][::-1]
        vols = [r["vol"] for r in rows][::-1]
        recent_high = max(highs[-20:])
        
        # 1. 高位筹码松动
        if closes[-1] > recent_high * 0.95 and np.mean(vols[-5:]) > np.mean(vols[-20:]) * 1.5:
            dangers.append("高位筹码松动：价格高位+放量")
        
        # 2. 股东减持（模拟：价格异常下跌）
        if closes[-1] < closes[-5] * 0.9 and np.mean(vols[-3:]) > np.mean(vols[-10:]) * 1.3:
            dangers.append("疑似减持：快速下跌+放量")
        
        # 3. 解禁压力（模拟：大市值+近期上市）
        if len(closes) < 252:
            dangers.append("解禁压力：次新股，注意解禁")
        
        # 4. 商誉暴雷（模拟：高估值+亏损）
        try:
            from layer1_data.tencent_api import get_quote
            q = get_quote(code)
            if (q.get("pe",0) or 0) < 0:
                dangers.append("商誉/业绩风险：PE亏损")
        except: pass
        
        # 5. 质押过高（模拟：ST或连续下跌）
        if "ST" in name or closes[-1] < np.mean(closes[-60:]) * 0.7:
            dangers.append("质押风险：ST或深跌")
        
        # 6. 业绩变脸（模拟：价格提前反映）
        if closes[-1] < closes[-20] * 0.8:
            dangers.append("业绩变脸嫌疑：20日跌幅超20%")
        
        return {"code":code,"name":name,"dangers":dangers,"count":len(dangers),"pass":len(dangers)==0}
    except Exception as e:
        return {"error":str(e)}

def analyze_volume_structure(code):
    """四大量价结构识别"""
    try:
        rows = db.query("SELECT close,vol FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 20", (code,))
        closes = [r["close"] for r in rows][::-1]
        vols = [r["vol"] for r in rows][::-1]
        vol_avg = np.mean(vols[:-5]) if len(vols) > 5 else vols[0]
        recent_vol = np.mean(vols[-5:])
        price_change = (closes[-1] / closes[0] - 1) * 100 if closes[0] > 0 else 0
        
        if recent_vol < vol_avg * 0.7 and abs(price_change) < 3:
            return {"structure":"缩量企稳","signal":"底部信号，等待放量确认","reliability":"中"}
        if recent_vol > vol_avg * 1.5 and price_change > 5:
            return {"structure":"放量突破","signal":"有效突破，可跟进","reliability":"高"}
        if recent_vol > vol_avg * 1.5 and abs(price_change) < 2:
            return {"structure":"放量滞涨","signal":"顶部信号，警惕出货","reliability":"高"}
        if recent_vol < vol_avg * 0.8 and price_change < -5:
            return {"structure":"缩量阴跌","signal":"无人承接，继续探底","reliability":"高"}
        return {"structure":"正常波动","signal":"无明显结构","reliability":"低"}
    except Exception as e:
        return {"error":str(e)}

def linkage_validation(code, industry):
    """大盘-板块-个股联动验证"""
    try:
        from layer1_data.tencent_api import get_indices
        indices = get_indices()
        sh_pct = indices.get("上证指数",{}).get("pct_chg",0) or 0
        
        rows = db.query("SELECT close FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 2", (code,))
        if len(rows) < 2: return {"error":"数据不足"}
        stock_pct = (rows[0]["close"] / rows[1]["close"] - 1) * 100
        
        aligned = (sh_pct > 0 and stock_pct > 0) or (sh_pct < 0 and stock_pct < 0)
        divergence = abs(stock_pct - sh_pct) > 2
        
        if aligned and not divergence:
            return {"linkage":"同步","risk":"低","advice":"跟随大势操作"}
        elif not aligned and divergence:
            return {"linkage":"背离","risk":"高","advice":"独立走势，谨慎参与"}
        else:
            return {"linkage":"部分同步","risk":"中","advice":"关注板块效应"}
    except Exception as e:
        return {"error":str(e)}

def systemic_risk_check():
    """系统性风险预警 — 大盘走弱第一时间避险提示"""
    risks = []
    try:
        from layer1_data.tencent_api import get_indices
        indices = get_indices()
        
        sh = indices.get("上证指数", {})
        sz = indices.get("深证成指", {})
        cy = indices.get("创业板指", {})
        
        sh_pct = sh.get("pct_chg", 0) or 0
        sz_pct = sz.get("pct_chg", 0) or 0
        cy_pct = cy.get("pct_chg", 0) or 0
        
        # 1. 三大指数共振下跌
        if sh_pct < -1 and sz_pct < -1 and cy_pct < -1:
            risks.append("三大指数共振大跌")
        elif sh_pct < 0 and sz_pct < 0 and cy_pct < 0:
            risks.append("三大指数同步走弱")
        
        # 2. 单日大跌预警
        if sh_pct < -3:
            risks.append(f"沪指暴跌{sh_pct:.1f}%")
        if cy_pct < -4:
            risks.append(f"创业板暴跌{cy_pct:.1f}%")
        
        # 3. 连续下跌（从数据库获取）
        try:
            # 用持仓中任意一只票的行情数据反推大盘趋势
            rows = db.query("SELECT close FROM stock_daily WHERE ts_code=(SELECT ts_code FROM stock_daily LIMIT 1) ORDER BY trade_date DESC LIMIT 5")
            if len(rows) >= 5:
                closes = [r["close"] for r in rows]
                down_days = sum(1 for i in range(len(closes)-1) if closes[i] < closes[i+1])
                if down_days >= 4:
                    risks.append(f"大盘连跌{days}天")
        except: pass
        
        # 4. 情绪低迷判断
        if abs(sh_pct) < 0.3 and abs(sz_pct) < 0.3:
            risks.append("市场情绪低迷，交投清淡")
        
        # 避险决策
        if len(risks) >= 3:
            level = "一级预警"
            action = "系统性风险高，立即降仓至30%以下，或空仓休息"
            signal = "REDUCE"
        elif len(risks) >= 2:
            level = "二级预警"
            action = "市场走弱，主动降仓减仓，控制回撤"
            signal = "CAUTION"
        elif len(risks) >= 1:
            level = "三级关注"
            action = "市场偏弱，提高警惕，减少新开仓"
            signal = "WATCH"
        else:
            level = "安全"
            action = "市场环境正常，正常交易"
            signal = "OK"
        
        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "indices": {"上证": sh_pct, "深证": sz_pct, "创业板": cy_pct},
            "risks": risks, "count": len(risks),
            "level": level, "action": action, "signal": signal
        }
    except Exception as e:
        return {"error": str(e)}

def full_danger_check(code, name, industry):
    """完整雷区检查"""
    return {
        "code":code,"name":name,"industry":industry,
        "six_dangers":check_six_dangers(code,name),
        "volume_structure":analyze_volume_structure(code),
        "linkage":linkage_validation(code,industry),
        "timestamp":datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

def batch_danger_check():
    results = {}
    for s in config.stocks:
        results[s["code"]] = full_danger_check(s["code"],s["name"],s.get("industry",""))
    
    # 追加系统性风险
    results["_systemic"] = systemic_risk_check()
    
    with open(os.path.join(DANGER_DIR,"danger_"+datetime.now().strftime("%Y%m%d")+".json"),"w",encoding="utf-8") as f:
        json.dump(results,f,ensure_ascii=False,indent=2)
    return results
