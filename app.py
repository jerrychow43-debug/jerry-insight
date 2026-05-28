import os
import time
import json
import re
import threading
import chromadb
import numpy as np
import pandas as pd
import streamlit as st
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor

# =====================================================================
# 🔒 1. 初始化页面配置与强效会话隔离
# =====================================================================
st.set_page_config(page_title="Jerry-Insight Pro v3.5+", layout="wide", page_icon="🛡️")

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

if not st.session_state['authenticated']:
    st.title("🛡️ Jerry-Insight Pro 访问鉴权")
    input_password = st.text_input("请输入访问令牌 (Token)：", type="password")
    if input_password == "jerry2026":
        st.session_state['authenticated'] = True
        st.rerun()
    st.stop()

# 初始化核心生命周期变量
if "active_query" not in st.session_state:
    st.session_state["active_query"] = None
if "has_searched" not in st.session_state:
    st.session_state["has_searched"] = False
if "expense_recorded" not in st.session_state:
    st.session_state["expense_recorded"] = False

# =====================================================================
# 🛠️ 2. 核心组件与通知组件引入
# =====================================================================
from bs4 import BeautifulSoup  
from core.router import classify_intent, clean_query_to_entity
from core.memory_manager import AdvancedMemoryManager
from core.hybrid_retriever import JaccardHybridRetriever
from tools.mcp_server import JerryMcpServer

from core.brain import ask_llm
from tools.search import web_search_pro
from tools.price_crawler import crawl_smzdm_price  
from core.jerry_fsm_agent import JerryFSMAgent     
from data.sql_db import save_audit_log
from dotenv import load_dotenv

load_dotenv()
WECHAT_TOKEN = st.secrets.get("PUSH_TOKEN", os.getenv("PUSH_TOKEN"))
DINGTALK_TOKEN = st.secrets.get("DING_WEBHOOK", os.getenv("DING_WEBHOOK"))

try:
    from tools.notify import push_wechat, push_dingtalk
except ImportError:
    def push_wechat(content): return "本地零件未就绪"
    def push_dingtalk(content, title=None): return "本地零件未就绪"

FILE_LOCK = threading.Lock()
PROFILE_FILE = "jerry_profile.json"

if 'ASYNC_EXECUTOR' not in st.session_state:
    st.session_state['ASYNC_EXECUTOR'] = ThreadPoolExecutor(max_workers=8)

@st.cache_resource
def init