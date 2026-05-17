"""
L3 分析引擎 — 全量评分（薄封装，委托 technical.score_all）
"""
from .technical import score_all as _score_all

def score_all_stocks() -> dict:
    return _score_all()

