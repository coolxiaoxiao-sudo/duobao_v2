"""DeepSeek AI 引擎"""
import json, requests, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import config
from core.logging import get_logger
logger = get_logger("deepseek")

class Engine:
    def __init__(self):
        self.key = config.deepseek_key
        self.base = config.get("deepseek", "base_url", default="https://api.deepseek.com/v1")
        self.model = config.get("deepseek", "model", default="deepseek-chat")
        self.reasoner = config.get("deepseek", "model_reasoner", default="deepseek-reasoner")
        self.tokens = config.get("deepseek", "max_tokens", default=4096)
        self.temp = config.get("deepseek", "temperature", default=0.3)

    def chat(self, msgs, model=None, temp=None):
        if not self.key: return "[SKIP] DeepSeek Key未配置"
        try:
            r = requests.post(f"{self.base}/chat/completions",
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                json={"model": model or self.model, "messages": msgs, "max_tokens": self.tokens,
                      "temperature": temp or self.temp}, timeout=60)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"DeepSeek API失败: {e}")
            return f"[ERROR] {e}"

    def analyze_stock(self, name, code, ctx):
        return self.chat([
            {"role": "system", "content": "你是专业A股量化分析师。数据驱动，给出明确多空判断+置信度+风险提示。"},
            {"role": "user", "content": f"## {name}({code})\n### 行情: {json.dumps(ctx.get('quote',{}), ensure_ascii=False)}\n### 六因子: {json.dumps(ctx.get('factors',{}), ensure_ascii=False)}\n### 成本: {ctx.get('cost')} 止盈: {ctx.get('target')} 止损: {ctx.get('stop')}\n请给出: 1.多空判断 2.置信度(0-1) 3.关键风险 4.操作建议"}
        ])

    def market_review(self, ctx):
        return self.chat([
            {"role": "system", "content": "专业A股市场分析师。"},
            {"role": "user", "content": f"请复盘今日A股:\n### 大盘: {json.dumps(ctx.get('indices',{}), ensure_ascii=False)}\n### 持仓评分: {json.dumps(ctx.get('scores',{}), ensure_ascii=False)}\n请给出: 1.市场总结 2.板块方向 3.风险提示 4.明日关注"}
        ])

    def reason(self, question, ctx=None):
        content = question
        if ctx: content = f"{question}\n\n### 数据\n{json.dumps(ctx, ensure_ascii=False)}"
        return self.chat([{"role": "user", "content": content}], model=self.reasoner, temp=0.1)

deepseek = Engine()
