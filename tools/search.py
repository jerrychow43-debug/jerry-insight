# Jerry-Insight-Pro/tools/search.py
import os
import requests
import math
import re
import streamlit as st
from tavily import TavilyClient
from urllib.parse import urlparse

def safe_secret_get(key, default=None):
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

def text_to_vector(text):
    """ 将文本转换为词频向量（纯 Python 实现） """
    words = [w for w in text if w.strip()]
    vector = {}
    for word in words:
        vector[word] = vector.get(word, 0) + 1
    return vector

def calculate_cosine_similarity(vec1, vec2):
    """ 计算两条文本的余弦相似度 """
    intersection = set(vec1.keys()) & set(vec2.keys())
    numerator = sum([vec1[x] * vec2[x] for x in intersection])
    sum1 = sum([vec1[x]**2 for x in vec1.keys()])
    sum2 = sum([vec2[x]**2 for x in vec2.keys()])
    denominator = math.sqrt(sum1) * math.sqrt(sum2)
    return float(numerator) / denominator if denominator else 0.0

def _dedupe_price_labels(labels):
    cleaned = []
    seen_numbers = set()
    for label in labels:
        number_match = re.search(r"\d+(?:\.\d+)?", label)
        if not number_match:
            continue
        number_key = str(float(number_match.group(0)))
        if number_key in seen_numbers:
            continue
        seen_numbers.add(number_key)
        cleaned.append(label.strip())
    return cleaned


def extract_price_labels(text: str):
    if not text:
        return []
    patterns = [
        r"(?:券后|到手|售价|价格|低至|仅需|约|￥|¥)\s*[￥¥]?\s*\d+(?:\.\d+)?\s*(?:元|块)?",
        r"[￥¥]\s*\d+(?:\.\d+)?",
        r"\d+(?:\.\d+)?\s*(?:元|块)",
    ]
    candidates = []
    for pattern in patterns:
        for match in re.findall(pattern, text):
            item = str(match).strip()
            if item and item not in candidates:
                candidates.append(item)
            if len(candidates) >= 3:
                break
        if candidates:
            break
    return _dedupe_price_labels(candidates)


def extract_price_text(text: str):
    """从搜索摘要中提取可能的价格片段，只作为展示线索，最终仍以来源页面为准。"""
    return " / ".join(extract_price_labels(text)[:3])

def extract_budget(query: str):
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块|块钱|rmb|RMB|以内|预算)", query)
    return float(match.group(1)) if match else None

def extract_price_numbers(text: str):
    if not text:
        return []
    values = []
    for match in re.findall(r"(?:￥|¥)?\s*(\d+(?:\.\d+)?)\s*(?:元|块)?", text):
        try:
            values.append(float(match))
        except ValueError:
            continue
    return values


def price_value(label: str):
    match = re.search(r"\d+(?:\.\d+)?", label or "")
    return float(match.group(0)) if match else None


def clean_price_text_for_budget(price_text: str, budget: float | None):
    if not budget or not price_text:
        return price_text
    labels = [item.strip() for item in price_text.split("/") if item.strip()]
    kept = []
    for label in labels:
        value = price_value(label)
        if value is None:
            continue
        if budget * 0.25 <= value <= budget * 1.25:
            kept.append(label)
    return " / ".join(_dedupe_price_labels(kept)[:3])

PRICE_PLATFORMS = [
    {"name": "京东 JD", "domains": ["jd.com", "3.cn"], "query": "{q} site:jd.com 到手价 OR 售价 OR 价格"},
    {"name": "天猫 Tmall", "domains": ["tmall.com"], "query": "{q} site:tmall.com 到手价 OR 售价 OR 价格"},
    {"name": "淘宝 Taobao", "domains": ["taobao.com"], "query": "{q} site:taobao.com 到手价 OR 售价 OR 价格"},
    {"name": "拼多多 PDD", "domains": ["pinduoduo.com", "yangkeduo.com"], "query": "{q} site:pinduoduo.com 到手价 OR 售价 OR 价格"},
    {"name": "什么值得买", "domains": ["smzdm.com"], "query": "{q} site:smzdm.com 到手价 OR 券后价 OR 爆料价"},
    {"name": "慢慢买", "domains": ["manmanbuy.com"], "query": "{q} site:manmanbuy.com 价格"},
]

def url_domain(url: str):
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""

def domain_matches(domain: str, allowed_domains):
    return any(domain == item or domain.endswith("." + item) for item in allowed_domains)

def infer_platform_from_domain(url: str):
    domain = url_domain(url)
    for platform in PRICE_PLATFORMS:
        if domain_matches(domain, platform["domains"]):
            return platform["name"]
    return ""

def is_bad_price_url(url: str):
    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace("www.", "")
    bad_domains = {"lp.pinduoduo.com"}
    bad_markers = ["ads_channel=", "ads_account=", "ads_set=", "poros/h5", "keywordid=", "exp_id="]
    return domain in bad_domains or any(marker in url for marker in bad_markers)

def is_budget_compatible(price_text: str, budget: float | None):
    if not budget:
        return True
    prices = extract_price_numbers(price_text)
    if not prices:
        return True
    in_range_prices = [price for price in prices if budget * 0.25 <= price <= budget * 1.25]
    if not in_range_prices:
        return False
    return True

def _search_tavily(tavily_client, search_kwargs):
    try:
        return tavily_client.search(**search_kwargs)
    except TypeError:
        fallback_kwargs = dict(search_kwargs)
        fallback_kwargs.pop("include_domains", None)
        return tavily_client.search(**fallback_kwargs)


def _append_platform_result(price_data, seen_links, platform_def, result, budget=None):
    text = result.get("content", "")
    title = result.get("title", "")
    link = result.get("url", "")
    domain = url_domain(link)

    if not link or link in seen_links or is_bad_price_url(link):
        return
    if not domain_matches(domain, platform_def["domains"]):
        return
    seen_links.add(link)

    source_text = f"{title}\n{text}"
    raw_price_text = extract_price_text(source_text)
    price_text = clean_price_text_for_budget(raw_price_text, budget)
    if raw_price_text and budget and not price_text:
        return
    if not price_text:
        return
    if not is_budget_compatible(price_text, budget):
        return
    price_note = (
        f"搜索摘要识别到可能价格：{price_text}；最终以来源页实时价格为准"
        if price_text
        else "该平台搜索结果未在摘要中暴露价格；保留来源链接用于人工核实"
    )
    price_data.append({
        "平台": platform_def["name"],
        "标题": title,
        "参考报价/情报说明": price_note,
        "识别价格": price_text,
        "数据出处": link,
        "来源域名": domain,
    })


def fetch_price_info(tavily_client, query: str):
    """
    Search-based price evidence.

    这里不直接抓取电商页面正文，避免反爬和动态券后价问题。价格只从 Tavily
    返回的标题/摘要里提取，来源链接保留给用户核实。
    """
    price_data = []
    seen_links = set()
    budget = extract_budget(query)
    
    # 彻底拉黑干扰文章、校招、八股文等脏数据来源域名
    junk_domains = [
        "woshipm.com", "nowcoder.com", "36kr.com", "cyzone.cn", 
        "21jingji.com", "haitao.com", "vocus.cc", "landtop.com.tw", "bianews.com"
    ]
    
    try:
        for platform_def in PRICE_PLATFORMS:
            price_query = platform_def["query"].format(q=query)
            search_kwargs = {"query": price_query, "search_depth": "basic", "max_results": 4}
            # Tavily 支持 include_domains 时会强约束来源；不支持时 site: query 仍然能做一层约束。
            search_kwargs["include_domains"] = platform_def["domains"]
            res = _search_tavily(tavily_client, search_kwargs)
            for r in res["results"]:
                link = r.get("url", "")
                domain = url_domain(link)
                if any(domain_matches(domain, [junk]) for junk in junk_domains):
                    continue
                _append_platform_result(price_data, seen_links, platform_def, r, budget)

        broad_res = tavily_client.search(
            query=f"{query} 价格 到手价 售价 京东 天猫 淘宝 拼多多 什么值得买 慢慢买",
            search_depth="basic",
            max_results=8,
        )
        for r in broad_res["results"]:
            link = r.get("url", "")
            domain = url_domain(link)
            if any(domain_matches(domain, [junk]) for junk in junk_domains):
                continue
            platform_name = infer_platform_from_domain(link)
            if not platform_name:
                continue
            platform_def = next(item for item in PRICE_PLATFORMS if item["name"] == platform_name)
            _append_platform_result(price_data, seen_links, platform_def, r, budget)
    except:
        pass
    
    # 优先展示能从搜索摘要识别到价格的真实电商/比价平台来源；同平台保留少量候选。
    price_data.sort(key=lambda item: (0 if item.get("识别价格") else 1, item.get("平台", "")))
    trimmed = []
    per_platform = {}
    for item in price_data:
        platform = item.get("平台", "")
        per_platform[platform] = per_platform.get(platform, 0) + 1
        if per_platform[platform] <= 2:
            trimmed.append(item)
        if len(trimmed) >= 8:
            break
    price_data = trimmed
    
    # 兜底渠道骨架
    if not price_data:
        price_data = [{"平台": "平台定向搜索", "标题": "", "参考报价/情报说明": "搜索 API 未返回白名单平台价格来源", "识别价格": "", "数据出处": "", "来源域名": ""}]
    return price_data

def web_search_pro(query):
    """
    终极自愈检索流：具备【短词语义约束防御】、【链接强制去重】与【纯渠道价格面板】功能
    """
    # 💡 完美对齐：优先读取云端的 TAVILY_API_KEY，全自动适配 Secrets 面板
    tavily_key = safe_secret_get("TAVILY_API_KEY")
    tavily = TavilyClient(api_key=tavily_key)
    
    # 策略：搜索引擎重构。如果搜的是超短词（如可乐），强行追加关键词把它拉回到饮料/消费品领域
    refined_search_query = f"{query} 测评 缺点 避坑 真实评价"
    if len(query) <= 2:
        refined_search_query = f"{query} 饮料 难喝 避坑 缺点 测评 长期喝 牙齿"
        
    # 1. 触发全新的纯渠道比价板节点
    price_table_data = fetch_price_info(tavily, query)
    
    raw_blocks = []
    # 强力情报源黑名单（彻底阻断非零售商品网站、面试八股文网站）
    blacklisted_domains = ["woshipm.com", "nowcoder.com", "podcasts.apple.com"]
    
    try:
        res = tavily.search(query=refined_search_query, search_depth="basic", max_results=5)
        
        for r in res['results']:
            link = r['url']
            
            # 命中黑名单域名直接扔掉
            if any(domain in link for domain in blacklisted_domains):
                continue
                
            # 如果是纯海淘转运或者旅游公司乱入，通过关键字二次斩断
            if len(query) <= 2 and any(x in r['content'] for x in ["海淘", "转运", "旅游", "导游", "线路"]):
                continue

            paragraphs = [p.strip() for p in r['content'].split("\n") if len(p.strip()) > 20]
            if not paragraphs and r.get("content"):
                paragraphs = [r["content"].strip()]
            for p in paragraphs:
                raw_blocks.append((p, link))

        if not raw_blocks:
            for r in res['results']: raw_blocks.append((r['content'], r['url']))

        # 2. 算语义相似度得分
        query_vec = text_to_vector(query)
        scored_blocks = []
        for p_text, url in raw_blocks:
            score = calculate_cosine_similarity(query_vec, text_to_vector(p_text))
            scored_blocks.append((p_text, url, score))
            
        # 按分数从高到低大排序
        scored_blocks.sort(key=lambda x: x[2], reverse=True)
        
        # 3. Link 强制去重机制 (Ensuring Diversity)
        seen_urls = set()
        unique_final_blocks = []
        
        for p_text, url, score in scored_blocks:
            if url not in seen_urls:
                seen_urls.add(url)
                unique_final_blocks.append((p_text, url, score))
            if len(unique_final_blocks) == 4: # 攒满 4 个不同的独立通道就收工
                break
                
        # 来源不够的话用兜底补充
        if len(unique_final_blocks) < 4:
            unique_final_blocks = scored_blocks[:4]

        llm_context = "\n".join([f"[独立源: {item[1]}]: {item[0]}" for item in unique_final_blocks])
        
        return unique_final_blocks, llm_context, price_table_data

    except Exception as e:
        return [], f"异常: {str(e)}", price_table_data
