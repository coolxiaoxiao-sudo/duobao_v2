"""7维综合评分模块 — 趋势+均值回归+波动+量价+估值+基本面+相对强度

在六因子均值回归之外，增加：
  趋势维度 → layer3_analysis/trend.py
  波动维度 → 布林带宽度 + 历史波动率
  量价维度 → OBV / 量价配合
  估值维度 → PE / 距 52 周高低
  基本面具代 → 盈亏状态 / 距止损
  相对强度 → 强于大盘打分

输出：7 维分数 + 综合信号 + 置信度
"""
from __future__ import annotations

import math
from typing import Dict, Optional

import numpy as np

from core.config import config
from core.database import db
from core.logging import get_logger
from layer3_analysis.trend import compute_all as trend_compute
from layer3_analysis.technical import compute as tech_compute

logger = get_logger("seven_dim")


def _bollinger_band_score(closes: list, price: float) -> dict:
    """布林带位置与宽度评分"""
    if len(closes) < 20:
        return {"bb_position": 50, "bb_width_pct": 0, "bb_score": 0.5}

    recent = [c for c in closes if c is not None][-60:]
    if len(recent) < 20:
        return {"bb_position": 50, "bb_width_pct": 0, "bb_score": 0.5}

    ma20 = float(np.mean(recent[-20:]))
    std20 = float(np.std(recent[-20:]))
    upper = ma20 + 2 * std20
    lower = ma20 - 2 * std20
    width_pct = (upper / lower - 1) * 100 if lower else 0

    # 价格在布林带的位置 0-100
    if upper > lower:
        pos = (price - lower) / (upper - lower) * 100
    else:
        pos = 50
    pos = max(0, min(100, pos))

    # 布林带收窄 = 变盘前兆 → 偏积极；极度扩张 → 偏谨慎
    if width_pct < 15:
        bb_score = 0.6
    elif width_pct < 30:
        bb_score = 0.7 if pos < 50 else 0.5
    else:
        bb_score = 0.4 if pos > 80 else 0.5

    return {"bb_position": round(pos, 1), "bb_width_pct": round(width_pct, 1), "bb_score": round(bb_score, 2)}


def _volume_price_score(rows: list[dict]) -> dict:
    """OBV 简易版 + 量价配合"""
    if len(rows) < 5:
        return {"obv_trend": "flat", "vol_price_corr": 0, "vol_score": 0.5}

    closes = [r["close"] for r in rows[-20:]]
    vols = [r["vol"] for r in rows[-20:]]

    # OBV 归一化方向
    obv = 0
    obv_values = [0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv += vols[i]
        elif closes[i] < closes[i - 1]:
            obv -= vols[i]
        obv_values.append(obv)

    obv_trend = "up" if obv_values[-1] > obv_values[-5] else ("down" if obv_values[-1] < obv_values[-5] else "flat")

    # 简易量价相关性
    try:
        pct_ret = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
        vol_chg = [(vols[i] / (vols[i - 1] + 1) - 1) for i in range(1, len(vols))]
        if len(pct_ret) >= 2:
            corr = float(np.corrcoef(pct_ret, vol_chg)[0, 1]) if not math.isnan(np.corrcoef(pct_ret, vol_chg)[0, 1]) else 0
        else:
            corr = 0
    except Exception:
        corr = 0

    # 量增价增 = 健康；量缩价跌 = 正常；量增价跌 = 警戒
    if obv_trend == "up" and corr > 0:
        vol_score = 0.8
    elif obv_trend == "up":
        vol_score = 0.6
    elif obv_trend == "down" and corr < 0:
        vol_score = 0.3
    else:
        vol_score = 0.5

    return {"obv_trend": obv_trend, "vol_price_corr": round(corr, 2), "vol_score": round(vol_score, 2)}


def _valuation_score(pe: float, high_52w: float, low_52w: float, price: float) -> dict:
    """估值代理评分"""
    # PE 评分
    if pe <= 0:
        pe_score = 0.3
    elif pe < 30:
        pe_score = 0.8
    elif pe < 60:
        pe_score = 0.6
    elif pe < 150:
        pe_score = 0.4
    else:
        pe_score = 0.2

    # 距 52 周位置
    if high_52w and low_52w and high_52w > low_52w:
        pos_52w = (price - low_52w) / (high_52w - low_52w)
        # 偏低位 = 安全边际高
        if pos_52w < 0.3:
            pos_score = 0.7
        elif pos_52w < 0.6:
            pos_score = 0.5
        else:
            pos_score = 0.3
    else:
        pos_52w = 0.5
        pos_score = 0.5

    val_score = round(pe_score * 0.5 + pos_score * 0.5, 2)
    return {"pe": pe, "52w_position": round(pos_52w, 2), "val_score": val_score}


def compute_seven(code: str, name: str, cost: float, stop: float, target: float, n: int = 60) -> dict:
    rows = db.query(
        "SELECT trade_date,open,high,low,close,vol FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT ?",
        (code, n * 2),
    )
    if len(rows) < 30:
        return {"error": f"数据不足({len(rows)}行)", "signal": "WAIT", "total": 0}

    rows_desc = rows
    rows_asc = list(reversed(rows))
    closes_asc = [r["close"] for r in rows_asc]
    price = closes_asc[-1] if closes_asc else 0

    # 1) 趋势维度
    tr = trend_compute(code, n)

    # 2) 均值回归维度（复用六因子计算）
    tech = tech_compute(code)
    mr_total = 0
    if "error" not in tech:
        from layer3_analysis.technical import score as mr_score_fn
        mr = mr_score_fn(tech, config.weights)
        mr_total = mr.get("total", 0)
    else:
        mr = {"scores": {}, "total": 0, "signal": "WAIT"}

    # 3) 波动维度
    bb = _bollinger_band_score(closes_asc, price)

    # 4) 量价维度
    vp = _volume_price_score(rows_asc)

    # 5) 估值维度
    high_52w = max(closes_asc) if closes_asc else price
    low_52w = min(closes_asc) if closes_asc else price
    pe_val = rows_asc[-1].get("pe", 50) if rows_asc and "pe" in rows_asc[-1] else 50
    val = _valuation_score(pe_val, high_52w, low_52w, price)

    # 6) 基本面代理维度
    pct_c = (price / cost - 1) * 100 if cost else 0
    if pct_c > 20:
        fund_score = 0.8
    elif pct_c > 0:
        fund_score = 0.6
    elif pct_c > -10:
        fund_score = 0.4
    else:
        fund_score = 0.2

    # 7) 相对强度维度
    rs_score = tr.get("rel_strength", 50) / 100

    # ── 综合评分 (权重可调) ──
    dims = {
        "trend": round(tr.get("trend_total", 5) / 10, 2),
        "mean_reversion": round(mr_total, 2),
        "volatility": bb["bb_score"],
        "volume_price": vp["vol_score"],
        "valuation": val["val_score"],
        "fundamental": round(fund_score, 2),
        "rel_strength": round(rs_score, 2),
    }

    weights_7 = config.get("seven_dim_weights", default={
        "trend": 0.20,
        "mean_reversion": 0.15,
        "volatility": 0.10,
        "volume_price": 0.15,
        "valuation": 0.10,
        "fundamental": 0.15,
        "rel_strength": 0.15,
    })

    total = sum(dims.get(k, 0) * weights_7.get(k, 0) for k in dims)
    total = round(total * 10, 1)  # 归一化到 0-10

    if total >= 7:
        sig = "STRONG"
    elif total >= 5.5:
        sig = "MODERATE"
    elif total >= 4.0:
        sig = "WEAK"
    else:
        sig = "AVOID"

    return {
        "code": code,
        "name": name,
        "price": price,
        "dimensions": dims,
        "details": {
            "trend": {
                "signal": tr.get("trend_signal"),
                "ma_status": tr.get("ma_status"),
                "adx": tr.get("adx"),
                "macd_div": tr.get("divergence"),
                "rel_strength": tr.get("rel_strength"),
            },
            "mean_reversion": {"factors": mr.get("scores", {}), "total": mr_total, "signal": mr.get("signal")},
            "volatility": bb,
            "volume_price": vp,
            "valuation": val,
            "fundamental": {"pct_cost": round(pct_c, 2)},
            "rel_strength": {"rs_val": tr.get("rel_strength")},
        },
        "total": total,
        "signal": sig,
    }


def compute_all(n: int = 60) -> dict:
    results = {}
    for s in config.stocks:
        c = s["code"]
        r = compute_seven(c, s["name"], s.get("cost", 0), s.get("stop", 0), s.get("target", 0), n)
        results[c] = r
    return dict(sorted(results.items(), key=lambda x: x[1].get("total", 0), reverse=True))
