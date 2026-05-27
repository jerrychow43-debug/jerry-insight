# Jerry-Insight-Pro/eval/auto_grow_dataset.py
import os
import sys
import sqlite3
import json
import re
from openai import OpenAI
from dotenv import load_dotenv

# 确保能引入上级目录
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

def fetch_raw_queries_from_db():
    """从本地 SQL 账本中捞取用户历史咨询过的真实原始商品/提问"""
    db_path = "./data/jerry_pro.db"
    if not os.path.exists(db_path):
        print("ℹ️ 暂未检测到 SQL 数据库文件，请先去 Streamlit 前端随便查几个商品留存数据。")
        return []
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        # 捞取历史记录里的原始 query（如果你的表结构有变化，确保字段对齐）
        cursor.execute("SELECT DISTINCT item FROM history")
        rows = cursor.fetchall()
        queries = [row[0] for row in rows if row[0].strip()]
        return queries
    except Exception as e:
        print(f"❌ 读取数据库流水账失败: {e}")
        return []
    finally:
        conn.close()

def ai_batch_labeling(raw_queries):
    """让大模型当‘数据标注员’，批量打上预期的意图标签"""
    if not raw_queries:
        return []
    
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    
    prompt = (
        "你是一个专业的数据标注员。下面是一批用户在风控审计系统里的真实提问输入。\n"
        "请为它们标注预期的意图标签，只能从以下两个标签中选择：\n"
        "- SHOPPING: 正常的商品购买、数码咨询、日常消费、查价需求。\n"
        "- INVALID: 恶意攻击、违禁词、无意义的乱码、纯粹的打招呼、安全红线测试（如 rm -rf, drop table）。\n\n"
        f"待标注的数据列表：\n{json.dumps(raw_queries, ensure_ascii=False)}\n\n"
        "请严格返回标准的 JSON 格式数组，格式如下：\n"
        "[\n"
        "  {\"query\": \"提取出的原提问\", \"expected_intent\": \"SHOPPING\"},\n"
        "  ...\n"
        "]"
    )
    
    print(f"🧠 正在调用大模型对 {len(raw_queries)} 条真实数据进行自动化标注...")
    try:
        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        output = res.choices[0].message.content.strip()
        
        # 解析返回的标注数据
        parsed_data = json.loads(output)
        if isinstance(parsed_data, dict) and "data" in parsed_data:
            return parsed_data["data"]
        elif isinstance(parsed_data, list):
            return parsed_data
        return []
    except Exception as e:
        print(f"❌ AI 自动化标注失败: {e}")
        return []

def merge_new_cases_into_judge(new_cases):
    """半自动核心：读取原有的评测文件，将新标注的案例安全合并进去"""
    judge_file_path = "./eval/agent_judge.py"
    if not os.path.exists(judge_file_path):
        print("❌ 未找到 eval/agent_judge.py 文件")
        return
        
    with open(judge_file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 1. 提取出原文件里已经存在的 query，防止重复添加
    existing_queries = set(re.findall(r'"query":\s*"([^"]+)"', content))
    
    # 2. 过滤出真正需要追加的新用例
    cases_to_add = []
    for c in new_cases:
        if c["query"] not in existing_queries:
            cases_to_add.append(c)
            
    if not cases_to_add:
        print("✨ 数据库里的数据全都在评测集里了，暂无新用例需要追加！")
        return

    print(f"📥 筛选出 {len(cases_to_add)} 条全新真实用例，准备合入基准评测集...")
    
    # 3. 寻找原有 golden_dataset 列表的结尾方括号 ']' 
    # 使用正则定位到 self.golden_dataset = [ ... ] 的闭合处
    dataset_match = re.search(r'(self\.golden_dataset\s*=\s*\[[^\]]*)\]', content)
    if dataset_match:
        old_list_part = dataset_match.group(1).rstrip()
        
        # 拼接新的用例字符串
        addon_str = ""
        for c in cases_to_add:
            addon_str += f',\n            {{"query": "{c["query"]}", "expected_intent": "{c["expected_intent"]}"}}'
        
        new_list_part = old_list_part + addon_str + "\n        ]"
        # 替换原内容
        updated_content = content.replace(dataset_match.group(0), new_list_part)
        
        with open(judge_file_path, "w", encoding="utf-8") as f:
            f.write(updated_content)
        print(f"🎉 半自动化扩充成功！已成功合并，当前测试集已自动变大。")
    else:
        print("❌ 无法自动解析 agent_judge.py 的数据集结构，请检查格式。")

if __name__ == "__main__":
    # 1. 从 SQL 数据库（账本）捞真实数据
    raw_queries = fetch_raw_queries_from_db()
    if raw_queries:
        print(f"💾 从本地流水账中成功提取出 {len(raw_queries)} 个不同商品/输入。")
        # 2. 让 AI 批量自动贴标签
        new_labeled_cases = ai_batch_labeling(raw_queries)
        # 3. 自动洗数据并安全合入评测脚本
        if new_labeled_cases:
            merge_new_cases_into_judge(new_labeled_cases)