"""自检：配置/依赖/数据源/DeepSeek/输出链路/看板端口"""
from __future__ import annotations

import json
import os
import socket
import sys
from datetime import datetime


def _ok(msg):
    return {"ok": True, "msg": msg}


def _bad(msg):
    return {"ok": False, "msg": msg}


def _try(fn):
    try:
        return fn()
    except Exception as e:
        return _bad(f"{type(e).__name__}: {e}")


def check_imports():
    missing = []
    for m in ("yaml", "requests", "numpy", "flask"):
        try:
            __import__(m)
        except Exception:
            missing.append(m)
    return _ok("依赖齐全") if not missing else _bad(f"缺少依赖: {missing}")


def check_config():
    import yaml

    cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    with open(cfg_path, encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}

    required = [
        ("system", "source_db"),
        ("deepseek", "base_url"),
        ("api_keys", "deepseek_api_key_fallback"),
        ("portfolio", "stocks"),
    ]

    for a, b in required:
        if a not in d or b not in (d.get(a) or {}):
            return _bad(f"config.yaml 缺字段: {a}.{b}")

    n = len((d.get("portfolio") or {}).get("stocks") or [])
    if n <= 0:
        return _bad("portfolio.stocks 为空")

    return _ok(f"config.yaml 正常（stocks={n}）")


def check_db():
    from core.config import config
    from core.database import db

    p = config.db_path
    if not p or not os.path.exists(p):
        return _bad(f"数据库不存在: {p}")

    row = db.query_one("SELECT COUNT(*) AS cnt FROM stock_daily")
    cnt = row.get("cnt") if isinstance(row, dict) else None
    return _ok(f"stock_daily 行数: {cnt}")


def check_tencent():
    from layer1_data.tencent_api import get_quote

    q = get_quote("301316.SZ")
    if not q or not q.get("price"):
        return _bad("腾讯行情获取失败")
    return _ok(f"腾讯行情 OK：慧博云通 现价 {q.get('price')}")


def check_deepseek():
    from core.config import config
    from ai.deepseek import deepseek

    if not config.deepseek_key:
        return _bad("DeepSeek Key 未配置")

    r = deepseek.chat(
        [
            {"role": "system", "content": "只回复OK"},
            {"role": "user", "content": "ping"},
        ],
        temp=0,
    )
    if isinstance(r, str) and r.startswith("[ERROR]"):
        return _bad(r)
    return _ok("DeepSeek 连通 OK")


def check_outputs():
    base = os.path.dirname(os.path.dirname(__file__))
    latest = os.path.join(base, "data", "latest_report.md")
    ok_latest = os.path.exists(latest)
    return _ok("latest_report.md 存在" if ok_latest else "latest_report.md 不存在（先运行一次 python .\\main.py 生成）")


def check_dashboard_port():
    host, port = "127.0.0.1", 8088
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        r = s.connect_ex((host, port))
        if r == 0:
            return _ok("看板端口 8088 已在监听")
        return _ok("看板端口 8088 未启动（正常；启动用 python .\\main.py --dashboard）")
    finally:
        s.close()


def run(print_json: bool = False, quiet: bool = False) -> dict:
    checks = {
        "python": _ok(f"{sys.version.split()[0]} @ {sys.executable}"),
        "imports": check_imports(),
        "config": _try(check_config),
        "db": _try(check_db),
        "tencent": _try(check_tencent),
        "deepseek": _try(check_deepseek),
        "outputs": _try(check_outputs),
        "dashboard": _try(check_dashboard_port),
    }

    ok_all = all(v.get("ok") for v in checks.values())
    result = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ok": ok_all,
        "checks": checks,
    }

    if print_json:
        if not quiet:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    if not quiet:
        print("\n=== 多宝 v2 自检报告 ===")
        print(f"时间: {result['time']}")
        print(f"总体: {'OK' if ok_all else 'FAIL'}")
        for k, v in checks.items():
            flag = "✅" if v.get("ok") else "❌"
            print(f"{flag} {k}: {v.get('msg')}")
        print("========================\n")

    return result
