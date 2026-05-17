"""数据库自修复：统一 trade_date 为 YYYY-MM-DD、基础一致性检查"""
import re
from typing import Dict
from core.database import db
from core.logging import get_logger
logger = get_logger("dbfix")

DATE8 = re.compile(r"^\d{4}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$")
DATE10 = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize_trade_date(v: str) -> str | None:
    """统一到 YYYY-MM-DD（与 pipeline 写入格式一致）"""
    if v is None: return None
    s = str(v).strip()
    if DATE10.match(s):
        return s  # 已合规
    if DATE8.match(s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def fix_trade_date_formats(limit: int | None = None) -> Dict:
    """将 YYYYMMDD 格式迁移为 YYYY-MM-DD"""
    rows = db.query(
        "SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg "
        "FROM stock_daily WHERE trade_date NOT LIKE '%-%'"
    )
    if limit: rows = rows[:int(limit)]
    changed = skipped = errors = 0

    for r in rows:
        try:
            ts_code = r.get("ts_code")
            old = r.get("trade_date")
            new = normalize_trade_date(old)
            if not new or new == old: skipped += 1; continue
            db.execute(
                "INSERT OR REPLACE INTO stock_daily (ts_code, trade_date, open, high, low, close, vol, amount, pct_chg) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (ts_code, new, r.get("open"), r.get("high"), r.get("low"), r.get("close"), r.get("vol"), r.get("amount"), r.get("pct_chg")))
            db.execute("DELETE FROM stock_daily WHERE ts_code=? AND trade_date=?", (ts_code, old))
            changed += 1
        except Exception as e:
            errors += 1
            logger.error(f"trade_date 修复失败 {ts_code} {old}: {e}")

    return {"checked": len(rows), "changed": changed, "skipped": skipped, "errors": errors}


def summary() -> Dict:
    total = db.query_one("SELECT COUNT(*) AS c FROM stock_daily")
    bad = db.query_one("SELECT COUNT(*) AS c FROM stock_daily WHERE trade_date NOT LIKE '%-%'")
    return {"total_rows": (total or {}).get("c"), "non_iso_trade_dates": (bad or {}).get("c")}


def run(auto_fix: bool = True) -> Dict:
    before = summary()
    fixed = None
    if auto_fix and before.get("non_iso_trade_dates"):
        fixed = fix_trade_date_formats()
    after = summary()
    return {"before": before, "fixed": fixed, "after": after}
