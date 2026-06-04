# Jerry-Insight / 省钱智探 Agent

一个面向个人消费决策的 Streamlit Agent 项目：用户可以用自然语言询问商品是否值得买、记录已经发生的消费、撤销或加回错误账目，并通过钉钉机器人收到关键操作通知。

项目重点不是做一个通用聊天机器人，而是围绕“买东西前问价 + 买完后记账 + 历史可追踪”这个具体场景，把输入路由、价格检索、RAG 记忆、账本闭环和异步通知串成一个可运行的 Agent 流程。

## 核心功能

| 功能               | 说明                                                                                                             |
| ------------------ | ---------------------------------------------------------------------------------------------------------------- |
| 商品问价与消费审计 | 输入“我想买可乐”“这个显示器值得买吗”等问题后，系统会抽取商品名，检索历史偏好和外部价格信息，再给出购买建议。 |
| 普通对话引导       | 对“怎么用”“你好”“你能干嘛”等非购物输入做轻量回复，并引导用户使用问价和记账功能。                           |
| 直接记账           | 支持“买了雪碧花了3块”“今天午饭花12.5元”等输入，直接写入账本并扣除余额。                                      |
| 加回余额           | 支持“加回来3块”“退回雪碧3元”等输入，用于退款或记错账后的余额修正。                                           |
| 撤销上一笔         | 支持“撤销上一笔”“撤销上一条”“加错了”“上一笔记错了”等口语化指令。                                         |
| 历史持久化         | 问价记录、账本记录和 Trace 日志会写入本地文件，刷新页面后仍可保留。                                              |
| 钉钉通知           | 问价结果、扣钱、加回、撤销等关键事件会通过钉钉机器人异步推送。                                                   |
| Agent Trace        | 记录意图判断、实体抽取、RAG 检索、网页搜索、价格抓取、LLM 审计等阶段耗时和错误信息，方便复盘和定位问题。         |

## 技术栈

- Python、Streamlit
- OpenAI-compatible API / DeepSeek
- FSM / Harness 风格的 Agent 流程控制
- ChromaDB、Jaccard / Rerank 混合检索
- Tavily Web Search、价格爬虫
- ThreadPoolExecutor 异步通知
- JSON / SQLite 本地持久化
- DingTalk 机器人通知
- Prompt Engineering、输入路由、结构化输出解析

## 运行入口

| 文件                       | 用途                                                                                       |
| -------------------------- | ------------------------------------------------------------------------------------------ |
| `app.py`                 | 当前主版本，适配 Streamlit Cloud 和本地运行。                                              |
| `eval_resume_metrics.py` | 基础回归测试脚本，验证输入路由、金额提取、账本操作和异步通知入队耗时。                     |
| `eval_agent_quality.py`  | 面向 Agent 质量的评估脚本，读取 Trace 日志和价格样本表，统计链路耗时、错误和价格命中情况。 |

## Agent 流程

```text
用户输入
  |
  v
输入路由
  |
  +--> 普通问候 / 使用说明回复
  |
  +--> 直接记账 / 加回余额 / 撤销上一笔
  |       |
  |       v
  |    写入账本 + 历史记录 + 钉钉通知
  |
  +--> 商品问价与消费审计
          |
          v
      商品实体抽取
          |
          v
      RAG 历史偏好检索 + Web Search + 价格爬虫
          |
          v
      LLM 审计总结
          |
          v
      用户确认扣款 / 取消购买
          |
          v
      账本更新 + 历史记录 + 钉钉通知
```

## 本地与云端配置

本地运行可以使用环境变量或 `.env`。部署到 Streamlit Cloud 时，建议在 Secrets 面板中配置同名变量。

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
TAVILY_API_KEY=your_tavily_api_key
DINGTALK_WEBHOOK=your_dingtalk_robot_webhook
```

注意：不要把真实的 API Key、钉钉 Webhook、`.env` 或 `.streamlit/secrets.toml` 提交到 GitHub。

## 快速启动

```bash
pip install -r requirements.txt
streamlit run app.py
```

如果要运行本地参考版本：

```bash
streamlit run app_local.py
```

## 本地数据文件

项目运行后会生成一些本地状态文件：

| 文件                            | 说明                              |
| ------------------------------- | --------------------------------- |
| `jerry_profile.json`          | 用户预算、余额和个人偏好。        |
| `jerry_history_sessions.json` | 历史问价和记账会话。              |
| `jerry_ledger.json`           | 消费、退款、撤销等账本流水。      |
| `jerry_trace_logs.jsonl`      | Agent 每次问价链路的 Trace 日志。 |

这些文件适合本地测试和演示。云端部署时，Streamlit Cloud 的本地文件不一定长期稳定，后续可以替换为 SQLite 云盘、Supabase、PostgreSQL 或对象存储。
