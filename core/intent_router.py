import numpy as np
import os
import chromadb
from openai import OpenAI

class TwoStageIntentRouter:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", threshold: float = 0.75):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.threshold = threshold
        # 🎯 匹配你原本系统的核心业务意图
        self.intent_templates = {
            "audit_task": ["帮我看看这个价格便宜吗", "全网比价", "排雷审计", "这个值得买吗", "帮我查一下最低价"],
            "INVALID": ["天气预报", "你是谁", "写段Java代码", "讲个笑话"]
        }
        self.template_embeddings = {}
        self._initialize_embeddings()

    def _get_embedding(self, text: str) -> list:
        try:
            response = self.client.embeddings.create(
                input=[text], model="text-embedding-3-small"
            )
            return response.data[0].embedding
        except:
            # 降级防御
            return [0.0] * 1536

    def _initialize_embeddings(self):
        """本地初始化高频意图的语义空间质心，实现 0 毫秒本地拦截分流"""
        for intent, texts in self.intent_templates.items():
            embeddings = [self._get_embedding(t) for t in texts]
            if embeddings and not all(all(v == 0.0 for v in emb) for emb in embeddings):
                self.template_embeddings[intent] = np.mean(embeddings, axis=0)

    def route(self, user_query: str) -> tuple[str, float]:
        """第一阶段本地向量快速匹配 -> 第二阶段 LLM 兜底消解"""
        if not self.template_embeddings:
            return "audit_task", 1.0
            
        query_emb = np.array(self._get_embedding(user_query))
        if all(v == 0.0 for v in query_emb):
            return "audit_task", 1.0

        best_intent = "unknown"
        max_sim = -1.0

        # 【第一阶段】本地余弦相似度计算
        for intent, target_emb in self.template_embeddings.items():
            sim = np.dot(query_emb, target_emb) / (np.linalg.norm(query_emb) * np.linalg.norm(target_emb))
            if sim > max_sim:
                max_sim = sim
                best_intent = intent

        if max_sim >= self.threshold:
            return best_intent, max_sim

        # 【第二阶段】长尾模糊意图，降级流式触发大模型
        fallback_prompt = f"""你是一个高精度的意图识别路由网关。请审阅用户的模糊请求并归类：
        - 'audit_task': 询问商品购买决策、商品排雷、查价格、消费审计。
        - 'INVALID': 闲聊、恶意灌水、非消费审计相关的无效请求。
        
        用户请求: "{user_query}"
        请严格仅返回标签字符串（如 audit_task），不要包含任何解释或标点。"""
        
        try:
            completion = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": fallback_prompt}],
                temperature=0.0
            )
            return completion.choices[0].message.content.strip(), 1.0
        except:
            return "audit_task", 1.0 # 熔断降级：默认放行进入审计流