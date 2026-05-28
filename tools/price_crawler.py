# Jerry-Insight-Pro/tools/price_crawler.py
import requests
from bs4 import BeautifulSoup

def crawl_smzdm_price(keyword):
    """
    专门去‘什么值得买’（SMZDM）定向爆破抓取该商品的最新券后价
    """
    if not keyword or keyword.strip() == "NONE" or len(keyword) > 15:
        print("🕷️ [底层爬虫] 关键词为空或受到长句子污染，主动熔断拒绝请求。")
        return []

    # 拼装什么值得买的搜索 URL
    url = f"https://search.smzdm.com/?s={keyword}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    print(f"🕷️ [底层爬虫] 正在定向解析什么值得买行情: {url}")
    try:
        response = requests.get(url, headers=headers, timeout=4)
        if response.status_code != 200:
            return []
            
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        
        # 1. 寻找商品卡片列表（放宽到 limit=4 确保链接足够）
        items = soup.find_all("div", class_="feed-block-info", limit=4)
        
        for item in items:
            title_node = item.find("h5", class_="feed-block-title")
            price_node = item.find("div", class_="z-highlight") # 优惠价格标签
            
            # 2. ✨ 【核心修复】：提取该商品的真实详情页点击链接，而不再是总搜索链接！
            item_url = url # 默认兜底
            if title_node and title_node.find("a"):
                real_link = title_node.find("a").get("href")
                if real_link:
                    item_url = real_link
            
            if title_node and price_node:
                title = title_node.get_text().strip()
                price = price_node.get_text().strip()
                results.append({
                    "platform": "什么值得买",
                    "price_info": f"【实时行情】{title} ｜ 爆料价: {price}",
                    "source": item_url  # ✨ 使用该商品的真实独立链接
                })
        return results
    except Exception as e:
        print(f"❌ [爬虫异常] 抓取失败: {e}")
        return []