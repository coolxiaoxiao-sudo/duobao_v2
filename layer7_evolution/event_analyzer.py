"""事件驱动超前推演 — 政策/供需/经营拐点/订单业绩催化预判

核心能力：
  1. 识别潜在催化事件类型
  2. 预判事件落地前预期炒作节奏
  3. 预判事件落地后利好兑现/见光死走势
  4. 提前布局 + 规避利好陷阱
"""
from __future__ import annotations

import json, os
from datetime import datetime
from typing import Dict, List, Optional

from core.config import config
from core.logging import get_logger

logger = get_logger("event_analyzer")

EVENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "events")
os.makedirs(EVENT_DIR, exist_ok=True)


# 行业事件模板库
EVENT_TEMPLATES = {
    "计算机": [
        {"type": "政策", "name": "数字经济/AI政策", "timing": "两会/中央会议", "pre_effect": "预期炒作1-2周", "post_effect": "分化，龙头持续"},
        {"type": "订单", "name": "大额订单公告", "timing": "不定期", "pre_effect": "提前3-5天异动", "post_effect": "公告即高点"},
    ],
    "电子": [
        {"type": "供需", "name": "芯片短缺/过剩", "timing": "季度财报", "pre_effect": "提前1月反应", "post_effect": "持续趋势"},
        {"type": "新品", "name": "苹果/华为发布会", "timing": "固定周期", "pre_effect": "提前2周", "post_effect": "见光死或超预期"},
    ],
    "医药生物": [
        {"type": "政策", "name": "集采/医保谈判", "timing": "固定时间", "pre_effect": "提前恐慌", "post_effect": "靴子落地反弹"},
        {"type": "业绩", "name": "新药审批/临床", "timing": "不定期", "pre_effect": "持续预期", "post_effect": "成功大涨失败暴跌"},
    ],
    "电力": [
        {"type": "政策", "name": "电价改革/新能源", "timing": "政策窗口", "pre_effect": "提前1周", "post_effect": "龙头持续"},
        {"type": "季节", "name": "夏季用电高峰", "timing": "每年6-8月", "pre_effect": "提前1月", "post_effect": "高峰兑现"},
    ],
    "有色金属": [
        {"type": "价格", "name": "大宗商品涨价", "timing": "实时", "pre_effect": "同步反应", "post_effect": "趋势延续"},
        {"type": "政策", "name": "供给侧改革", "timing": "政策窗口", "pre_effect": "提前预期", "post_effect": "龙头受益"},
    ],
}


def analyze_events(code: str, name: str, industry: str = "") -> dict:
    """个股事件驱动分析"""
    events = []

    # 根据行业匹配潜在事件
    templates = EVENT_TEMPLATES.get(industry, [])
    for t in templates:
        events.append({
            "event_type": t["type"],
            "event_name": t["name"],
            "typical_timing": t["timing"],
            "pre_rally": t["pre_effect"],
            "post_reaction": t["post_effect"],
            "strategy": f"提前{t['pre_effect'].replace('提前','').replace('反应','').replace('异动','')}布局，公告后视情况兑现",
        })

    # 通用事件（所有股票）
    events.extend([
        {"event_type": "业绩", "event_name": "季报/年报", "typical_timing": "1/4/7/10月",
         "pre_rally": "业绩预增提前2周", "post_reaction": "超预期高开低走，低预期低开高走",
         "strategy": "预增公告前潜伏，正式公告后1-2天兑现"},
        {"event_type": "分红", "event_name": "分红送转", "typical_timing": "年报后",
         "pre_rally": "预案前1周", "post_reaction": "除权后填权或贴权",
         "strategy": "高股息提前布局，高送转警惕见光死"},
    ])

    # 当前阶段判断
    try:
        from layer3_analysis.technical import compute
        from layer3_analysis.trend import compute_all as trend_compute
        tech = compute(code)
        tr = trend_compute(code, 60)

        price = tech.get("price", 0)
        vol_ratio = tech.get("vol_ratio", 1)
        trend = tr.get("trend_total", 5)

        # 判断是否在事件炒作期
        if vol_ratio > 1.5 and trend > 6:
            stage = "事件发酵期"
            advice = "可能已有资金提前布局，追高需谨慎，等待回调或确认"
        elif vol_ratio > 2 and trend > 7:
            stage = "事件高潮期"
            advice = "情绪亢奋，利好即将兑现，考虑减仓而非追涨"
        elif vol_ratio < 0.8 and trend < 4:
            stage = "事件真空期"
            advice = "无人问津，适合左侧潜伏等待催化"
        else:
            stage = "正常波动"
            advice = "无明显事件驱动迹象，按基本面操作"
    except:
        stage = "未知"
        advice = "数据不足"

    return {
        "code": code, "name": name, "industry": industry,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "potential_events": events,
        "current_stage": stage,
        "stage_advice": advice,
    }


def batch_event_analysis() -> dict:
    """全持仓事件分析"""
    results = {}
    for s in config.stocks:
        try:
            results[s["code"]] = analyze_events(s["code"], s["name"], s.get("industry", ""))
        except Exception as e:
            results[s["code"]] = {"error": str(e), "name": s["name"]}

    f = os.path.join(EVENT_DIR, f"event_{datetime.now().strftime('%Y%m%d')}.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)

    return {"date": datetime.now().strftime("%Y-%m-%d"), "results": results}
