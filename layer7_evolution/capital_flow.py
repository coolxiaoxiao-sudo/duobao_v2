"""资金层级深度拆解 — 机构主力/北向资金/游资/散户行为识别

通过量价特征和持仓数据推断各路资金意图：
  机构主力：温和放量+持续买入+压盘吸筹
  游资：脉冲放量+题材+短线快进快出
  北向资金：持续净流入+指数关联性强
  散户：缩量+随大流+高位接盘特征
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("capital_flow")

FLOW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "capital")
os.makedirs(FLOW_DIR, exist_ok=True)


def analyze_capital_flow(code: str, name: str = "") -> dict:
    """单只股票资金层级拆解"""
    rows = db.query(
        "SELECT trade_date,open,high,low,close,vol FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 60",
        (code,))
    if len(rows) < 30:
        return {"error": "数据不足", "code": code, "name": name}

    closes = [r["close"] for r in rows][::-1]
    vols = [r["vol"] for r in rows][::-1]
    price = closes[-1]
    vol5 = np.mean(vols[1:6]) if len(vols) >= 6 else vols[0]
    vol10 = np.mean(vols[1:11]) if len(vols) >= 11 else vols[0]

    # 1. 机构主力
    up_days = sum(1 for i in range(1, len(closes)) if closes[-i] > closes[-i-1])
    up_ratio = up_days / min(20, len(closes)-1)
    vol_stability = np.std(vols[:10]) / np.mean(vols[:10]) if np.mean(vols[:10]) > 0 else 1

    inst_score, inst_sig = 0, []
    if vol_stability < 0.3 and np.mean(vols[:5]) / vol5 > 1.1:
        inst_score += 4; inst_sig.append("温和持续放量，疑似机构建仓")
    if up_ratio > 0.65:
        inst_score += 3; inst_sig.append(f"阳线占比{up_ratio:.0%}")
    recent_5d = closes[:5]
    if max(recent_5d) / min(recent_5d) < 1.05 and np.mean(vols[:5]) > vol10 * 1.2:
        inst_score += 3; inst_sig.append("压盘吸筹")
    inst_intensity = "强" if inst_score >= 7 else ("中" if inst_score >= 4 else "弱")

    # 2. 游资
    pulse_count = sum(1 for v in vols[:10] if v > vol5 * 2)
    hot_score, hot_sig = 0, []
    if pulse_count >= 2:
        hot_score += 4; hot_sig.append(f"近期{pulse_count}次脉冲放量")
    price_std = np.std(closes[:20]) / np.mean(closes[:20])
    if price_std > 0.05:
        hot_score += 3; hot_sig.append(f"高频波动{price_std:.1%}")
    consec_up = 0
    for i in range(1, len(closes)):
        if closes[-i] > closes[-i-1] * 1.09:
            consec_up += 1
        else:
            break
    if consec_up >= 2:
        hot_score += 3; hot_sig.append(f"连涨{consec_up}天")
    hot_intensity = "强" if hot_score >= 7 else ("中" if hot_score >= 4 else "弱")

    # 3. 北向资金
    north_score, north_sig = 0, []
    try:
        from layer1_data.tencent_api import get_quote
        q = get_quote(code); pe = q.get("pe", 0) or 0
        if 10 < pe < 40:
            north_score += 3; north_sig.append(f"PE={pe}")
    except:
        pass
    if vol_stability < 0.2:
        north_score += 2; north_sig.append("量能稳定")
    north_intensity = "强" if north_score >= 5 else ("中" if north_score >= 3 else "弱")

    # 4. 散户
    retail_score, retail_sig = 0, []
    if np.mean(vols[:5]) < vol10 * 0.8 and price > np.mean(closes[:20]):
        retail_score += 4; retail_sig.append("缩量上涨")
    recent_high = max(closes[:20])
    if price > recent_high * 0.98 and np.mean(vols[:5]) > vol10 * 1.5:
        retail_score += 4; retail_sig.append("高位放量")
    retail_intensity = "弱" if retail_score <= 3 else ("中" if retail_score <= 6 else "强")

    flows = {
        "机构主力": {"score": inst_score, "intensity": inst_intensity, "signals": inst_sig},
        "游资": {"score": hot_score, "intensity": hot_intensity, "signals": hot_sig},
        "北向资金": {"score": north_score, "intensity": north_intensity, "signals": north_sig},
        "散户": {"score": retail_score, "intensity": retail_intensity, "signals": retail_sig},
    }
    dominant = max(flows.items(), key=lambda x: x[1]["score"])

    intent_map = {
        "机构主力": "机构建仓中，继续持有" if inst_score > 7 else "机构低吸，不追涨",
        "游资": "游资炒作，注意止盈" if hot_score > 7 else "游资试探，不宜重仓",
        "北向资金": "长线资金流入，中期持有",
        "散户": "散户主导，注意风险",
    }

    return {
        "code": code, "name": name, "price": price,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "flows": flows, "dominant": dominant[0], "intent": intent_map.get(dominant[0], "观望"),
    }


def batch_capital_flow() -> dict:
    results = {}
    for s in config.stocks:
        try:
            results[s["code"]] = analyze_capital_flow(s["code"], s["name"])
        except Exception as e:
            results[s["code"]] = {"error": str(e), "name": s["name"]}

    by_flow = {}
    for code, r in results.items():
        dom = r.get("dominant", "?")
        if dom not in by_flow:
            by_flow[dom] = []
        by_flow[dom].append({"code": code, "name": r.get("name", "?"),
                             "score": r.get("flows", {}).get(dom, {}).get("score", 0)})

    f = os.path.join(FLOW_DIR, f"flow_{datetime.now().strftime('%Y%m%d')}.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)

    return {"date": datetime.now().strftime("%Y-%m-%d"), "results": results, "by_flow": by_flow}
