"""L7 买卖临界点精算模块

基于本地 stock_daily K线数据，纯 numpy 计算，不依赖外部 API。

功能模块：
  1. 多周期共振检测 — MA5/MA10/MA20/MA60 排列 + 价格位置，共振评分 0-100
  2. 关键支撑压力位 — 布林带、均线、前高前低、整数关口
  3. 最佳进场区间 — 支撑位 + RSI 超卖 + 波动收敛
  4. 三级卖出点位 — T1 止盈 / T2 减仓 / T3 清仓
  5. 量能异动检测 — 放量/地量 + 攻击量/出货量判断
  6. 盈亏比计算 — 基于进场/止损/止盈计算风险回报比
  7. 多空分水岭 — MA20 牛熊分界线距离与方向

科学依据：
  均线共振 → 格兰维尔八大法则 + 多重时间框架分析
  布林带   → John Bollinger 波动率通道 (1980s)
  RSI      → Wilder 相对强弱指标 (1978)
  量价关系 → 基于 20 日均量的异动识别
  盈亏比   → Van Tharp 风险回报理论
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("entry_exit_calculator")

# ──────────────────────── 常量 ────────────────────────
DEFAULT_LOOKBACK = 120          # 默认回溯 K 线条数
VOL_MA_PERIOD = 20              # 均量周期
BB_PERIOD = 20                  # 布林带周期
BB_STD = 2.0                    # 布林带标准差倍数
RSI_PERIOD = 14                 # RSI 周期
SWING_LOOKBACK = 60             # 前高前低回溯周期
T1_TARGET_RATIO = 0.85          # T1 止盈目标价比例


# ──────────────────────── 工具函数 ────────────────────────

def load_kline(code: str, n: int = DEFAULT_LOOKBACK) -> list:
    """从数据库加载 K 线数据（按日期降序，最近在前）"""
    return db.query(
        "SELECT trade_date, open, high, low, close, vol, pct_chg "
        "FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT ?",
        (code, n),
    )


def _round_number(price: float, direction: str = "both") -> list:
    """计算整数关口（含半分位）作为支撑/压力参考

    Args:
        price: 当前价格
        direction: 'support' 向下取, 'resistance' 向上取, 'both' 双向
    Returns:
        关口价格列表（已去重排序）
    """
    results = []
    # 主整数关口
    base = math.floor(price)
    # 上下各取 5 个整数关口 + 半分位
    for i in range(-5, 6):
        for offset in (0, 0.5):
            if offset == 0.5 and i == 0:
                continue  # 跳过当前价格的半分位，太近无意义
            rn = base + i + offset
            if rn <= 0:
                continue
            if direction == "support" and rn >= price:
                continue
            if direction == "resistance" and rn <= price:
                continue
            if direction == "both":
                if abs(rn - price) < 0.01:
                    continue
            results.append(round(rn, 2))

    results = sorted(set(results))
    return results


def _rsi(closes: List[float], period: int = RSI_PERIOD) -> float:
    """计算 RSI 相对强弱指标"""
    if len(closes) < period + 1:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(period):
        diff = closes[i] - closes[i + 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = gains / losses
    return round(100.0 - 100.0 / (1.0 + rs), 1)


def _bollinger(closes: List[float], period: int = BB_PERIOD, std_mult: float = BB_STD):
    """计算布林带（中轨、上轨、下轨）"""
    if len(closes) < period:
        mid = closes[0] if closes else 0
        return (mid, mid, mid)
    mid = float(np.mean(closes[:period]))
    std = float(np.std(closes[:period], ddof=1))
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return (round(mid, 2), round(upper, 2), round(lower, 2))


def _swing_high_low(highs: List[float], lows: List[float], lookback: int = SWING_LOOKBACK) -> dict:
    """找到近期最高点和最低点（最近 N 根 K 线内）"""
    if not highs or not lows:
        return {"swing_high": 0, "swing_low": 0}
    n = min(lookback, len(highs))
    swing_high = float(np.max(highs[:n]))
    swing_low = float(np.min(lows[:n]))
    return {
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
    }


def _vol_ma(vols: List[float], period: int = VOL_MA_PERIOD) -> float:
    """计算成交量的移动平均"""
    if len(vols) < period:
        return vols[0] if vols else 0
    return float(np.mean(vols[:period]))


def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """计算 ATR 平均真实波幅"""
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(len(closes) - 1):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i + 1]),
            abs(lows[i] - closes[i + 1]),
        )
        trs.append(tr)
    return round(float(np.mean(trs[:period])), 2)


# ──────────────────── 1. 多周期共振检测 ────────────────────

def _resonance_score(price: float, ma5: float, ma10: float, ma20: float,
                     ma60: Optional[float], closes: List[float]) -> dict:
    """多周期共振评分 0-100

    评分逻辑：
      - MA 多头排列 (MA5>MA10>MA20>MA60): 基础分 60
      - MA 空头排列: 基础分 10
      - 价格位于 MA20 上方: +10
      - 价格位于 MA5 上方: +10 (强势)
      - 价格位于所有均线上方: +10
      - 短期均线金叉 (MA5 上穿 MA10): +5
      - MA20 斜率向上: +5
    """
    score = 0
    details = []

    # 基础排列评分
    if ma60 is not None:
        if ma5 > ma10 > ma20 > ma60:
            score += 60
            details.append("MA5>MA10>MA20>MA60 标准多头排列")
        elif ma5 < ma10 < ma20 < ma60:
            score += 10
            details.append("MA5<MA10<MA20<MA60 标准空头排列")
        elif ma5 > ma10 > ma20:
            score += 45
            details.append("MA5>MA10>MA20 短期多头")
        elif ma5 < ma10 < ma20:
            score += 20
            details.append("MA5<MA10<MA20 短期空头")
        else:
            score += 30
            details.append("MA 排列混乱/震荡")
    else:
        if ma5 > ma10 > ma20:
            score += 50
            details.append("MA5>MA10>MA20 多头排列(无MA60)")
        elif ma5 < ma10 < ma20:
            score += 15
            details.append("MA5<MA10<MA20 空头排列(无MA60)")
        else:
            score += 28
            details.append("MA 震荡排列(无MA60)")

    # 价格与均线位置
    if price > ma20:
        score += 10
        details.append("价格在 MA20 上方 +10")
        if price > ma5:
            score += 10
            details.append("价格在 MA5 上方 +10 (强势)")
        if ma60 is not None and price > ma60:
            score += 5
            details.append("价格在 MA60 上方 +5")
    else:
        if price < ma20:
            details.append("价格在 MA20 下方")
        if price < ma5:
            details.append("价格在 MA5 下方 (弱势)")

    # 价格位于所有均线之上（最强状态）
    if ma60 is not None:
        if price > ma5 and price > ma10 and price > ma20 and price > ma60:
            score += 10
            details.append("价格站上全部均线 +10")
    else:
        if price > ma5 and price > ma10 and price > ma20:
            score += 8
            details.append("价格站上全部均线 +8")

    # 短期均线金叉判断（MA5 上穿 MA10 — 需近期数据）
    if len(closes) >= 6:
        prev_ma5 = float(np.mean(closes[1:6]))
        prev_ma10 = float(np.mean(closes[1:11])) if len(closes) >= 11 else prev_ma5
        if prev_ma5 <= prev_ma10 and ma5 > ma10:
            score += 5
            details.append("MA5 金叉 MA10 +5")

    # MA20 斜率向上（当前值 > 5 日前值）
    if len(closes) >= 25:
        prev_ma20 = float(np.mean(closes[5:25]))
        if ma20 > prev_ma20:
            score += 5
            details.append("MA20 斜率向上 +5")
    elif len(closes) >= 21:
        prev_ma20_short = float(np.mean(closes[1:21]))
        if ma20 > prev_ma20_short:
            score += 3
            details.append("MA20 短期斜率向上 +3")

    score = min(score, 100)

    # 共振等级
    if score >= 80:
        level = "强共振"
    elif score >= 60:
        level = "偏多共振"
    elif score >= 40:
        level = "弱共振/震荡"
    elif score >= 20:
        level = "偏空共振"
    else:
        level = "空头共振"

    return {
        "score": score,
        "level": level,
        "details": details,
    }


# ──────────────────── 2. 关键支撑压力位 ────────────────────

def _calc_support_resistance_inner(price: float, ma5: float, ma10: float, ma20: float,
                                     bb_upper: float, bb_lower: float,
                                     swing_high: float, swing_low: float) -> dict:
    """计算支撑位和压力位（内部实现）"""
    supports = []
    resistances = []

    # ── 支撑位候选 ──
    # MA20 支撑
    if ma20 < price:
        supports.append({"price": round(ma20, 2), "type": "MA20均线支撑", "strength": "强"})
    # 布林下轨
    if bb_lower < price:
        supports.append({"price": round(bb_lower, 2), "type": "布林下轨", "strength": "中"})
    # 前低
    if swing_low < price:
        supports.append({"price": round(swing_low, 2), "type": "前低支撑", "strength": "强"})
    # 整数关口（向下取 3 个）
    round_nums = _round_number(price, direction="support")
    for rn in round_nums:
        if rn < price:
            supports.append({"price": rn, "type": "整数关口支撑", "strength": "弱"})
    # MA10 如果低于价格也可作支撑
    if ma10 < price and abs(ma10 - ma20) > price * 0.005:  # 避免与 MA20 重复
        supports.append({"price": round(ma10, 2), "type": "MA10均线支撑", "strength": "中"})

    # 按价格降序排列（离当前价格最近的在前）
    supports.sort(key=lambda x: x["price"], reverse=True)
    # 去重（相同价格取 strength 最高的类型）
    seen = set()
    supports_dedup = []
    for s in supports:
        k = s["price"]
        if k not in seen:
            seen.add(k)
            supports_dedup.append(s)

    # ── 压力位候选 ──
    # MA5
    if ma5 > price:
        resistances.append({"price": round(ma5, 2), "type": "MA5均线压力", "strength": "中"})
    # MA10
    if ma10 > price:
        resistances.append({"price": round(ma10, 2), "type": "MA10均线压力", "strength": "中"})
    # 布林上轨
    if bb_upper > price:
        resistances.append({"price": round(bb_upper, 2), "type": "布林上轨", "strength": "中"})
    # 前高
    if swing_high > price:
        resistances.append({"price": round(swing_high, 2), "type": "前高压力", "strength": "强"})
    # 整数关口（向上取 3 个）
    round_nums_up = _round_number(price, direction="resistance")
    for rn in round_nums_up:
        if rn > price:
            resistances.append({"price": rn, "type": "整数关口压力", "strength": "弱"})

    # 按价格升序排列（离当前价格最近的在前）
    resistances.sort(key=lambda x: x["price"])
    seen_r = set()
    resistances_dedup = []
    for r in resistances:
        k = r["price"]
        if k not in seen_r:
            seen_r.add(k)
            resistances_dedup.append(r)

    return {
        "supports": supports_dedup[:3],
        "resistances": resistances_dedup[:3],
    }


# ──────────────────── 3. 最佳进场区间 ────────────────────

def _calc_entry_zone_inner(price: float, ma20: float, bb_lower: float, swing_low: float,
                           rsi14: float, vol_ratio: float, atr14: float) -> dict:
    """计算最佳进场区间

    逻辑：
      - 价格回踩 MA20 附近（距 MA20 +-2%）= 较好时机
      - RSI < 50 表示未过热
      - 缩量（vol_ratio < 0.8）表示卖压减弱
      - 综合以上因素给出加分和进场区间
    """
    entry_low = max(bb_lower, swing_low)
    entry_high = min(ma20, price * 0.98) if ma20 < price else ma20

    # 确保下界 < 上界
    if entry_low >= entry_high:
        entry_low = max(bb_lower * 0.98, swing_low * 0.98)
        entry_high = ma20 if ma20 > entry_low else entry_low * 1.02

    score = 0
    reasons = []

    # 距 MA20 的距离
    dist_to_ma20 = (price / ma20 - 1) * 100 if ma20 else 0
    if abs(dist_to_ma20) <= 3:
        score += 30
        reasons.append(f"价格距MA20仅{dist_to_ma20:+.1f}%，处于回踩区间")
    elif abs(dist_to_ma20) <= 5:
        score += 20
        reasons.append(f"价格距MA20 {dist_to_ma20:+.1f}%，较近但未完全回踩")
    elif dist_to_ma20 < -5:
        score += 5
        reasons.append(f"价格远低于MA20 {dist_to_ma20:.1f}%，趋势偏弱需谨慎")
    else:
        score += 10
        reasons.append(f"价格高于MA20 {dist_to_ma20:.1f}%，等待回踩")

    # RSI 状态
    if rsi14 < 30:
        score += 25
        reasons.append(f"RSI={rsi14} 超卖区域，反弹概率大")
    elif rsi14 < 50:
        score += 20
        reasons.append(f"RSI={rsi14} 偏低，有上行空间")
    elif rsi14 < 70:
        score += 10
        reasons.append(f"RSI={rsi14} 中性偏强")
    else:
        score += 0
        reasons.append(f"RSI={rsi14} 超买区域，不宜进场")

    # 量能状态
    if vol_ratio < 0.5:
        score += 25
        reasons.append(f"量比={vol_ratio:.2f} 地量，卖压枯竭")
    elif vol_ratio < 0.8:
        score += 15
        reasons.append(f"量比={vol_ratio:.2f} 缩量，抛压减轻")
    elif vol_ratio <= 1.2:
        score += 10
        reasons.append(f"量比={vol_ratio:.2f} 正常量能")
    else:
        score += 5
        reasons.append(f"量比={vol_ratio:.2f} 放量，需观察方向")

    # ATR 波动率
    atr_pct = (atr14 / price * 100) if price else 0
    if atr_pct < 2:
        score += 10
        reasons.append(f"ATR={atr_pct:.1f}% 低波动收敛，适合布局")
    elif atr_pct < 5:
        score += 5
        reasons.append(f"ATR={atr_pct:.1f}% 波动适中")

    score = min(score, 100)

    # 进场评级
    if score >= 70:
        grade = "A级（强烈推荐）"
    elif score >= 50:
        grade = "B级（建议关注）"
    elif score >= 30:
        grade = "C级（观望等待）"
    else:
        grade = "D级（不建议进场）"

    return {
        "entry_low": round(entry_low, 2),
        "entry_high": round(entry_high, 2),
        "entry_mid": round((entry_low + entry_high) / 2, 2),
        "score": score,
        "grade": grade,
        "reasons": reasons,
        "dist_to_ma20_pct": round(dist_to_ma20, 1),
    }


# ──────────────────── 4. 三级卖出点位 ────────────────────

def _calc_exit_points_inner(price: float, target_price: float, stop_loss: float,
                            ma10: float, ma20: float, rsi14: float) -> dict:
    """计算三级卖出点位

    T1 - 止盈位: 目标价的 85%
    T2 - 减仓位: 跌破 MA10 或 RSI > 80
    T3 - 清仓位: 跌破 MA20 或止损价
    """
    # T1 止盈位
    t1_price = round(target_price * T1_TARGET_RATIO, 2)
    t1_condition = f"价格触及 {t1_price}（目标价 {target_price} 的 {int(T1_TARGET_RATIO*100)}%）"

    # T2 减仓位
    t2_price_ma10 = round(ma10, 2)
    t2_condition = (
        f"① 收盘跌破 MA10 ({t2_price_ma10})，或"
        f" ② RSI 日线 > 80 超买"
    )

    # T3 清仓位
    t3_price = round(max(ma20, stop_loss), 2)
    t3_condition = (
        f"① 收盘跌破 MA20 ({round(ma20, 2)})，或"
        f" ② 跌破止损价 {stop_loss}"
    )

    # T1 距离
    t1_dist = round((t1_price / price - 1) * 100, 1) if price else 0
    t2_dist = round((t2_price_ma10 / price - 1) * 100, 1) if price else 0
    t3_dist = round((t3_price / price - 1) * 100, 1) if price else 0

    return {
        "T1_止盈位": {
            "price": t1_price,
            "type": "止盈",
            "condition": t1_condition,
            "dist_pct": t1_dist,
        },
        "T2_减仓位": {
            "price": t2_price_ma10,
            "type": "减仓",
            "condition": t2_condition,
            "dist_pct": t2_dist,
        },
        "T3_清仓位": {
            "price": t3_price,
            "type": "清仓",
            "condition": t3_condition,
            "dist_pct": t3_dist,
        },
    }


# ──────────────────── 5. 量能异动检测 ────────────────────

def _detect_volume_anomaly_inner(vol: float, vol_ma20: float, pct_chg: float) -> dict:
    """检测量能异动

    规则：
      - 量比 > 1.5: 放量
      - 量比 < 0.5: 地量
      - 放量 + 上涨: 攻击量
      - 放量 + 下跌: 出货量
    """
    vol_ratio = round(vol / vol_ma20, 2) if vol_ma20 else 1.0

    if vol_ratio > 1.5:
        if pct_chg > 0:
            anomaly_type = "攻击量"
            desc = f"量比={vol_ratio}，放量上涨，主力资金主动买入"
            signal = "偏多"
        elif pct_chg < 0:
            anomaly_type = "出货量"
            desc = f"量比={vol_ratio}，放量下跌，主力资金主动卖出"
            signal = "偏空"
        else:
            anomaly_type = "异常放量"
            desc = f"量比={vol_ratio}，放量平盘，多空分歧加剧"
            signal = "中性"
    elif vol_ratio < 0.5:
        anomaly_type = "地量"
        desc = f"量比={vol_ratio}，成交极度萎缩，变盘前兆"
        signal = "中性偏多（地量见地价）" if pct_chg <= 0 else "中性偏空（缩量上涨需警惕）"
    elif vol_ratio > 1.2:
        anomaly_type = "温和放量"
        desc = f"量比={vol_ratio}，成交温和放大"
        signal = "中性"
    elif vol_ratio > 0.8:
        anomaly_type = "正常量能"
        desc = f"量比={vol_ratio}，成交正常"
        signal = "中性"
    else:
        anomaly_type = "缩量"
        desc = f"量比={vol_ratio}，成交清淡"
        signal = "中性"

    return {
        "vol_ratio": vol_ratio,
        "vol_today": vol,
        "vol_ma20": round(vol_ma20, 0),
        "anomaly_type": anomaly_type,
        "description": desc,
        "signal": signal,
    }


# ──────────────────── 6. 盈亏比计算 ────────────────────

def _calc_risk_reward_inner(entry: float, stop_loss: float, target: float) -> dict:
    """计算盈亏比（风险回报比）

    Args:
        entry: 进场价格
        stop_loss: 止损价格
        target: 止盈目标价格
    Returns:
        盈亏比、风险金额、潜在收益等
    """
    if entry <= 0 or stop_loss <= 0 or target <= 0:
        return {"error": "参数异常，价格不能为零或负数"}

    risk = abs(entry - stop_loss)          # 每股风险
    reward = abs(target - entry)           # 每股潜在收益

    if risk == 0:
        return {"error": "止损价与进场价相同，风险为零无法计算"}

    rr_ratio = round(reward / risk, 2)

    # 风险百分比
    risk_pct = round(risk / entry * 100, 2)
    reward_pct = round(reward / entry * 100, 2)

    # 评级
    if rr_ratio >= 3:
        rr_grade = "优秀"
    elif rr_ratio >= 2:
        rr_grade = "良好"
    elif rr_ratio >= 1.5:
        rr_grade = "一般"
    elif rr_ratio >= 1:
        rr_grade = "勉强合格"
    else:
        rr_grade = "不合格（风险大于收益）"

    return {
        "entry_price": entry,
        "stop_loss": stop_loss,
        "target_price": target,
        "risk_per_share": round(risk, 2),
        "reward_per_share": round(reward, 2),
        "risk_pct": risk_pct,
        "reward_pct": reward_pct,
        "rr_ratio": rr_ratio,
        "grade": rr_grade,
    }


# ──────────────────── 7. 多空分水岭 ────────────────────

def _calc_watershed(price: float, ma20: float) -> dict:
    """计算多空分水岭（MA20 牛熊分界线）"""
    if ma20 <= 0:
        return {"watershed": 0, "dist_pct": 0, "direction": "数据不足"}

    dist = price - ma20
    dist_pct = round(dist / ma20 * 100, 1)

    if dist > 0:
        direction = "多头区域"
        status = "价格在牛熊分界线上方，偏多"
    elif dist < 0:
        direction = "空头区域"
        status = "价格在牛熊分界线下方，偏空"
    else:
        direction = "分界线"
        status = "价格恰在牛熊分界线上，方向待定"

    return {
        "watershed_price": round(ma20, 2),
        "current_price": price,
        "distance": round(dist, 2),
        "dist_pct": dist_pct,
        "direction": direction,
        "status": status,
    }


# ──────────────────── 公开 API ────────────────────

def calc_support_resistance(code: str) -> dict:
    """计算支撑压力位

    Returns:
        {
            "code": "000001.SZ",
            "price": 12.50,
            "supports": [{price, type, strength}, ...],   # 最近 3 个支撑位
            "resistances": [{price, type, strength}, ...], # 最近 3 个压力位
        }
    """
    rows = load_kline(code, DEFAULT_LOOKBACK)
    if len(rows) < 20:
        return {"code": code, "error": f"数据不足({len(rows)}行，需>=20行)"}

    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    price = closes[0]

    # 均线
    ma5 = round(float(np.mean(closes[:5])), 2) if len(closes) >= 5 else price
    ma10 = round(float(np.mean(closes[:10])), 2) if len(closes) >= 10 else price
    ma20 = round(float(np.mean(closes[:20])), 2) if len(closes) >= 20 else price

    # 布林带
    _, bb_upper, bb_lower = _bollinger(closes)

    # 前高前低
    sw = _swing_high_low(highs, lows)

    result = _calc_support_resistance_inner(
        price, ma5, ma10, ma20, bb_upper, bb_lower, sw["swing_high"], sw["swing_low"]
    )
    result["code"] = code
    result["price"] = price
    return result


def calc_entry_zone(code: str) -> dict:
    """计算最佳进场区间

    Returns:
        {
            "code", "price",
            "entry_low", "entry_high", "entry_mid",   # 进场价格区间
            "score", "grade", "reasons",               # 进场评分与理由
        }
    """
    rows = load_kline(code, DEFAULT_LOOKBACK)
    if len(rows) < 30:
        return {"code": code, "error": f"数据不足({len(rows)}行，需>=30行)"}

    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    vols = [r["vol"] for r in rows]
    price = closes[0]

    ma20 = round(float(np.mean(closes[:20])), 2) if len(closes) >= 20 else price
    _, _, bb_lower = _bollinger(closes)
    sw = _swing_high_low(highs, lows)
    rsi14 = _rsi(closes)
    vol_ma20 = _vol_ma(vols)
    vol_ratio = round(vols[0] / vol_ma20, 2) if vol_ma20 else 1.0
    atr14 = _atr(highs, lows, closes)

    result = _calc_entry_zone_inner(price, ma20, bb_lower, sw["swing_low"],
                                     rsi14, vol_ratio, atr14)
    result["code"] = code
    result["price"] = price
    return result


def calc_exit_points(code: str) -> dict:
    """计算 T1/T2/T3 卖出点位

    Returns:
        {
            "code", "price",
            "T1_止盈位": {price, type, condition, dist_pct},
            "T2_减仓位": {price, type, condition, dist_pct},
            "T3_清仓位": {price, type, condition, dist_pct},
        }
    """
    rows = load_kline(code, DEFAULT_LOOKBACK)
    if len(rows) < 30:
        return {"code": code, "error": f"数据不足({len(rows)}行，需>=30行)"}

    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    price = closes[0]

    ma10 = round(float(np.mean(closes[:10])), 2) if len(closes) >= 10 else price
    ma20 = round(float(np.mean(closes[:20])), 2) if len(closes) >= 20 else price
    rsi14 = _rsi(closes)
    atr14 = _atr(highs, lows, closes)

    # 目标价：近期高点 + 1 倍 ATR 作为保守目标
    sw = _swing_high_low(highs, lows, lookback=20)
    target_price = round(sw["swing_high"] + atr14, 2)
    # 止损价：MA20 下方 1 倍 ATR 或 近期低点，取较低者
    stop_loss = round(min(ma20 - atr14, sw["swing_low"] * 0.97), 2)

    result = _calc_exit_points_inner(price, target_price, stop_loss, ma10, ma20, rsi14)
    result["code"] = code
    result["price"] = price
    result["target_price"] = target_price
    result["stop_loss"] = stop_loss
    return result


def detect_volume_anomaly(code: str) -> dict:
    """检测量能异动

    Returns:
        {code, vol_ratio, vol_today, vol_ma20, anomaly_type, description, signal}
    """
    rows = load_kline(code, DEFAULT_LOOKBACK)
    if len(rows) < VOL_MA_PERIOD + 1:
        return {"code": code, "error": f"数据不足({len(rows)}行，需>={VOL_MA_PERIOD + 1}行)"}

    vols = [r["vol"] for r in rows]
    pct_chgs = [r["pct_chg"] for r in rows]
    vol_today = vols[0]
    pct_today = pct_chgs[0] if pct_chgs[0] is not None else 0
    vol_ma20 = _vol_ma(vols)

    result = _detect_volume_anomaly_inner(vol_today, vol_ma20, pct_today)
    result["code"] = code
    return result


def calc_risk_reward(code: str, entry: float, stop_loss: float, target: float) -> dict:
    """计算盈亏比

    Args:
        code: 股票代码
        entry: 进场价格
        stop_loss: 止损价格
        target: 止盈目标价格
    Returns:
        盈亏比及相关指标
    """
    result = _calc_risk_reward_inner(entry, stop_loss, target)
    result["code"] = code
    return result


def full_calc(code: str, target_price: Optional[float] = None,
              stop_loss: Optional[float] = None) -> dict:
    """完整精算结果 — 调用所有子模块一次性输出

    Args:
        code: 股票代码
        target_price: 目标价（可选，不传则自动计算）
        stop_loss: 止损价（可选，不传则自动计算）

    Returns:
        {
            "code", "name", "price",
            "resonance": {...},           # 共振检测
            "support_resistance": {...},  # 支撑压力位
            "entry_zone": {...},          # 进场区间
            "exit_points": {...},         # 三级卖出
            "volume_anomaly": {...},      # 量能异动
            "risk_reward": {...},         # 盈亏比
            "watershed": {...},           # 多空分水岭
        }
    """
    rows = load_kline(code, DEFAULT_LOOKBACK)
    if len(rows) < 60:
        return {"code": code, "error": f"数据不足({len(rows)}行，需>=60行进行完整精算)"}

    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    vols = [r["vol"] for r in rows]
    pct_chgs = [r["pct_chg"] for r in rows]

    price = closes[0]

    # 均线
    ma5 = round(float(np.mean(closes[:5])), 2)
    ma10 = round(float(np.mean(closes[:10])), 2)
    ma20 = round(float(np.mean(closes[:20])), 2)
    ma60 = round(float(np.mean(closes[:60])), 2) if len(closes) >= 60 else None

    # 布林带
    bb_mid, bb_upper, bb_lower = _bollinger(closes)

    # 前高前低
    sw = _swing_high_low(highs, lows)

    # RSI
    rsi14 = _rsi(closes)

    # 量能
    vol_ma20 = _vol_ma(vols)
    vol_ratio = round(vols[0] / vol_ma20, 2) if vol_ma20 else 1.0

    # ATR
    atr14 = _atr(highs, lows, closes)

    # 当日涨跌
    pct_today = pct_chgs[0] if pct_chgs[0] is not None else 0

    # ── 1. 共振检测 ──
    resonance = _resonance_score(price, ma5, ma10, ma20, ma60, closes)

    # ── 2. 支撑压力位 ──
    sr = _calc_support_resistance_inner(price, ma5, ma10, ma20, bb_upper, bb_lower,
                                         sw["swing_high"], sw["swing_low"])

    # ── 3. 进场区间 ──
    entry_zone = _calc_entry_zone_inner(price, ma20, bb_lower, sw["swing_low"],
                                         rsi14, vol_ratio, atr14)

    # ── 4. 三级卖出 ──
    if target_price is None:
        target_price = round(sw["swing_high"] + atr14, 2)
    if stop_loss is None:
        stop_loss = round(min(ma20 - atr14, sw["swing_low"] * 0.97), 2)
    exit_points = _calc_exit_points_inner(price, target_price, stop_loss, ma10, ma20, rsi14)

    # ── 5. 量能异动 ──
    volume_anomaly = _detect_volume_anomaly_inner(vols[0], vol_ma20, pct_today)

    # ── 6. 盈亏比 ──
    risk_reward = _calc_risk_reward_inner(entry_zone["entry_high"], stop_loss, target_price)

    # ── 7. 多空分水岭 ──
    watershed = _calc_watershed(price, ma20)

    return {
        "code": code,
        "price": price,
        "pct_chg": round(pct_today, 2),
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma60": ma60,
        "atr14": atr14,
        "rsi14": rsi14,
        "resonance": resonance,
        "support_resistance": sr,
        "entry_zone": entry_zone,
        "exit_points": exit_points,
        "volume_anomaly": volume_anomaly,
        "risk_reward": risk_reward,
        "watershed": watershed,
    }


def batch_calc(codes: Optional[List[str]] = None) -> dict:
    """批量精算（默认使用 config 中的自选股列表）"""
    if codes is None:
        codes = [s["code"] for s in config.stocks]

    results = {}
    for code in codes:
        try:
            r = full_calc(code)
        except Exception as e:
            logger.error(f"[{code}] 精算失败: {e}")
            r = {"code": code, "error": str(e)}
        results[code] = r

    return results


# ──────────────────── CLI 调试入口 ────────────────────

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("用法: python entry_exit_calculator.py <股票代码>")
        print("示例: python entry_exit_calculator.py 000001.SZ")
        sys.exit(1)

    code = sys.argv[1]
    result = full_calc(code)

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
