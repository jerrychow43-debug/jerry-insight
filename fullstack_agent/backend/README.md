# Jerry-Insight FastAPI Backend

这是省钱智探 Agent 的轻量 FastAPI 后端版本，用来练习和展示“前后端分离 + Agent API + SQLite 持久化”的全栈结构。

## LifeOps Agent

当前后端新增了 `Jerry LifeOps Agent` API。它不是普通聊天接口，而是事件驱动的 Agent Runtime：

```text
事件 -> Runbook -> Toolset -> Memory Layers -> Safety Gate -> Report
```

借鉴点：

- `HolmesGPT`：runbook、toolset、权限安全、什么时候人工介入。
- `Letta / MemGPT`：core memory、recall memory、archival memory 三层记忆。
- `GPT-Researcher`：planner / executor / publisher 的研究报告流程。
- `Aider`：只选择和任务相关的上下文，不把所有资料塞给模型。

## 功能

- `GET /api/health`：检查服务状态
- `POST /api/chat`：提交用户问题，返回 Agent 回复和耗时
- `GET /api/history`：查看历史问答记录
- `DELETE /api/history`：清空历史记录
- `GET /api/lifeops/spec`：查看 LifeOps 事件类型、toolset 和 runbook
- `POST /api/lifeops/run`：运行一个 LifeOps 事件
- `GET /api/lifeops/runs`：查看最近 LifeOps 运行记录

LifeOps 当前支持四类事件：

```text
budget_anomaly        消费异常事件
procurement_decision  采购决策事件
interview_countdown   面试冲刺事件
learning_delay        学习延期事件
```

## 启动

```bash
cd fullstack_agent/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

启动后打开：

```text
http://localhost:8000/docs
```

## 环境变量

可以复用项目根目录 `.env`：

```env
DEEPSEEK_API_KEY=your_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
```
