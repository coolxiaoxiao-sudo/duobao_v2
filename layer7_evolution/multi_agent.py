"""多智能体协同研判模块 — 宏观/行业/基本面/技术面/资金面/风控交叉验证

每个 Agent 独立打分，最终由 Chairman 综合裁定，杜绝片面判断。
决策逻辑可追溯，每项评分附带推导过程。
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("multi_agent")

# 从腾讯API获取指数数据
try:
    from layer1_data.tencent_api import get_indices
except:
    get_indices = lambda: {}


def _safe_get(d, *keys, default=0):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d if d is not None else default


class MacroAgent:
    """宏观Agent — 大盘环境研判"""

    def assess(self, indices: dict = None) -> dict:
        if indices is None:
            indices = get_indices()
        score = 5.0  # 中性起点
        signals = []

        # 分析各大指数
        for name, data in indices.items():
            if not isinstance(data, dict):
                continue
            pct = _safe_get(data, "pct_chg", default=0)
            vol_ratio = _safe_get(data, "volume_ratio", default=1)

            if pct > 1:
                score += 0.5
                signals.append(f"{name}涨幅{pct:.1f}%，偏多")
            elif pct < -1:
                score -= 0.5
                signals.append(f"{name}跌幅{abs(pct):.1f}%，偏空")

            if vol_ratio > 1.2:
                score += 0.3
                signals.append(f"{name}放量{vol_ratio:.1f}倍")
            elif vol_ratio < 0.7:
                score -= 0.3
                signals.append(f"{name}缩量")

        # 科创50特殊加权（科技方向引领）
        kechuang_pct = 0
        for name, data in indices.items():
            if "科创" in str(name):
                kechuang_pct = _safe_get(data, "pct_chg", default=0)
                break
        if kechuang_pct > 0.5:
            score += 0.5
            signals.append(f"科创50领涨{kechuang_pct}%，科技方向活跃")

        score = max(1, min(10, score))
        status = "BULL" if score >= 7 else ("SIDEWAYS" if score >= 4 else "BEAR")
        return {
            "agent": "宏观", "score": round(score, 1), "status": status,
            "signals": signals,
            "verdict": f"大盘{status}，评分{score:.1f}/10",
        }


class SectorAgent:
    """行业Agent — 板块轮动与题材周期"""

    def assess(self, portfolio: list) -> dict:
        industries = {}
        for s in portfolio:
            ind = s.get("industry", "其他")
            if ind not in industries:
                industries[ind] = []
            industries[ind].append(s)

        score = 5.0
        signals = []
        sector_scores = {}

        for ind, stocks in industries.items():
            # 行业内平均趋势强度
            avg_trend = 0
            for s in stocks:
                try:
                    from layer3_analysis.trend import compute_all as trend_compute
                    tr = trend_compute(s["code"], 60)
                    avg_trend += _safe_get(tr, "trend_total", default=5)
                except:
                    avg_trend += 5
            avg_trend /= len(stocks) if stocks else 1

            # 行业评分
            if avg_trend >= 7:
                ind_score = 8
                signals.append(f"{ind}强势(均趋势{avg_trend:.1f})")
            elif avg_trend >= 5:
                ind_score = 6
                signals.append(f"{ind}中性(均趋势{avg_trend:.1f})")
            else:
                ind_score = 3
                signals.append(f"{ind}弱势(均趋势{avg_trend:.1f})")

            sector_scores[ind] = {"avg_trend": round(avg_trend, 1), "score": ind_score}

        # 综合: 有强势行业加分
        strong = sum(1 for v in sector_scores.values() if v["score"] >= 7)
        weak = sum(1 for v in sector_scores.values() if v["score"] <= 3)
        score = 5 + strong * 1.5 - weak * 1.0
        score = max(1, min(10, score))

        return {
            "agent": "行业", "score": round(score, 1),
            "signals": signals, "sectors": sector_scores,
            "verdict": f"行业分散度正常，强势行业{strong}个",
        }


class FundamentalAgent:
    """基本面Agent — 估值与财务健康度"""

    def assess_single(self, code: str, name: str, industry: str) -> dict:
        try:
            from layer5_execution.audit import _pe_b_score, _industry_bonus
            pe_score = _pe_b_score(code)
            ind_bonus = _industry_bonus(industry)
        except:
            pe_score = 5
            ind_bonus = 0

        score = pe_score + ind_bonus
        signals = []

        if pe_score >= 7:
            signals.append("PE低估")
        elif pe_score <= 2:
            signals.append("PE亏损或高估")

        if ind_bonus > 0:
            signals.append(f"{industry}行业加成+{ind_bonus}")

        return {
            "agent": "基本面", "name": name, "code": code,
            "score": round(score, 1), "pe_score": pe_score,
            "signals": signals,
        }


class TechnicalAgent:
    """技术面Agent — 六因子 + 趋势双重确认"""

    def assess_single(self, code: str, name: str) -> dict:
        try:
            from layer3_analysis.technical import compute, score_with_trend
            from layer3_analysis.trend import compute_all as trend_compute
            tech = compute(code)
            tr = trend_compute(code, 60)
            sc = score_with_trend(tech, tr)

            factors_detail = sc.get("scores", {})
            top_factor = max(factors_detail, key=factors_detail.get) if factors_detail else "N/A"
            bottom_factor = min(factors_detail, key=factors_detail.get) if factors_detail else "N/A"

            return {
                "agent": "技术面", "name": name, "code": code,
                "score": sc.get("total", 5), "signal": sc.get("signal", "HOLD"),
                "trend_score": _safe_get(tr, "trend_total", default=5),
                "top_factor": top_factor,
                "bottom_factor": bottom_factor,
                "factors": factors_detail,
            }
        except Exception as e:
            return {"agent": "技术面", "name": name, "code": code,
                    "score": 5, "signal": "HOLD", "error": str(e)}


class CapitalAgent:
    """资金面Agent — 量价关系与主力动向"""

    def assess_single(self, code: str, name: str) -> dict:
        try:
            from layer3_analysis.technical import compute
            tech = compute(code)
            vol_ratio = _safe_get(tech, "vol_ratio", default=1)
            rsi = _safe_get(tech, "rsi14", default=50)
        except:
            vol_ratio = 1
            rsi = 50

        score = 5.0
        signals = []

        # 量能分析
        if vol_ratio > 1.5:
            score += 2
            signals.append("放量1.5倍+，资金活跃")
        elif vol_ratio > 1.2:
            score += 1
            signals.append("放量，量能温和放大")
        elif vol_ratio < 0.5:
            score -= 2
            signals.append("严重缩量，资金冷清")
        elif vol_ratio < 0.7:
            score -= 1
            signals.append("缩量，交投清淡")

        # RSI位置
        if rsi > 80:
            score -= 1.5
            signals.append(f"RSI={rsi}超买，追高风险")
        elif rsi < 30:
            score += 1
            signals.append(f"RSI={rsi}超卖，反弹可能")
        elif rsi > 70:
            score -= 0.5
            signals.append(f"RSI={rsi}偏高")
        elif rsi < 40:
            score += 0.5
            signals.append(f"RSI={rsi}偏低")

        score = max(1, min(10, score))
        return {
            "agent": "资金面", "name": name, "code": code,
            "score": round(score, 1), "vol_ratio": vol_ratio, "rsi": rsi,
            "signals": signals,
        }


class RiskAgent:
    """风控Agent — 风险预判与仓位建议"""

    def assess_single(self, code: str, name: str, cost: float, stop: float) -> dict:
        try:
            from layer3_analysis.technical import compute
            tech = compute(code)
            price = _safe_get(tech, "price", default=0)
            rsi = _safe_get(tech, "rsi14", default=50)
            atr_pct = _safe_get(tech, "atr_pct", default=5)
        except:
            price = 0
            rsi = 50
            atr_pct = 5

        score = 5.0
        signals = []
        risk_level = "MEDIUM"

        # 距止损距离
        if stop and price:
            margin = (price / stop - 1) * 100
            if margin < 5:
                score -= 2
                signals.append(f"距止损仅{margin:.1f}%，高危")
                risk_level = "HIGH"
            elif margin < 10:
                score -= 1
                signals.append(f"距止损{margin:.1f}%，需关注")

        # 距成本
        if cost and price:
            pnl = (price / cost - 1) * 100
            if pnl < -30:
                score -= 2
                signals.append(f"深套{pnl:.1f}%，流动性风险")
                risk_level = "HIGH"
            elif pnl < -15:
                score -= 1
                signals.append(f"浮亏{pnl:.1f}%")

        # ATR 波动风险
        if atr_pct > 8:
            score -= 1
            signals.append(f"高波动ATR{atr_pct:.1f}%")
        elif atr_pct < 3:
            score += 0.5
            signals.append(f"低波动，风险可控")

        # RSI极端值
        if rsi > 85:
            score -= 1.5
            signals.append("RSI极端超买，回撤风险高")

        max_drawdown_risk = max(0, score)
        score = max(1, min(10, score))

        return {
            "agent": "风控", "name": name, "code": code,
            "score": round(score, 1), "risk_level": risk_level,
            "max_drawdown_risk": round(max_drawdown_risk, 1),
            "signals": signals,
        }


class Chairman:
    """主席Agent — 综合裁定"""


    def deliberate(self, code, name, agent_results):
        scores = [r.get("score", 5) for r in agent_results if "score" in r]
        if not scores:
            return {"verdict": "数据不足", "confidence": 0, "grade": "D"}

        avg_score = np.mean(scores)
        score_std = np.std(scores) if len(scores) > 1 else 0

        weights = {"宏观": 0.10, "行业": 0.10, "基本面": 0.15,
                   "技术面": 0.35, "资金面": 0.15, "风控": 0.15}
        weighted = 0; total_w = 0
        for r in agent_results:
            agent = r.get("agent", ""); w = weights.get(agent, 0.1); s = r.get("score", 5)
            weighted += s * w; total_w += w
        final_score = weighted / total_w if total_w > 0 else avg_score

        if score_std < 1.0: consensus = "HIGH"
        elif score_std < 2.0: consensus = "MEDIUM"
        else: consensus = "LOW"

        if final_score >= 7: signal = "STRONG_BUY"
        elif final_score >= 5.5: signal = "BUY"
        elif final_score >= 4: signal = "HOLD"
        elif final_score >= 2.5: signal = "REDUCE"
        else: signal = "SELL"

        bull_agents = sum(1 for s in scores if s >= 6)
        bear_agents = sum(1 for s in scores if s <= 4)
        net_agents = bull_agents - bear_agents

        if final_score >= 6.5 and consensus == "HIGH" and net_agents >= 4:
            grade = "A"; grade_desc = "高度确定看多"
        elif final_score >= 5.5 and consensus in ("HIGH","MEDIUM") and net_agents >= 2:
            grade = "B"; grade_desc = "偏多确定"
        elif final_score <= 3.5 and consensus in ("HIGH","MEDIUM") and net_agents <= -3:
            grade = "D"; grade_desc = "高度确定看空"
        elif consensus == "LOW" or abs(final_score - 5) < 1.5:
            grade = "C"; grade_desc = "多空分歧"
        elif final_score >= 4.5:
            grade = "B"; grade_desc = "偏多但不确定"
        else:
            grade = "C"; grade_desc = "中性偏弱"

        logic_chain = []
        for r in agent_results:
            agent = r.get("agent","?"); s = r.get("score",5); sigs = r.get("signals",[])
            if s >= 7: logic_chain.append(f"[{agent}] {s}/10 强看多: {'; '.join(sigs[:2])}")
            elif s <= 3: logic_chain.append(f"[{agent}] {s}/10 看空: {'; '.join(sigs[:2])}")
            else: logic_chain.append(f"[{agent}] {s}/10 中性")

        dissent = []
        if consensus == "LOW":
            high = max(scores); low = min(scores)
            ha = [r.get("agent") for r in agent_results if r.get("score")==high]
            la = [r.get("agent") for r in agent_results if r.get("score")==low]
            dissent.append(f"{'/'.join(ha)}({high}) vs {'/'.join(la)}({low})")

        hazards = []
        for r in agent_results:
            if r.get("agent")=="风控" and r.get("risk_level") in ("HIGH","CRITICAL"):
                hazards.extend(r.get("signals",[]))

        return {
            "code": code, "name": name, "final_score": round(final_score,1),
            "signal": signal, "grade": grade, "grade_desc": grade_desc,
            "consensus": consensus, "confidence": round(1-score_std/5,2),
            "dissent": dissent, "logic_chain": logic_chain, "hazards": hazards[:3],
            "agent_scores": {r.get("agent","?"):r.get("score",5) for r in agent_results},
            "verdict": f"等级{grade} | 综合{final_score:.1f} | {grade_desc}",
        }



def multi_agent_analyze(code: str, name: str, industry: str,
                        cost: float, stop: float, indices: dict = None) -> dict:
    """多智能体协同研判 —— 对单只股票"""
    macro = MacroAgent()
    sector = SectorAgent()
    fund = FundamentalAgent()
    tech = TechnicalAgent()
    capital = CapitalAgent()
    risk = RiskAgent()
    chair = Chairman()

    # 宏观
    macro_result = macro.assess(indices)

    # 行业（基于全持仓）
    portfolio = config.stocks
    sector_result = sector.assess(portfolio)

    # 基本面
    fund_result = fund.assess_single(code, name, industry)

    # 技术面
    tech_result = tech.assess_single(code, name)

    # 资金面
    capital_result = capital.assess_single(code, name)

    # 风控
    risk_result = risk.assess_single(code, name, cost, stop)

    # 汇总到Chairman
    agent_results = [macro_result, sector_result, fund_result, tech_result, capital_result, risk_result]
    verdict = chair.deliberate(code, name, agent_results)

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "verdict": verdict,
        "macro": macro_result,
        "sector": sector_result,
        "fundamental": fund_result,
        "technical": tech_result,
        "capital": capital_result,
        "risk": risk_result,
    }


def portfolio_batch_analyze() -> dict:
    """全持仓多Agent协同研判"""
    indices = get_indices()
    results = {}
    for s in config.stocks:
        try:
            results[s["code"]] = multi_agent_analyze(
                s["code"], s["name"], s.get("industry", ""),
                s.get("cost", 0), s.get("stop", 0), indices)
        except Exception as e:
            results[s["code"]] = {"error": str(e), "name": s["name"]}

    # 持仓总结
    signals = {}
    for code, r in results.items():
        if "verdict" in r:
            sig = r["verdict"].get("signal", "HOLD")
            signals[sig] = signals.get(sig, 0) + 1

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "results": results,
        "signal_distribution": signals,
    }
