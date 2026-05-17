"""
Telegram 推送模块
================
向 Telegram 发送分析报告和预警。
"""
import requests
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import config
from core.logging import get_logger

logger = get_logger("telegram")


def _get_credentials():
    token = config.get("notifications", "telegram", "bot_token", default="")
    chat_id = config.get("notifications", "telegram", "chat_id", default="")
    return token, chat_id


def send_message(text: str) -> bool:
    """发送 Telegram 消息"""
    if not config.get("notifications", "telegram", "enabled", default=True):
        logger.info("Telegram 未启用")
        return False

    token, chat_id = _get_credentials()
    if not token or not chat_id:
        logger.warning("Telegram 配置不完整")
        return False

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram 推送失败: {e}")
        return False


def send_stop_alert(alert: dict) -> bool:
    """推送止损预警"""
    emoji = "🚨" if alert.get("severity") == "CRITICAL" else "⚠️"
    text = f"""{emoji} <b>止损监控</b>

股票: {alert['name']} ({alert['code']})
现价: {alert['price']}
止损线: {alert['stop']}
浮亏: {alert['pct_from_cost']}%

<i>系统自动推送</i>"""
    return send_message(text)


def send_daily_summary(report_text: str) -> bool:
    """推送每日总结"""
    # Telegram 限制 4096 字符
    text = report_text[:4000]
    return send_message(f"📊 <b>每日分析报告</b>\n\n{text}")
