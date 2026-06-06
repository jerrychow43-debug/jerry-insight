import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path

try:
    from openai import OpenAI
except ModuleNotFoundError:
    OpenAI = None

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*args, **kwargs):
        return False


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db import find_memory_context, get_current_surplus

try:
    from core.router import classify_intent as original_classify_intent
    from core.router import clean_query_to_entity as original_clean_query_to_entity
except Exception as import_err:
    original_classify_intent = None
    original_clean_query_to_entity = None
    print(f"原版 router 暂不可用，已启用降级路由: {import_err}")


load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()

WEB_SEARCH_TIMEOUT_SECONDS = int(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "25"))
TRACE_FILE = Path(__file__).resolve().parent / "fullstack_trace_logs.jsonl"
EXECUTOR = ThreadPoolExecutor(max_workers=8)


def new_trace(query_text):
    return {
        "trace_id": f"trace_{int(time.time() * 1000)}",
        "query": query_text,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "stages": [],
        "status": "running",
        "errors": [],
    }


def trace_stage(trace, name, started_at, status="ok", **extra):
    if not trace:
        return
    item = {
        "name": name,
        "status": status,
        "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
    }
    item.update(extra)
    trace["stages"].append(item)


def save_trace_log(trace):
    if not trace:
        return
    try:
        with TRACE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(trace, ensure_ascii=False) + "\n")
    except Exception as err:
        print(f"Trace 保存失败: {err}")


def fallback_extract_item(query):
    text = query.strip()
    stop_phrases = [
        "我想买",
        "想买",
        "帮我看看",
        "帮我看下",
        "看看",
        "这个",
        "值不值得买",
        "值不值得入手",
        "多少钱",
        "多少价",
        "有没有必要",
        "推荐一下",
        "买",
    ]
    for phrase in stop_phrases:
        text = text.replace(phrase, "")
    text = re.sub(r"[，。！？,.!?、\s]+", "", text)
    return text[:30] or query.strip()[:30] or "未知商品"


def normalize_entity(query, trace):
    stage_started = time.perf_counter()
    try:
        if original_clean_query_to_entity is None:
            entity = "NONE"
        else:
            entity = original_clean_query_to_entity(query)
    except Exception as err:
        trace["errors"].append({"stage": "entity_extract", "error": str(err)})
        entity = "NONE"

    if not entity or entity.upper() == "NONE":
        entity = fallback_extract_item(query)
        trace_stage(trace, "entity_extract", stage_started, status="fallback", entity=entity)
    else:
        trace_stage(trace, "entity_extract", stage_started, entity=entity)
    return entity


def get_memory_context(query, limit=5):
    hits = find_memory_context(query, limit=limit)
    if not hits:
        return "暂无相关历史消费或对话记忆。", []
    lines = []
    for row in hits:
        lines.append(f"- {row.get('text', '')} | {row.get('extra', '')} | score={row.get('score', 0)}")
    return "\n".join(lines), hits


def compact_price_context(crawler_results):
    if not crawler_results:
        return ""
    return "\n".join(row.get("price_info", "") for row in crawler_results if row.get("price_info"))


class OriginalAgentHarness:
    def __init__(self, max_steps=4):
        self.max_steps = max_steps
        self.client = None
        if OpenAI is not None and os.getenv("DEEPSEEK_API_KEY"):
            self.client = OpenAI(
                api_key=os.getenv("DEEPSEEK_API_KEY", ""),
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            )
        self.model = "deepseek-chat"

    def run_harness(self, item_name, raw_info_text, profile_data, long_term_context, memory_ctx, chat_history=None):
        if self.client is None:
            return self._offline_answer(item_name, raw_info_text)

        short_term_history = ""
        for msg in (chat_history or [])[-6:]:
            short_term_history += f"-> {msg.get('role', '').upper()}: {msg.get('content', '')}\n"

        system_instruction = f"""
你是 Jerry 财务智能体系统里的消费审计官。
本次审计对象是：{item_name}

你必须围绕“用户是否值得买、合理单价是多少、是否会影响预算”回答。
如果商品是可乐、雪碧、东方树叶、饮料、矿泉水、零食等单体快消品，默认数量是 1 瓶/1 件，必须折算成单件单价，不要把整箱价格当成单件价格。

你只能输出 JSON，格式二选一：
1. 需要继续搜索：
{{"action":"Call_Web_Search","action_input":"搜索关键词"}}
2. 情报足够，给最终报告：
{{"action":"Final Answer","action_input":"【建议购买/建议避坑/持币观望】\\n\\n【深度审计理由】：...\\n\\nPRICE_DATA: {{\\"item\\": \\"{item_name}\\", \\"estimated_price\\": 3.50}}"}}
"""
        user_context = f"""
【短期多轮会话】
{short_term_history or "暂无。"}

【历史档案】
{long_term_context}

【治理缓存】
{memory_ctx}

【财务画像】
- 当前剩余资金: {profile_data["current_surplus"]} 元

【初始情报】
{raw_info_text[:1800]}
"""
        conversation = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_context},
        ]

        raw_output = ""
        for step in range(self.max_steps):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=conversation,
                    temperature=0.3,
                )
                raw_output = response.choices[0].message.content.strip()
                parsed_json = self._parse_json(raw_output)

                if parsed_json.get("action") == "Final Answer":
                    return parsed_json.get("action_input", raw_output)

                if parsed_json.get("action") == "Call_Web_Search":
                    search_kw = parsed_json.get("action_input") or item_name
                    try:
                        future = EXECUTOR.submit(run_web_search, search_kw)
                        _, search_feedback, _ = future.result(timeout=WEB_SEARCH_TIMEOUT_SECONDS)
                    except FutureTimeoutError:
                        search_feedback = f"二次外部搜索超过 {WEB_SEARCH_TIMEOUT_SECONDS} 秒，请基于已有情报直接收敛。"
                    except Exception as err:
                        search_feedback = f"二次外部搜索异常：{err}。请基于已有情报直接收敛。"
                    conversation.append({"role": "assistant", "content": raw_output})
                    conversation.append({"role": "user", "content": f"【追查情报反馈】\n{search_feedback[:1200]}"})
            except Exception as err:
                print(f"Harness Step {step + 1} 异常: {err}")
                break

        return self._force_final(item_name, raw_output, conversation)

    def _parse_json(self, raw_output):
        text = raw_output.strip()
        if text.startswith("```json"):
            text = text.replace("```json", "", 1).rstrip("`").strip()
        elif text.startswith("```"):
            text = text.replace("```", "", 1).rstrip("`").strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(match.group(0) if match else text)

    def _force_final(self, item_name, raw_output, conversation):
        if "PRICE_DATA" in raw_output:
            return raw_output
        if self.client is not None:
            try:
                conversation.append({
                    "role": "user",
                    "content": "请立刻停止搜索，直接用 Final Answer JSON 输出最终审计报告，并附带 PRICE_DATA。",
                })
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=conversation,
                    temperature=0.2,
                )
                parsed_json = self._parse_json(response.choices[0].message.content.strip())
                if parsed_json.get("action") == "Final Answer":
                    return parsed_json.get("action_input", "")
            except Exception as err:
                print(f"强制收敛失败: {err}")
        return self._offline_answer(item_name, raw_output)

    def _offline_answer(self, item_name, raw_info_text):
        fallback_price = guess_price_from_text(item_name, raw_info_text)
        return (
            "【持币观望】\n\n"
            "【深度审计理由】：当前后端没有拿到可用的大模型配置或模型调用失败，因此先基于搜索与价格线索给出保守判断。"
            "建议你点开来源核实最新券后价，再决定是否购买。\n\n"
            f"PRICE_DATA: {{\"item\": \"{item_name}\", \"estimated_price\": {fallback_price}}}"
        )


def guess_price_from_text(item_name, text):
    is_beverage = is_beverage_item(item_name)
    if is_beverage:
        return 3.0

    nums = []
    for match in re.findall(r"(\d+(?:\.\d+)?)\s*(?:元|块|块钱|RMB|rmb)", text or ""):
        try:
            value = float(match)
            if 0 < value < 100000:
                nums.append(value)
        except ValueError:
            continue
    return round(nums[0], 2) if nums else 15.0


def run_web_search(item):
    try:
        from tools.search import web_search_pro

        return web_search_pro(item)
    except Exception as err:
        return (
            [],
            f"Web Search 暂不可用：{err}",
            [{"平台": "Web Search 降级", "参考报价/情报说明": "搜索工具导入或执行失败", "数据出处": ""}],
        )


def run_price_crawler(item):
    try:
        from tools.price_crawler import crawl_smzdm_price

        return crawl_smzdm_price(item)
    except Exception as err:
        print(f"价格爬虫暂不可用: {err}")
        return []


def is_beverage_item(item_name):
    lowered = (item_name or "").lower()
    return any(word in lowered for word in ["可乐", "cola", "饮料", "水", "雪碧", "芬达", "矿泉水", "东方树叶", "茶饮"])


def parse_price(raw_answer, item_name):
    detected_price = 0.0
    if "PRICE_DATA:" in raw_answer:
        try:
            price_part = raw_answer.rsplit("PRICE_DATA:", 1)[1].strip()
            price_match = re.search(r'"estimated_price"\s*:\s*([0-9.]+)', price_part)
            if price_match:
                detected_price = float(price_match.group(1))
            else:
                json_match = re.search(r"\{.*\}", price_part, re.DOTALL)
                detected_price = float(json.loads(json_match.group(0))["estimated_price"])
        except Exception as err:
            print(f"价格抽取未命中: {err}")

    if detected_price == 0.0:
        range_match = re.findall(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*元", raw_answer)
        if range_match:
            detected_price = float(range_match[0][0])
        else:
            single_nums = re.findall(r"(\d+(?:\.\d+)?)\s*元", raw_answer)
            if single_nums:
                detected_price = float(single_nums[0])

    if is_beverage_item(item_name) and detected_price > 20.0:
        detected_price = 3.0
    elif detected_price == 0.0:
        detected_price = 3.0 if is_beverage_item(item_name) else 15.0

    return round(float(detected_price), 2)


def run_original_pipeline(query, chat_history=None):
    trace = new_trace(query)
    pipeline_started = time.perf_counter()

    stage_started = time.perf_counter()
    try:
        if original_classify_intent is None:
            intent = "SHOPPING"
        else:
            intent = original_classify_intent(query)
    except Exception as err:
        intent = "SHOPPING"
        trace["errors"].append({"stage": "intent_check", "error": str(err)})
    if intent == "INVALID":
        intent = "SHOPPING"
        trace_stage(trace, "intent_check", stage_started, status="fallback", intent=intent)
    else:
        trace_stage(trace, "intent_check", stage_started, intent=intent)

    item = normalize_entity(query, trace)

    future_memory = EXECUTOR.submit(get_memory_context, query)
    future_web = EXECUTOR.submit(run_web_search, item)
    future_crawler = EXECUTOR.submit(run_price_crawler, item)

    stage_started = time.perf_counter()
    try:
        long_term_context, memory_hits = future_memory.result(timeout=3)
        trace_stage(trace, "rag_retrieve", stage_started, context_chars=len(long_term_context or ""), result_count=len(memory_hits))
    except Exception as err:
        long_term_context, memory_hits = "历史档案加载失败，已降级为空上下文。", []
        trace["errors"].append({"stage": "rag_retrieve", "error": str(err)})
        trace_stage(trace, "rag_retrieve", stage_started, status="fallback")

    stage_started = time.perf_counter()
    try:
        info_blocks, raw_info_text, price_table_data = future_web.result(timeout=WEB_SEARCH_TIMEOUT_SECONDS)
        trace_stage(trace, "web_search", stage_started, result_count=len(info_blocks or []))
    except FutureTimeoutError:
        info_blocks = []
        raw_info_text = f"外部 Web Search 超过 {WEB_SEARCH_TIMEOUT_SECONDS} 秒未返回，本次审计将基于历史偏好、爬虫线索和模型常识继续生成。"
        price_table_data = [{"平台": "外部搜索超时", "参考报价/情报说明": "本次未等到 Web Search 返回", "数据出处": ""}]
        trace["errors"].append({"stage": "web_search", "error": f"timeout after {WEB_SEARCH_TIMEOUT_SECONDS}s"})
        trace_stage(trace, "web_search", stage_started, status="timeout", result_count=0)
    except Exception as err:
        info_blocks = []
        raw_info_text = f"外部 Web Search 异常：{err}。本次审计将基于历史偏好、爬虫线索和模型常识继续生成。"
        price_table_data = [{"平台": "外部搜索异常", "参考报价/情报说明": "Web Search 未成功返回", "数据出处": ""}]
        trace["errors"].append({"stage": "web_search", "error": str(err)})
        trace_stage(trace, "web_search", stage_started, status="fallback", result_count=0)

    stage_started = time.perf_counter()
    try:
        crawler_results = future_crawler.result(timeout=2.5)
        trace_stage(trace, "price_crawler", stage_started, result_count=len(crawler_results or []))
    except Exception as err:
        crawler_results = []
        trace["errors"].append({"stage": "price_crawler", "error": str(err)})
        trace_stage(trace, "price_crawler", stage_started, status="timeout")

    if crawler_results:
        raw_info_text = "【什么值得买精选行情】\n" + compact_price_context(crawler_results) + "\n\n" + raw_info_text

    memory_ctx = long_term_context
    profile = {"current_surplus": get_current_surplus()}

    stage_started = time.perf_counter()
    raw_answer = OriginalAgentHarness().run_harness(
        item,
        raw_info_text,
        profile,
        long_term_context,
        memory_ctx,
        chat_history=chat_history,
    )
    trace_stage(trace, "llm_audit", stage_started, answer_chars=len(raw_answer or ""))

    detected_price = parse_price(raw_answer or "", item)
    final_display_text = raw_answer.split("PRICE_DATA:")[0].strip() if "PRICE_DATA:" in raw_answer else (raw_answer or "").strip()

    trace["status"] = "ok"
    trace["total_latency_ms"] = round((time.perf_counter() - pipeline_started) * 1000, 2)
    save_trace_log(trace)

    return {
        "raw_answer": raw_answer,
        "display_answer": final_display_text,
        "item": item,
        "price": detected_price,
        "info_blocks": (info_blocks or [])[:4],
        "price_table_data": price_table_data or [],
        "crawler_results": crawler_results or [],
        "long_term_context": long_term_context,
        "memory_hits": memory_hits,
        "trace": trace,
        "current_surplus": profile["current_surplus"],
    }
