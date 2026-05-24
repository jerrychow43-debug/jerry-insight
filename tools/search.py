import os
import requests
import math
import re
from tavily import TavilyClient

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

def fetch_price_info(tavily_client, query: str):
    """
    【全新升级看板机制】：彻底砍掉网页正文乱抠数字的逻辑，
    直接根据权威数据源拉出渠道名称和验证跳转链接。
    """
    price_query = f"{query} 真实售价 官方旗舰店 购买渠道 价格"
    price_data = []
    
    # 彻底拉黑干扰文章、校招、八股文等脏数据来源域名
    junk_domains = [
        "woshipm.com", "nowcoder.com", "36kr.com", "cyzone.cn", 
        "21jingji.com", "haitao.com", "vocus.cc", "landtop.com.tw", "bianews.com"
    ]
    
    try:
        res = tavily_client.search(query=price_query, search_depth="basic", max_results=6)
        for r in res['results']:
            text = r['content']
            link = r['url']
            
            # 命中黑名单直接扔掉
            if any(domain in link for domain in junk_domains):
                continue
                
            # 智能提取核心平台渠道
            platform = "全网综合比价源"
            if "jd.com" in link or "京东" in text: 
                platform = "京东 JD 旗舰渠道"
            elif "tmall.com" in link or "天猫" in text: 
                platform = "天猫 Tmall 官方渠道"
            elif "pinduoduo" in link or "pdd" in link or "拼多多" in text: 
                platform = "拼多多 PDD 补贴渠道"
            elif "taobao.com" in link or "淘宝" in text: 
                platform = "淘宝 Taobao 零售渠道"
            elif "smzdm.com" in link: 
                platform = "什么值得买 价格聚合"
            elif "bilibili.com" in link: 
                platform = "B站 视频评测避坑渠道"
            
            price_data.append({
                "平台": platform,
                "参考报价/情报说明": "点击右侧链接核实最新券后价",  # 👈 不再直接写死容易抓错的数字，还你纯净看板
                "数据出处": link
            })
    except:
        pass
    
    # 只要前 4 条最靠谱的
    price_data = price_data[:4]
    
    # 兜底渠道骨架
    if not price_data:
        price_data = [{"平台": "官方电商渠道", "参考报价/情报说明": "点击右侧链接前往核实", "数据出处": "https://www.taobao.com"}]
    return price_data

def web_search_pro(query):
    """
    终极自愈检索流：具备【短词语义约束防御】、【链接强制去重】与【纯渠道价格面板】功能
    """
    tavily_key = os.getenv("TAVILY_API_KEY")
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
        res = tavily.search(query=refined_search_query, search_depth="advanced", max_results=8)
        
        for r in res['results']:
            link = r['url']
            
            # 命中黑名单域名直接扔掉
            if any(domain in link for domain in blacklisted_domains):
                continue
                
            # 如果是纯海淘转运或者旅游公司乱入，通过关键字二次斩断
            if len(query) <= 2 and any(x in r['content'] for x in ["海淘", "转运", "旅游", "导游", "线路"]):
                continue

            if any(domain in link for domain in ["smzdm.com", "zhihu.com"]):
                paragraphs = [p.strip() for p in r['content'].split("\n") if len(p.strip()) > 20]
                for p in paragraphs: raw_blocks.append((p, link))
                continue

            jina_url = f"https://r.jina.ai/{link}"
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                resp = requests.get(jina_url, headers=headers, timeout=5)
                if any(x in resp.text for x in ["验证码", "Security", "403 Forbidden"]) or len(resp.text) < 300:
                    paragraphs = [p.strip() for p in r['content'].split("\n") if len(p.strip()) > 20]
                else:
                    paragraphs = [p.strip() for p in resp.text[:1500].split("\n") if len(p.strip()) > 30]
            except:
                paragraphs = [p.strip() for p in r['content'].split("\n") if len(p.strip()) > 20]
                
            for p in paragraphs: raw_blocks.append((p, link))

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