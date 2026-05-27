# Jerry-Insight-Pro/tools/price_crawler.py
import requests
from bs4 import BeautifulSoup

def crawl_smzdm_price(keyword):
    """
    专门去‘什么值得买’（SMZDM）定向爆破抓取该商品的最新券后价
    """
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
        
        # 寻找商品卡片列表（根据实际网页结构调整 class 名）
        items = soup.find_all("div", class_="feed-block-info", limit=2)
        for item in items:
            title_node = item.find("h5", class_="feed-block-title")
            price_node = item.find("div", class_="z-highlight") # 优惠价格标签
            
            if title_node and price_node:
                title = title_node.get_text().strip()
                price = price_node.get_text().strip()
                results.append({
                    "platform": "什么值得买",
                    "price_info": f"【实时行情】{title} ｜ 爆料价: {price}",
                    "source": url
                })
        return results
    except Exception as e:
        print(f"❌ [爬虫异常] 抓取失败: {e}")
        return []