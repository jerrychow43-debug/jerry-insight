# 🛡️ Jerry-Insight Pro v3.5

> **工业级消费风控与排雷 Agent 引擎（自研 Harness 有限状态机 + 标准 MCP 网关版）**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Framework: Streamlit](https://img.shields.io/badge/Framework-Streamlit-FF4B4B.svg)](https://streamlit.io/)
[![Protocol: MCP](https://img.shields.io/badge/Protocol-MCP-green.svg)](https://modelcontextprotocol.io/)

本项目针对传统大模型 RAG 应用在**“工具调度死循环”、“长文本记忆丢失”、“输出格式断裂”以及“单线程网络 I/O 阻塞导致前端 UI 卡死”**等工业级四大缺陷，完全抛弃了 LangChain / LangGraph 等重度封装的黑盒框架。

系统从底层纯手写了一套 **Harness 有限状态机 (FSM) 控制器**，打通了全网去重比价爬虫、混合向量库、标准 Model Context Protocol (MCP) 资产托管服务、常驻线程池异步消息分发（微信+钉钉），具备极高的工程确定性、自愈降级能力和线程安全性。

---

## 🚀 核心技术亮点与工业级痛点解决

| 工业级 Agent 缺陷/痛点                     | 本项目硬核解决方案（像素级对齐）                                                                                                                                                                                                                                                                              |
| :----------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **1. 传统 RAG 指代不明与模糊输入**   | **前置意图消解路由 (`core.intent_router`)**：在并行检索前，缝合双阶段高频分流器（Two-Stage Router），结合短期记忆（Session State）进行指代消解与模糊词翻译，自动将“它”、“这个”补全为精确商品名词。                                                                                                |
| **2. 工具调度死板与黑盒死循环**      | **手写 Harness 有限状态机 (FSM)**：基于 `while` 循环构建标准的 `Think-Act-Observe` 闭环。在大脑发现初始情报不足时，自主下发网络搜索工具进行二轮追加追查，直至触发 `Final Answer` 状态收敛。                                                                                                       |
| **3. 记忆管理粗暴截断与 Token 爆炸** | **高级记忆治理机制 (`core.memory_manager`)**：采用动态窗口摘要压缩。短期记忆触及临界点时，自动调用大模型执行流式脱水压缩，生成核心红线摘要挂载于 System Prompt 头部，确保长期核心偏好规则绝对不丢失。                                                                                                 |
| **4. 输出格式断裂导致系统瘫痪**      | **三层健壮降级容错自愈链**：采用 `try-except` 强行捕获大模型 JSON 破损异常。第一、二层通过提示词追加进行实时状态纠偏与动态自愈；最终极限层通过纯文本安全熔断 Fallback 强行截获价格块，保证系统 0 崩溃。                                                                                               |
| **5. 高并发下资产账本读写错乱**      | **标准 MCP 协议网关 + 互斥锁 (`tools.mcp_server`)**：基于标准的 Model Context Protocol (MCP) 规范手写 RPC 托管网关。数据改写动作内联操作系统级线程互斥锁（`threading.Lock`），实现分布式、线程安全的资产账本安全联动闭环。                                                                          |
| **6. 外部网络 I/O 导致前端 UI 瘫痪** | **页面生命周期通知挂载解耦机制**：针对多路 Webhook（微信+钉钉）网络请求高延迟导致 Streamlit 渲染卡死的痛点，重构引入全局单例 `ThreadPoolExecutor` 常驻后台线程池；点击扣款时秒级改写账本并暂存通知，直接 rerun 刷新前端（体感延时 <50ms），由新生命周期开头的后台线程静默异步消费推送，实现完全解耦。 |

---

## 🛠️ 系统后端架构拓扑

```text
[User Query] -> [Two-Stage Intent Router (意图分流)]
                       │
                       ▼ (合法业务请求)
         [Context 指代消解 / 模糊词翻译]
                       │
     ┌─────────────────┴─────────────────┐
     ▼ (并行调度复用全局常驻线程池)           ▼
[ChromaDB 向量检索]                 [全网比价爬虫抓取]
     │                                   │
     └─────────────────┬─────────────────┘
                       ▼
         [Jaccard Hybrid Rerank (去重重排)]
                       │
                       ▼
         [JerryAgentHarness 有限状态机] ◄─── (多轮自主追查、格式纠偏自愈)
                       │
                       ▼ (状态收敛 Final Answer)
     ┌─────────────────┴─────────────────┐
     ▼                                   ▼
[Streamlit Trace 思考树看板]         [标准 MCP RPC 资产记账网关]
                                         │ (OS 级 Mutex Lock 保护)
                                         ▼
                                [异步通知暂存挂载区]
                                         │
                                         ▼ (常驻后台线程静默消费)
                                [微信推送 + 钉钉群机器人双路送达]
```


## 📂 项目模块化目录架构

**Plaintext**

```
├── main.py                 # Streamlit 全局可视看板、可观测性思考树渲染与调度中枢
├── core/
│   ├── intent_router.py    # 双阶段高频意图分流器 (Two-Stage Router)
│   ├── memory_manager.py   # 智能上下文脱水与二级记忆治理 (AdvancedMemoryManager)
│   └── hybrid_retriever.py # Jaccard 语义去重混合检索重排引擎 (Hybrid-Rerank)
├── tools/
│   ├── mcp_server.py       # 标准 Model Context Protocol (MCP) 线程安全账务托管服务器
│   ├── search.py           # Tavily Pro 并行网络情报检索组件
│   └── notify.py           # 微信/钉钉 Webhook 高频分发模块
└── data/
    └── sql_db.py           # 生产级审计日志持久化本地安全仓储
```

## 📦 技术栈 (Tech Stack)

* **LLM Core** : DeepSeek-Chat (支持 DeepSeek-R1 深度思考流策略对齐)
* **Frontend/Observability** : Streamlit (大厂敏捷开发测试控制台模式，手写实时 Trace 思考树 Timeline)
* **Vector DB** : ChromaDB (用户长期财务画像与雷点偏好档案挂载)
* **Reranker** : Custom Jaccard Matrix Reranker (多源情报语义相似度去重比价重排)
* **Protocol & Concurrency** : Model Context Protocol (MCP) + ThreadPoolExecutor (全局常驻线程池) + threading.Lock (文件互斥锁)


## ⚙️ 快速开始 (Quick Start)

### 1. 环境准备与依赖安装

**Bash**

```
git clone [https://github.com/jerrychow43-debug/jerry-insight.git](https://github.com/jerrychow43-debug/jerry-insight.git)
cd jerry-insight
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置本地环境变量

在项目根目录下创建 `.env` 文件，塞入你的核心 API 密钥：

**代码段**

```
DEEPSEEK_API_KEY="your_deepseek_api_key"
TAVILY_API_KEY="your_tavily_api_key"
```

### 3. 本地启动服务

**Bash**

```
streamlit run main.py
```

```

```
