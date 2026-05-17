"""统一日志"""
import logging, os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from .config import config

def get_logger(name="duobao"):
    logger = logging.getLogger(name)
    if logger.handlers: return logger
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler(); ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    logger.addHandler(ch)
    d = config.get("system", "log_dir", default="logs"); os.makedirs(d, exist_ok=True)
    fh = RotatingFileHandler(os.path.join(d, f"{name}_{datetime.now():%Y%m%d}.log"), 10*1024*1024, 30, encoding="utf-8")
    fh.setLevel(logging.DEBUG); fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(fh)
    return logger
