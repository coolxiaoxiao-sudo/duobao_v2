"""L5 持仓审计 — T/B/F/R 四维评分
T=趋势(MA排列+ADX+MACD方向) B=估值(PE+PB+行业) F=六因子总分 R=风险(距止损+RSI)
ADD≥6.0  HOLD≥4.5  REDUCE≥3.0  CLOSE<3.0"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import config
from core.logging import get_logger
from layer3_analysis.technical import compute as tech_compute, score as factor_score
from layer3_analysis.trend import compute_all as trend_compute
from layer1_data.tencent_api import get_quote
logger = get_logger("audit")

def _pe_b_score(code):
    """B=估值: 从实时行情取PE做分档，回退到pct_ma20代理"""
    try:
        q = get_quote(code)
        pe = q.get("pe", 0)
    except:
        pe = 0
    if pe is None: pe = 0
    if pe <= 0: return 2   # 亏损
    elif pe < 20: return 8  # 低估
    elif pe < 40: return 6  # 合理偏低
    elif pe < 60: return 5  # 合理
    elif pe < 100: return 3 # 偏高
    else: return 1          # 高估

def _industry_bonus(industry):
    """行业加成: 计算机+0.5, 电力+0.5"""
    bonus = {"计算机": 0.5, "电子": 0.5, "电力": 0.5, "有色金属": 0, "汽车": 0,
             "医药生物": 0, "传媒": 0, "电力设备": 0}
    return bonus.get(industry, 0)


def audit():
    r = {}
    for s in config.stocks:
        code, name, cost, stop, tgt = s["code"], s["name"], s.get("cost",0), s.get("stop",0), s.get("target",0)
        industry = s.get("industry", "")
        tech = tech_compute(code)
        if "error" in tech: r[code] = {**s, "error": tech["error"], "action": "HOLD"}; continue
        p = tech.get("price", 0)
        rsi = tech.get("rsi14", 50)

        # T=趋势: MA排列+ADX+MACD方向 (0-10制)
        tr = trend_compute(code, 60)
        T = round(tr.get("trend_total", 5), 1)
        ma_status = tr.get("ma_status", "unknown")

        # B=估值: 真实PE + 行业加成
        B_raw = _pe_b_score(code)
        B = round(B_raw + _industry_bonus(industry), 1)

        # F=六因子总分 (0-10制)
        fs = factor_score(tech, config.weights)
        F = fs.get("total", 5)
        fac_signal = fs.get("signal", "HOLD")

        # R=风险 (距止损距离 + RSI 归一化)
        dts_pct = (p / stop - 1) * 100 if stop else 100
        r_stop = 8 if dts_pct > 20 else (6 if dts_pct > 10 else (4 if dts_pct > 5 else 2))
        r_rsi = 8 if rsi < 35 else (6 if rsi < 45 else (4 if rsi < 55 else 2))
        R = round((r_stop + r_rsi) / 2, 1)

        tot = round((T + B + F + R) / 4, 1)
        th = config.signal_thresholds
        if tot >= th.get("add", 6): act = "ADD"
        elif tot >= th.get("hold_audit", 4.5): act = "HOLD"
        elif tot >= th.get("reduce", 3): act = "REDUCE"
        else: act = "CLOSE"

        r[code] = {**s, "price": p, "scores": {"T": T, "B": B, "F": F, "R": R},
                   "total": tot, "action": act, "rsi": rsi, "ma_status": ma_status,
                   "factor_signal": fac_signal, "pct_stop": round(dts_pct, 2)}

    return dict(sorted(r.items(), key=lambda x: x[1].get("total", 0), reverse=True))
