"""L1 数据采集层 — 腾讯行情API"""
import urllib.request, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import config
from core.logging import get_logger
logger = get_logger("tencent")

def get_quote(code: str) -> dict | None:
    """腾讯实时行情"""
    if code.startswith("sh") or code.startswith("sz"): mc = code
    else:
        m = "sh" if code.endswith("SH") else "sz"
        mc = f"{m}{code.replace('.SH','').replace('.SZ','')}"
    url = f"https://qt.gtimg.cn/q={mc}"
    to = config.get("data_sources", "tencent", "timeout", default=10)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=to) as r: t = r.read().decode("gbk", errors="ignore")
        if "~" not in t: return None
        p = t.split("~")
        if len(p) < 40: return None
        return {"name": p[1], "price": float(p[3] or 0), "prev_close": float(p[4] or 0),
                "open": float(p[5] or 0), "high": float(p[33] or 0), "low": float(p[34] or 0),
                "volume": float(p[6] or 0), "amount": float(p[37] or 0),
                "pct_chg": float(p[32] or 0), "pe": float(p[39] or 0)}
    except: return None

def get_all_quotes() -> dict:
    r = {}
    for s in config.stocks:
        q = get_quote(s["code"])
        r[s["code"]] = {**s, **(q or {}), "error": None if q else "获取失败"}
    return r

def get_indices() -> dict:
    idx = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指", "sh000688": "科创50"}
    r = {}
    for c, n in idx.items():
        q = get_quote(c)
        if q: r[n] = q
    return r
