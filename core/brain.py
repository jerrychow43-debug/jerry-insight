import os
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

# 自动定位项目根目录下的 .env
base_dir = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=base_dir / ".env")

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL")
)

def ask_llm(messages, json_mode=False):
    response_format = {"type": "json_object"} if json_mode else None
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            response_format=response_format,
            temperature=0.3,
            timeout=15,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"大脑连接失败: {str(e)}"
