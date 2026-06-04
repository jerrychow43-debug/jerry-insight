# Jerry-Insight-Pro/tools/notify.py
import os
import requests
import json
import streamlit as st

def safe_secret_get(key, default=None):
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

def push_wechat(content):
    """标准的微信推送通知（带强力超时容错与云端全局配置适配）"""
    # 💡 完美对齐：优先读取你截图里的 PUSH_TOKEN，自动兼容云端 Secrets 和本地系统环境
    token = safe_secret_get("PUSH_TOKEN")
    if not token:
        print("【微信推送】未配置 PUSH_TOKEN，通知放弃发送")
        return "未配置 PUSH_TOKEN"
        
    url = 'http://www.pushplus.plus/send'
    payload = {
        "token": token, 
        "title": "🛡️ Jerry-Insight 风控通报", 
        "content": content, 
        "template": "markdown"
    }
    try:
        # 加上 timeout=5，防止 pushplus 服务器卡死导致咱们的网页转圈圈
        response = requests.post(url, json=payload, timeout=5)
        print(f"【微信推送返回】: {response.text}")
        return response.text
    except Exception as e:
        print(f"【微信推送异常】: {e}")
        return f"微信发送失败: {e}"

def push_dingtalk(content, title="🛡️ Jerry-Insight 风控通报"):
    """标准的钉钉群机器人推送（原生通道，极速稳定，全面兼容云端配置）"""
    # 兼容云端主版的 DINGTALK_WEBHOOK，以及旧本地版的 DING_WEBHOOK。
    webhook_url = (
        safe_secret_get("DINGTALK_WEBHOOK")
        or safe_secret_get("DING_WEBHOOK")
    )
    if not webhook_url:
        print("【钉钉推送】未配置 DING_WEBHOOK，通知放弃发送")
        return "未配置 DING_WEBHOOK"
        
    headers = {"Content-Type": "application/json;charset=utf-8"}
    
    # 拼装钉钉标准的 MarkDown 消息体
    # 注意：正文里必须包含你在钉钉机器人安全设置里填写的自定义关键词（比如：Jerry）
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"## {title}\n\n{content}"
        }
    }
    
    try:
        response = requests.post(webhook_url, data=json.dumps(data), headers=headers, timeout=5)
        print(f"【钉钉推送返回】: {response.text}")
        return response.text
    except Exception as e:
        print(f"【钉钉推送异常】: {e}")
        return f"钉钉发送失败: {e}"
