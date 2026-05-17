"""统一配置 — 单次加载 + 环境变量解析"""
import os, yaml
from pathlib import Path

ROOT = Path(__file__).parent.parent
_cache = None

def _resolve(o):
    if isinstance(o, str) and o.startswith('${') and o.endswith('}'):
        return os.getenv(o[2:-1], '')
    if isinstance(o, dict):
        return {k: _resolve(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_resolve(i) for i in o]
    return o

def load():
    global _cache
    if _cache is None:
        with open(ROOT / 'config.yaml', encoding='utf-8') as f:
            _cache = _resolve(yaml.safe_load(f))
    return _cache

def get(*keys, default=None):
    v = load()
    for k in keys:
        if isinstance(v, dict):
            v = v.get(k)
        else:
            return default
    return v if v is not None else default

class Config:
    stocks = property(lambda self: get('portfolio', 'stocks', default=[]))
    db_path = property(lambda self: get('system', 'source_db', default=''))
    deepseek_key = property(lambda self:
        get('api_keys', 'deepseek_api_key')
        or get('api_keys', 'deepseek_api_key_fallback', default=''))
    deepseek_model = property(lambda self:
        get('deepseek', 'model', default='deepseek-chat'))
    tushare_token = property(lambda self:
        get('api_keys', 'tushare_token')
        or get('api_keys', 'tushare_token_fallback', default=''))
    weights = property(lambda self:
        get('strategy', 'factor_weights', default={}))
    signal_thresholds = property(lambda self:
        get('strategy', 'signal_thresholds', default={'buy': 7, 'watch': 5, 'hold': 3}))

    def get(self, *keys, default=None):
        return get(*keys, default=default)

config = Config()
