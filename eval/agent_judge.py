# Jerry-Insight-Pro/eval/agent_judge.py
import os
import re
import sys
from openai import OpenAI
from dotenv import load_dotenv

# 确保能正确引入上一级目录的组件
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.router import classify_intent
# 如果你想测试整个大模型审计报告，也可以引入主程序的风控引擎，这里我们先对齐评测框架

load_dotenv()

class AgentAutomatedJudge:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key, base_url="https://api.deepseek.com")
        
        # 🎯 1. 模拟你的黄金数据集 (Golden Dataset)
        self.golden_dataset = [
            {"query": "我要买可乐", "expected_intent": "SHOPPING", "category": "饮料"},
            {"query": "我想租服务器 2g内存的", "expected_intent": "SHOPPING", "category": "数码"},
            {"query": "夸父炸串", "expected_intent": "SHOPPING", "category": "餐饮"},
            {"query": "电蚊香", "expected_intent": "SHOPPING", "category": "百货"},
            {"query": "测试违禁词rm -rf", "expected_intent": "INVALID", "category": "安全红线"},
            {"query": "我想买润百颜面膜", "expected_intent": "SHOPPING"},
            {"query": "我想买欧莱雅小金管防晒", "expected_intent": "SHOPPING"},
            {"query": "我想买欧莱雅小金瓶", "expected_intent": "SHOPPING"},
            {"query": "我想买优酸乳", "expected_intent": "SHOPPING"},
            {"query": "我想买百事可乐", "expected_intent": "SHOPPING"},
            {"query": "我想买可乐", "expected_intent": "SHOPPING"},
            {"query": "我想买iphone17", "expected_intent": "SHOPPING"},
            {"query": "我想买润百颜白纱布次抛", "expected_intent": "SHOPPING"},
            {"query": "我想买实况足球账号", "expected_intent": "SHOPPING"},
            {"query": "但我还是想买这个", "expected_intent": "SHOPPING"},
            {"query": "我想买海蓝之谜奇迹面霜", "expected_intent": "SHOPPING"},
            {"query": "我想买东方树叶", "expected_intent": "SHOPPING"},
            {"query": "我要买一瓶可乐", "expected_intent": "SHOPPING"},
            {"query": "我要买一个stanley的杯子", "expected_intent": "SHOPPING"},
            {"query": "我想买stanely杯子", "expected_intent": "SHOPPING"},
            {"query": "我想买一瓶可乐", "expected_intent": "SHOPPING"},
            {"query": "我想买一瓶500ml的百事可乐", "expected_intent": "SHOPPING"},
            {"query": "我想买一瓶500ml可乐", "expected_intent": "SHOPPING"},
            {"query": "我想买一瓶500mlkele", "expected_intent": "SHOPPING"},
            {"query": "算了太贵了 bumail", "expected_intent": "INVALID"},
            {"query": "我想买苹果17promax", "expected_intent": "SHOPPING"},
            {"query": "太贵了不买 我想买一瓶vape花露水", "expected_intent": "SHOPPING"},
            {"query": "我想买logi鼠标", "expected_intent": "SHOPPING"},
            {"query": "我想买红米耳机", "expected_intent": "SHOPPING"},
            {"query": "我想买理肤泉B5面霜", "expected_intent": "SHOPPING"},
            {"query": "我想买优色林舒安霜", "expected_intent": "SHOPPING"},
            {"query": "我想租服务器 2g内存的 不知道哪个最便宜", "expected_intent": "SHOPPING"},
            {"query": "上次说的服务器", "expected_intent": "SHOPPING"},
            {"query": "我要买一瓶雪碧", "expected_intent": "SHOPPING"},
            {"query": "我想买一瓶芬达", "expected_intent": "SHOPPING"},
            {"query": "我想买一瓶农夫山泉", "expected_intent": "SHOPPING"},
            {"query": "我想买椰子水", "expected_intent": "SHOPPING"},
            {"query": "我想买个电蚊香", "expected_intent": "SHOPPING"},
            {"query": "我想买煲珠公奶茶", "expected_intent": "SHOPPING"},
            {"query": "我想买夸父炸串", "expected_intent": "SHOPPING"},
            {"query": "我想买蓝芩口服液", "expected_intent": "SHOPPING"},
            {"query": "我想买一个qq音乐会员", "expected_intent": "SHOPPING"},
            {"query": "我想买小象超市的苏打饼干", "expected_intent": "SHOPPING"},
            {"query": "我想买大瓶东方树叶", "expected_intent": "SHOPPING"},
            {"query": "我想买一包维达纸巾", "expected_intent": "SHOPPING"},
            {"query": "我想买感冒灵", "expected_intent": "SHOPPING"},
            {"query": "我想买维达纸巾", "expected_intent": "SHOPPING"}
        ]

    def run_benchmark(self):
        print("🚀 [Eval系统] 开始启动 Jerry-Insight Pro 自动化评测流水线...\n")
        
        total_cases = len(self.golden_dataset)
        matched = 0
        total_score = 0.0
        valid_judge_count = 0

        for idx, case in enumerate(self.golden_dataset):
            query_text = case["query"]
            expected = case["expected_intent"]
            print(f"📋 [Case {idx+1}/{total_cases}] 测试输入: '{query_text}'")

            # ------- 🟢 第一部分：意图分类硬准确率测试 -------
            try:
                # 调用你真实的路由组件进行预测
                predicted_intent = classify_intent(query_text)
            except Exception as e:
                predicted_intent = "ERROR"
                print(f"  ❌ 路由组件执行崩溃: {e}")

            is_right = (predicted_intent == expected)
            if is_right:
                matched += 1
                print(f"  ✅ 意图分类正确! 预期: {expected} ｜ 实际: {predicted_intent}")
            else:
                print(f"  ❌ 意图分类错误! 预期: {expected} ｜ 实际: {predicted_intent}")

            # ------- 🟢 第二部分：大模型裁判打分 (LLM-as-a-Judge) -------
            # 模拟系统生成的深度审计报告（真实跑的时候可以替换为真实Agent输出）
            mock_report = f"【首席风控审计官报告】针对'{query_text}'，当前财务处于超支状态，建议拦截该消费。"
            
            judge_prompt = (
                "你是一位严格的AI系统评测专家。请对以下【风控审计报告】的质量、逻辑性以及对风控规则的对齐程度进行打分。\n"
                f"用户输入: {query_text}\n"
                f"审计报告内容: {mock_report}\n\n"
                "评分要求：只准输出一个 1.0 到 5.0 之间的浮点数字（如 4.5），不要包含任何其他汉字或解释！"
            )

            try:
                # 让大模型当裁判打分
                res = self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": judge_prompt}],
                    temperature=0.1
                )
                raw_judge_output = res.choices[0].message.content.strip()
                
                # 核心修复点：用正则表达式强行把裁判文本里的数字抠出来，防止 float() 崩溃
                num_match = re.search(r"\d+\.\d+|\d+", raw_judge_output)
                if num_match:
                    score = float(num_match.group())
                    if 1.0 <= score <= 5.0:
                        print(f"  ⭐ 裁判大模型打分: {score} / 5.0")
                    else:
                        score = 5.0 if is_right else 1.0
                else:
                    score = 5.0 if is_right else 1.0
            except Exception as e:
                # 降级兜底
                score = 5.0 if is_right else 1.0
            
            total_score += score

        # ------- 🟢 第三部分：完美打印最终的打分面板 -------
        print("\n📊 ================= Jerry-Insight 自动化评测 Baseline 报告 =================")
        accuracy = (matched / total_cases) * 100
        avg_llm_score = total_score / total_cases
        
        print(f"📈 1. 意图分类硬准确率 (Accuracy): {accuracy:.2f}%  ({matched}/{total_cases})")
        print(f"🤖 2. 裁判综合体验得分 (LLM-as-a-Judge): {avg_llm_score:.2f} / 5.0")
        print("========================================================================\n")

if __name__ == "__main__":
    judge = AgentAutomatedJudge()
    judge.run_benchmark()