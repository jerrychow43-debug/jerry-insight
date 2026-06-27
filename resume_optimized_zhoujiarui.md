# 周嘉睿 - 简历

**湖北大学 · 电子信息工程 · 2026届**  
武汉 | 18086663259 | jerrychow43@gmail.com  
GitHub: <https://github.com/jerrychow43-debug/jerry-insight>

## 教育背景

**湖北大学 / 电子信息工程 / 本科**　　　　　2022.09 - 2026.06

- 荣誉：优秀毕业生奖学金、优秀学生奖学金
- 英语：CET-6 467、CET-4 450
- 竞赛/证书：蓝桥杯 C/C++ 程序设计湖北赛区一等奖、全国总决赛优秀奖；软件设计师中级

## 技术能力

- **AI Agent**：FSM / Harness 执行控制、工具调用、RAG、Prompt 设计、Trace 可观测、失败降级、人工确认
- **大模型工程**：OpenAI-compatible API / DeepSeek、LLaMA-Factory、Qwen2.5-1.5B、SFT + LoRA 微调实验、结构化 JSON 输出
- **后端与系统**：Python、Streamlit、FastAPI、SQLite / JSON、ChromaDB、ThreadPoolExecutor
- **Linux C++**：Socket、HTTP、SSE、RPC、多线程、文件持久化、协议解析、前后端联调

## 项目经历

### 省钱智探 Agent：消费风控与记账智能体

**个人项目 | Python / Streamlit / RAG / LoRA | 2026.02 - 2026.06**

- GitHub：<https://github.com/jerrychow43-debug/jerry-insight>
- 线上地址：<https://jerry-insight-2epkw2pl4pfcyxhtyypizl.streamlit.app/>

面向“买前查价难、买后记账散、历史消费难复盘”的个人消费场景，独立开发消费决策 Agent，支持商品问价、购买审计、账本扣减、余额加回、撤销流水、历史记忆、钉钉通知和 Trace 复盘。

- **Harness / FSM 控制**：自研执行层将输入路由、实体抽取、RAG 检索、Web Search、价格线索处理、LLM 审计、账本确认拆成可观测阶段；确定性账本动作不直接交给 LLM，降低黑盒执行风险。
- **反爬与价格策略**：未强行绕过电商反爬，优先使用公开 Web Search / Tavily 获取价格线索与来源链接，将价格作为候选证据并提示用户核验；对外部搜索失败、价格缺失、页面结构变化提供降级说明。
- **输入治理与评估**：规则优先处理记账、退款、撤销、帮助类输入，商品问价进入审计链路；基于自建消费场景样本验证意图分流、金额提取和账本状态变化。
- **RAG 与个性化**：使用 ChromaDB 记录历史购买、拦截和偏好信息，结合 Jaccard / rerank 召回用户历史上下文，与实时搜索证据共同进入审计提示词。
- **可观测与优化**：构建 Agent Trace 记录意图识别、实体抽取、RAG、Web Search、LLM 审计等阶段耗时和异常；定位搜索瓶颈后加入轻量检索、超时控制和失败降级，复测中链路平均耗时由约 51s 降至约 8.75s。
- **微调实验**：使用 AutoDL RTX 4090D + LLaMA-Factory 对 Qwen2.5-1.5B-Instruct 做 SFT + LoRA，训练 155 条消费解析样本，3 epoch 后 train_loss=0.2385；用于验证“用户输入 -> intent / item / amount / action JSON”的入口解析能力，商品和金额抽取更干净。

### C++ MiniChat：Linux Socket Web 聊天系统

**个人项目 | C++ / Linux / HTTP / SSE / RPC | 2026.06**

基于 Linux socket 从零实现轻量 Web 聊天服务，浏览器通过 HTTP 接口发送/拉取消息，服务端完成请求解析、路由分发、JSON 响应拼装和文件持久化。

- **网络服务端实现**：基于 socket 解析浏览器 HTTP 请求，实现 `/api/send`、`/api/messages`、`/api/search`、`/api/users`、`/events` 等接口。
- **RPC 用户服务接入**：接入独立 C++ RPC 用户服务，支持注册、登录、token 校验、刷新保持登录态和退出登录，形成聊天服务与用户服务拆分的小型多服务架构。
- **实时推送与并发处理**：通过 SSE 长连接实时推送新消息，并使用多线程处理客户端连接，避免长连接阻塞普通请求。
- **权限与状态管理**：实现房间聊天、私聊权限过滤、在线用户列表、消息搜索、测试数据清理；私聊过滤在服务端完成，避免只依赖前端隐藏。
- **持久化与兼容**：消息持久化到 `data/messages.tsv`，并兼容旧版消息格式，覆盖网络编程、协议解析、并发处理、状态管理和前后端联调能力。

## 实习经历

### 武汉威士讯信息技术有限公司 · 专业集中实习

**2025.06 - 2025.07**

- 参与企业信息化项目的需求沟通、基础功能体验、测试记录整理、部署实施和问题反馈。
- 了解服务器部署、数据库、权限管理、数据安全及前后端协作等工程实践流程。

## 竞赛与证书

- 2025 睿抗机器人开发者大赛（RAICOM）全国总决赛三等奖、湖北赛区二等奖
- 第十六届蓝桥杯全国软件和信息技术专业人才大赛 C/C++ 程序设计湖北赛区一等奖、全国总决赛优秀奖
- 计算机技术与软件专业技术资格：中级软件设计师
