"""L1 数据采集层 — TuShare 日线接口（用于补齐历史K线）"""
import os
import sys
import datetime as dt
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import config
from core.logging import get_logger

logger = get_logger("tushare")

TS_API = "http://api.tushare.pro"


def _token() -> str:
    # 优先环境变量/主token，其次 fallback
    return config.tushare_token


def pro_query(api_name: str, params: dict, fields: str) -> list[dict]:
    tok = _token()
    if not tok:
        raise RuntimeError("TuShare token 未配置")

    payload = {"api_name": api_name, "token": tok, "params": params, "fields": fields}
    r = requests.post(TS_API, json=payload, timeout=20)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError(f"TuShare error: {j}")

    data = j.get("data") or {}
    flds = data.get("fields") or []
    items = data.get("items") or []
    out = [dict(zip(flds, it)) for it in items]
    return out


def fetch_daily(ts_code: str, start_date: str, end_date: str) -> list[dict]:
    """拉取日线（trade_date 为 YYYYMMDD）。"""
    fields = "ts_code,trade_date,open,high,low,close,vol,amount,pct_chg"
    rows = pro_query("daily", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}, fields)
    return rows


def fetch_last_n_trading_days(ts_code: str, n: int = 60) -> list[dict]:
    """补齐最近 n 个交易日（粗略用 220 个自然日窗口覆盖）。"""
    end = dt.date.today()
    start = end - dt.timedelta(days=220)
    rows = fetch_daily(ts_code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    # TuShare 默认按 trade_date 倒序返回
    rows = list(reversed(rows))
    if len(rows) > n:
        rows = rows[-n:]
    return rows
