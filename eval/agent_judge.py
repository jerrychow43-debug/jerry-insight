import os
import sys
# 修正路径引入 core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from openai import OpenAI
from core.intent_router import TwoStageIntentRouter

class AgentAutomatedJudge:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        # 💡 人工标注的生产环境黄金真值基准测试集 (Golden Dataset)
        self.golden_dataset = [
            {"query": "我想入手一个大疆无人机，帮我看看有没有坑", "expected_intent": "audit_task"},
            {"query": "拼多多上的入耳式耳机很便宜，能买吗", "expected_intent": "audit_task"},
            {"query": "今天晚上的五子棋比赛规则是什么", "expected_intent": "INVALID"},
            {"query": "帮我写一段Python连接数据库的代码", "expected_intent": "INVALID"}
        ]

    def run_benchmark(self):
        print("🚀 [LLM-as-a-Judge] 正在自动化跑分评测系统性能...")
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        router = TwoStageIntentRouter(api_key=api_key)
        
        total_cases = len(self.golden_dataset)
        matched = 0
        total_score = 0.0

        for case in self.golden_dataset:
            actual_intent, confidence = router.route(case["query"])
            is_right = (actual_intent == case["expected_intent"])
            if is_right:
                matched += 1

            # 裁判模型现场打分
            judge_prompt = f"""你是一个严厉的Agent评测官。
            输入句: "{case['query']}"
            系统分类: "{actual_intent}"
            预期真值: "{case['expected_intent']}"
            若分类完全正确给5分，完全错误给1分。请严格仅返回一个纯数字得分（如 5）。"""
            
            try:
                res = self.client.chat.completions.create(
                    model="deepseek-chat", messages=[{"role": "user", "content": judge_prompt}], temperature=0.0
                )
                score = float(res.choices[0].message.content.strip())
            except:
                score = 5.0 if is_right else 1.0
            total_score += score

        print("\n📊 ===== Jerry-Insight 自动化评测 Baseline 报告 =====")
        print(f"1. 意图分类硬准确率 (Accuracy): {(matched / total_cases)*100:.2f}%")
        print(f"2. 裁判综合体验得分 (LLM-as-a-Judge): {total_score / total_cases:.2f} / 5.0")
        print("====================================================\n")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    judge = AgentAutomatedJudge(api_key=os.getenv("DEEPSEEK_API_KEY"))
    judge.run_benchmark()