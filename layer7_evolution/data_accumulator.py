"""数据累积器 — 积累本地数据便于后期分析

对接 investment.db 现有表：
- signal_history: 每日六因子+7维+审计信号归档
- analysis_tracker: 每日分析记录（存证+后期回溯验证）
- daily_forecast: 三层趋势预判记录（验证预测准确率）
- investment_thesis: 投资逻辑固化/到期提醒
- factor_backtest_data: 读取历史因子数据加速回测
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from core.database import db
from core.config import config
from core.logging import get_logger

logger = get_logger("data_accumulator")

def accumulate_signals(scores, audit_data, seven_dim):
    """写入 signal_history — 存档每日多维度信号"""
    today = datetime.now().strftime("%Y-%m-%d")
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    count = 0
    
    for code, s in scores.items():
        name = s.get("name", "")
        price = s.get("price") or s.get("technicals", {}).get("price", 0)
        signal = s.get("signal", "")
        total = s.get("total", 0)
        factors = s.get("factors", {})
        
        # 从审计和7维取补充数据
        aud = audit_data.get(code, {})
        sd = seven_dim.get(code, {})
        
        # 各维度分数拆解
        quant_score = total  # 六因子=量化分
        price_score = sd.get("dimensions", {}).get("趋势", 5)  # 7维中取趋势维度
        fund_score = aud.get("total", 5)  # T/B/F/R总分
        
        detail = {
            "六因子": {k: round(v,2) if isinstance(v, float) else v for k,v in factors.items()},
            "7维": sd.get("dimensions", {}),
            "审计": {"T": aud.get("T"), "B": aud.get("B"), "F": aud.get("F"), "R": aud.get("R")},
        }
        
        try:
            db.execute(
                "INSERT INTO signal_history (trade_date, ts_code, name, price, signal, composite, quant_score, price_score, fund_score, detail, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (today, code, name, price, signal, signal, quant_score, price_score, fund_score, json.dumps(detail, ensure_ascii=False), now_ts)
            )
            count += 1
        except Exception as e:
            logger.warning(f"signal_history写入失败 {code}: {e}")
    
    logger.info(f"signal_history 写入 {count} 条")
    return count

def accumulate_analysis(scores, audit_data, seven_dim):
    """写入 analysis_tracker — 分析存证+后期回溯验证"""
    today = datetime.now().strftime("%Y-%m-%d")
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    count = 0
    
    for code, s in scores.items():
        name = s.get("name", "")
        price = s.get("price") or s.get("technicals", {}).get("price", 0)
        signal = s.get("signal", "")
        aud = audit_data.get(code, {})
        sd = seven_dim.get(code, {})
        
        # 从配置取目标价/止损
        stock_cfg = next((st for st in config.stocks if st["code"] == code), {})
        target = stock_cfg.get("target", 0)
        stop = stock_cfg.get("stop", 0)
        
        # 方向
        if signal in ("BUY", "买入"):
            direction = "bullish"
        elif signal in ("AVOID", "回避"):
            direction = "bearish"
        else:
            direction = "neutral"
        
        # 关键假设和证伪
        try:
            from layer7_evolution.trading_discipline import falsification_analysis
            fa = falsification_analysis(code, name)
            counter_evidence = ", ".join(fa.get("all_signals", []))
            assumptions = fa.get("verdict", "")
        except:
            counter_evidence = ""
            assumptions = ""
        
        notes_data = {
            "六因子总分": s.get("total", 0),
            "7维总分": sd.get("total", 0),
            "T/B/F/R": aud.get("total", 0),
            "审计建议": aud.get("action", ""),
            "预期差": "",
        }
        
        try:
            db.execute(
                "INSERT INTO analysis_tracker (ts_code, name, analysis_date, price_at_analysis, target_price, stop_loss, direction, consensus_votes, self_confidence, key_assumptions, counter_evidence, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (code, name, today, price, target, stop, direction, 0, 0.7, assumptions, counter_evidence, json.dumps(notes_data, ensure_ascii=False), now_ts)
            )
            count += 1
        except Exception as e:
            logger.warning(f"analysis_tracker写入失败 {code}: {e}")
    
    logger.info(f"analysis_tracker 写入 {count} 条")
    return count

def accumulate_forecast(scores, seven_dim):
    """写入 daily_forecast — 三层趋势预判记录"""
    today = datetime.now().strftime("%Y-%m-%d")
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    count = 0
    
    for code, s in scores.items():
        name = s.get("name", "")
        price = s.get("price") or s.get("technicals", {}).get("price", 0)
        signal = s.get("signal", "")
        
        # 三层趋势信息
        try:
            from layer7_evolution.signal_filter import three_layer_validation
            tl = three_layer_validation(code)
            short = tl.get("short", {})
            mid = tl.get("mid", {})
            long = tl.get("long", {})
            direction_label = tl.get("direction", "")
            
            if "共振向上" in direction_label:
                predicted_direction = "上涨"
            elif "共振向下" in direction_label:
                predicted_direction = "下跌"
            else:
                predicted_direction = "震荡"
            
            confidence = 0.8 if tl.get("consistent") else 0.5
            
            # 预测区间
            predicted_low = price * 0.95
            predicted_high = price * 1.05
            if predicted_direction == "上涨":
                predicted_high = price * 1.08
            elif predicted_direction == "下跌":
                predicted_low = price * 0.92
            
            signals_detail = {
                "short": short, "mid": mid, "long": long,
                "direction": direction_label,
            }
            
            factor_breakdown = {
                "factors": s.get("factors", {}),
                "total": s.get("total", 0),
            }
        except:
            predicted_direction = "未知"
            confidence = 0.3
            predicted_low = price * 0.95
            predicted_high = price * 1.05
            signals_detail = {}
            factor_breakdown = {}
        
        try:
            db.execute(
                "INSERT INTO daily_forecast (ts_code, name, forecast_date, target_date, predicted_direction, predicted_low, predicted_high, confidence, signal_score, signals_detail, model_version, factor_breakdown) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (code, name, today, today, predicted_direction, round(predicted_low,2), round(predicted_high,2), round(confidence,2), s.get("total",0), json.dumps(signals_detail, ensure_ascii=False), "duobao_v2.5", json.dumps(factor_breakdown, ensure_ascii=False))
            )
            count += 1
        except Exception as e:
            logger.warning(f"daily_forecast写入失败 {code}: {e}")
    
    logger.info(f"daily_forecast 写入 {count} 条")
    return count

def verify_past_forecasts():
    """回溯校验过去的 daily_forecast — 用当前实际价格验证旧预测"""
    today = datetime.now().strftime("%Y-%m-%d")
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 取未验证的预测（3天以上前的）
    cutoff = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    unverified = db.query(
        "SELECT id, ts_code, forecast_date, predicted_direction, predicted_low, predicted_high FROM daily_forecast WHERE forecast_date <= ? AND verified_at IS NULL ORDER BY forecast_date DESC LIMIT 50",
        (cutoff,)
    )
    
    verified = 0
    for row in unverified:
        fid = row["id"]
        code = row["ts_code"]
        
        # 取验证日收盘价
        actual = db.query_one(
            "SELECT close FROM stock_daily WHERE ts_code=? AND trade_date>=? ORDER BY trade_date ASC LIMIT 1",
            (code, row["forecast_date"])
        )
        
        if actual:
            actual_close = actual["close"]
            actual_pct = (actual_close / row["predicted_high"] - 1) * 100 if row["predicted_high"] else 0
            
            direction_correct = (
                (row["predicted_direction"] == "上涨" and actual_pct > 0) or
                (row["predicted_direction"] == "下跌" and actual_pct < 0) or
                (row["predicted_direction"] == "震荡" and abs(actual_pct) < 3)
            )
            
            within_range = row["predicted_low"] <= actual_close <= row["predicted_high"]
            
            db.execute(
                "UPDATE daily_forecast SET actual_close=?, actual_pct=?, was_direction_correct=?, within_range=?, verified_at=? WHERE id=?",
                (actual_close, round(actual_pct, 2), 1 if direction_correct else 0, 1 if within_range else 0, now_ts, fid)
            )
            verified += 1
    
    if verified:
        logger.info(f"回溯校验 daily_forecast: {verified} 条")
    return verified

def read_factor_data(code, limit=60):
    """从 factor_backtest_data 读取历史因子数据（加速回测）"""
    rows = db.query(
        "SELECT trade_date,ma5,ma10,ma20,adx,rsi14,ret_20d,vol_ratio,close,fwd_1d,fwd_5d,fwd_20d FROM factor_backtest_data WHERE ts_code=? ORDER BY trade_date DESC LIMIT ?",
        (code, limit)
    )
    return rows

def update_investment_thesis(code, name, thesis_text, catalyst, invalidation, horizon):
    """写入/更新 investment_thesis"""
    now = datetime.now().strftime("%Y-%m-%d")
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    existing = db.query_one("SELECT ts_code FROM investment_thesis WHERE ts_code=?", (code,))
    
    if existing:
        db.execute(
            "UPDATE investment_thesis SET thesis=?, catalyst=?, assumptions=?, invalidation=?, horizon=?, last_review=?, updated_at=?, next_review=?, review_interval_days=? WHERE ts_code=?",
            (thesis_text, catalyst, "", invalidation, horizon, now, now_ts, (datetime.now()+timedelta(days=14)).strftime("%Y-%m-%d"), 14, code)
        )
    else:
        db.execute(
            "INSERT INTO investment_thesis (ts_code, name, thesis, catalyst, assumptions, invalidation, horizon, last_review, status, created_at, updated_at, next_review, review_interval_days) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (code, name, thesis_text, catalyst, "", invalidation, horizon, now, "active", now_ts, now_ts, (datetime.now()+timedelta(days=14)).strftime("%Y-%m-%d"), 14)
        )
    return True

def full_accumulate(scores, audit_data, seven_dim):
    """全量数据累积 — 每次 --final 运行时调用"""
    r = {}
    r["signals"] = accumulate_signals(scores, audit_data, seven_dim)
    r["analysis"] = accumulate_analysis(scores, audit_data, seven_dim)
    r["forecast"] = accumulate_forecast(scores, seven_dim)
    r["verified"] = verify_past_forecasts()
    return r
