import json
from openai import OpenAI

class AdvancedMemoryManager:
    def __init__(self, client: OpenAI, max_turns: int = 3):
        self.client = client
        self.max_turns = max_turns
        self.short_term_memory = []       # 原生内存窗口
        self.system_redline_summary = ""   # 脱水后的长效红线缓存区

    def add_message(self, role: str, content: str):
        self.short_term_memory.append({"role": role, "content": content})
        # 如果对话轮数（一问一答算2条）超标，自动触发流式压缩
        if len(self.short_term_memory) > (self.max_turns * 2):
            self._compress_and_flush()

    def _compress_and_flush(self):
        """流式脱水机制：提炼长效财务快照，清空原始历史"""
        to_compress = self.short_term_memory[:-2]
        self.short_term_memory = self.short_term_memory[-2:] # 只留最后1轮
        
        compress_prompt = f"""请分析以下用户的消费交互历史，并将其无损压缩成100字以内的‘核心用户消费偏好、当前财务红线、历史敏感雷点’快照。
        历史记录：{json.dumps(to_compress, ensure_ascii=False)}
        请直接输出提炼后的风控红线事实，严禁任何客套话。"""
        
        try:
            completion = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": compress_prompt}],
                temperature=0.1
            )
            compressed_fact = completion.choices[0].message.content.strip()
            if self.system_redline_summary:
                self.system_redline_summary += " ｜ " + compressed_fact
            else:
                self.system_redline_summary = compressed_fact
        except:
            pass

    def get_compiled_context(self) -> str:
        """获取压缩处理后的纯记忆文本，完美注入状态机"""
        context_str = ""
        if self.system_redline_summary:
            context_str += f"【前序会话脱水长期记忆】：\n{self.system_redline_summary}\n\n"
        
        context_str += "【近期临近会话上下文】:\n"
        for msg in self.short_term_memory:
            role_tag = "用户" if msg["role"] == "user" else "铁算盘"
            context_str += f"- {role_tag}: {msg['content']}\n"
        return context_str