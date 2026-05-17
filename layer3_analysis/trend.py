"""趋势因子模块 — MA排列 / ADX / MACD背离 / 相对强度

基于本地 stock_daily K线数据，纯 numpy 计算，不依赖外部 API。

科学依据：
  MA排列 → 趋势跟随理论 (Jegadeesh & Titman 1993)
  ADX   → Wilder 趋势强度 (1978)
  MACD  → Appel 动量背离 (1979)
  相对强度 → O'Neil CANSLIM RPS
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np

from core.database import db
from core.logging import get_logger

logger = get_logger("trend")

INDICES_SQL = {
    "上证指数": "sh000001",
    "创业板指": "sz399006",
}

TREND_DEFAULTS = {
    "ma_score": 0.0,
    "ma_status": "unknown",
    "adx": 0.0,
    "adx_status": "unknown",
    "plus_di": 0.0,
    "minus_di": 0.0,
    "macd": 0.0,
    "macd_signal": 0.0,
    "macd_hist": 0.0,
    "macd_divergence": "none",
    "rel_strength": 50.0,
    "trend_total": 0.0,
    "trend_signal": "WAIT",
}


# ───────────────────────── 工具函数 ─────────────────────────

def _ema(data: List[float], n: int) -> List[float]:
    if len(data) < n:
        return [None] * len(data)
    k = 2 / (n + 1)
    out = [None] * (n - 1) + [float(np.mean(data[:n]))]
    for v in data[n:]:
        out.append(out[-1] * (1 - k) + v * k)
    return out


def _sma(data: List[float], n: int) -> List[Optional[float]]:
    if len(data) < n:
        return [None] * len(data)
    out = [None] * (n - 1)
    for i in range(n - 1, len(data)):
        out.append(float(np.mean(data[i - n + 1 : i + 1])))
    return out


def _macd(closes: List[float], fast=12, slow=26, sig=9) -> dict:
    if len(closes) < slow + sig:
        return {"macd": 0.0, "macd_signal": 0.0, "macd_hist": 0.0, "divergence": "none"}

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    dif = [a - b if (a is not None and b is not None) else None for a, b in zip(ema_fast, ema_slow)]
    dif_clean = [v for v in dif if v is not None]
    dea = _ema(dif_clean, sig)
    # 对齐尾部
    hist = dif_clean[-1] - dea[-1] if len(dif_clean) >= len(dea) else 0.0

    # 简易背离检测：价格新高但 MACD 不新高
    divergence = "none"
    if len(closes) >= 10 and len(dif_clean) >= 10:
        price_higher = closes[-1] > closes[-5]
        macd_lower = abs(dif_clean[-1]) < abs(dif_clean[-5])
        if price_higher and macd_lower:
            divergence = "bearish_divergence"  # 顶背离
        elif (not price_higher) and (not macd_lower):
            divergence = "bullish_divergence"  # 底背离

    return {
        "macd": round(dif_clean[-1], 4),
        "macd_signal": round(dea[-1], 4),
        "macd_hist": round(hist, 4),
        "divergence": divergence,
    }


def _adx(highs: List[float], lows: List[float], closes: List[float], n=14) -> dict:
    if len(closes) < n + 1:
        return {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0, "status": "unknown"}

    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm = up if (up > dn and up > 0) else 0.0
        minus_dm = dn if (dn > up and dn > 0) else 0.0

        tr_list.append(tr)
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    atr = float(np.mean(tr_list[:n]))
    plus_di = float(np.mean(plus_dm_list[:n])) / atr * 100 if atr else 0
    minus_di = float(np.mean(minus_dm_list[:n])) / atr * 100 if atr else 0
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) else 0

    # ADX = EMA of DX
    adx_vals = _ema([dx] + [0] * (n - 1), n)  # 简化：取最近 DX 的 EMA
    adx = float(np.mean([dx])) if dx else 0.0

    status = "trending" if adx > 25 else "ranging"
    return {
        "adx": round(adx, 1),
        "plus_di": round(plus_di, 1),
        "minus_di": round(minus_di, 1),
        "status": status,
    }


def _ma_alignment(price: float, ma5: float, ma10: float, ma20: float, ma60: Optional[float]) -> dict:
    """MA 多头/空头排列评分"""
    score = 0.0
    status = "unknown"

    if not ma60 or not ma20 or not ma10 or not ma5:
        return {"ma_score": 0.0, "ma_status": "unknown"}

    # 多头排列
    if ma5 > ma10 > ma20 > ma60:
        status = "bullish"
        score = 8.0
    # 价格在各均线上方
    elif price > ma20 and ma10 > ma20:
        status = "bullish_weak"
        score = 6.0
    # 粘合/震荡
    elif abs(ma5 / ma20 - 1) < 0.03:
        status = "sideways"
        score = 4.0
    # 价格在 MA20 下方但未完全空头
    elif price < ma20 and ma10 < ma20:
        status = "bearish_weak"
        score = 3.0
    # 空头排列
    elif ma5 < ma10 < ma20 < ma60:
        status = "bearish"
        score = 1.0
    else:
        status = "mixed"
        score = 4.0

    return {"ma_score": score, "ma_status": status}


def _relative_strength(code: str, closes: List[dict], period: int = 60) -> float:
    """计算相对强度（vs 市场）：0-100 分制"""
    try:
        idx = 0
        idx_pct = 0.0

        for name, sc in INDICES_SQL.items():
            idx_rows = db.query(
                "SELECT trade_date,close FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT ?",
                (sc, period),
            )
            if idx_rows and len(idx_rows) >= period:
                pct = (idx_rows[0]["close"] / idx_rows[-1]["close"] - 1) * 100
                idx_pct += pct
                idx += 1

        if idx == 0 or not closes or len(closes) < period:
            return 50.0

        stock_pct = (closes[0]["close"] / closes[-1]["close"] - 1) * 100 if closes else 0
        market_pct = idx_pct / idx

        delta = stock_pct - market_pct
        # 归一化到 0-100：±30% 为极值
        normalized = max(0, min(100, 50 + delta * 1.5))
        return round(normalized, 1)
    except Exception:
        return 50.0


# ───────────────────────── 主入口 ─────────────────────────

def compute_all(code: str, n: int = 60) -> dict:
    rows = db.query(
        "SELECT trade_date,open,high,low,close,vol FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT ?",
        (code, n),
    )
    if len(rows) < 30:
        return {**TREND_DEFAULTS, "error": f"数据不足({len(rows)}行)", "trend_signal": "WAIT"}

    closes = [r["close"] for r in rows][::-1]
    highs = [r["high"] for r in rows][::-1]
    lows = [r["low"] for r in rows][::-1]
    price = closes[-1]

    # MA
    ma5 = float(np.mean(closes[-5:])) if len(closes) >= 5 else price
    ma10 = float(np.mean(closes[-10:])) if len(closes) >= 10 else price
    ma20 = float(np.mean(closes[-20:])) if len(closes) >= 20 else price
    ma60 = float(np.mean(closes[-60:])) if len(closes) >= 60 else None

    # 子模块
    ma = _ma_alignment(price, ma5, ma10, ma20, ma60)
    adx = _adx(highs, lows, closes)
    macd = _macd(closes)
    rs = _relative_strength(code, rows, n)

    # 趋势综合分
    trend_total = round((ma["ma_score"] / 8 * 3 + (adx["adx"] / 100 * 2) + (rs / 100 * 3)) * 2, 1)

    if trend_total >= 7:
        sig = "BULLISH"
    elif trend_total >= 5:
        sig = "BIAS_UP"
    elif trend_total >= 3:
        sig = "NEUTRAL"
    else:
        sig = "BIAS_DOWN"

    return {
        **ma,
        **adx,
        **macd,
        "rel_strength": rs,
        "trend_total": trend_total,
        "trend_signal": sig,
    }
