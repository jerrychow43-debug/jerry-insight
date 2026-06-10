# Jerry Agent Crew

个人任务多智能体工作台 MVP。

这个目录是从原来的“省钱智探 Agent”拆出来的新方向：不再把产品做成一个普通聊天框，而是做成“任务模板 + 多 Agent 分工 + Skill Registry + Trace”的 Agent Workspace。

## 第一版四个功能模板

| 模板 | 作用 | 产物 |
| --- | --- | --- |
| 省钱计划 / 消费决策 | 继承原省钱智探 Agent，支持问价、历史消费上下文、预算判断、记账确认思路 | 购买建议、候选价格、预算上下文 |
| 采购调研 | 面向较复杂的购买任务，例如显示器、耳机、键盘对比 | 采购调研报告、候选来源、观察清单建议 |
| 面试准备 | 读取项目和笔记，整理 Agent 岗面试话术和追问 | 面试回答稿、项目包装、追问清单 |
| 学习资料整理 | 读取 Linux/C++/Agent 笔记，生成复习大纲 | 复习计划、知识点整理 |

## Agent Team

```text
ManagerAgent   负责理解目标和拆任务
ResearchAgent  负责搜索候选价格或读取本地资料
AnalystAgent   负责结合账本、预算、项目笔记做分析
WriterAgent    负责生成结构化 Markdown 产物
ReviewerAgent  负责检查风险、来源可信度、是否需要确认
ExecutorAgent  负责准备产物或待确认动作
```

## Skill Registry

MVP 内置这些 Skills：

```text
web_price_search   搜索 API 候选价格，不硬爬电商页面
ledger_summary     读取旧账本/画像摘要
report_artifact    生成 Markdown 产物
ledger_write_plan  创建待确认记账动作，不自动扣款
```

省钱模块会参考主项目已有逻辑，但这版把 `price_crawler.py` 那种硬爬虫降级为非主路径，默认使用搜索引擎/API 摘要做候选价格来源。

## 运行

在仓库根目录执行：

```bash
streamlit run jerry_agent_crew/app.py
```

如果要启用联网候选价格搜索，配置：

```bash
TAVILY_API_KEY=your_key
```

没有配置时也能运行，只是价格搜索会显示安全降级提示。

## 和旧项目的关系

旧项目是：

```text
聊天输入 -> 意图路由 -> 搜索/RAG/记账 -> 回复
```

新方向是：

```text
任务模板 -> ManagerAgent 拆任务 -> 多 Agent 协作 -> Skill 调用 -> Trace -> 产物
```

旧的省钱能力会逐步迁移成 `省钱计划 / 消费决策` 模板下的 Skills 和数据工具。

## 下一步

1. 把旧项目的账本写入、撤销、加回逻辑封成 `finance_mcp_server`。
2. 把搜索 API 候选价格模块做成可测试 Skill。
3. 增加任务持久化：`tasks.jsonl`。
4. 增加 Approval Queue 页面，所有记账/通知类动作先确认再执行。
5. 增加 Eval 数据集，测试四个模板的工具选择和输出质量。

