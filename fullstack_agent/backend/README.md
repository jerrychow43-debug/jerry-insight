# Jerry-Insight FastAPI Backend

这是省钱智探 Agent 的轻量 FastAPI 后端版本，用来练习和展示“前后端分离 + Agent API + SQLite 持久化”的全栈结构。

## 功能

- `GET /api/health`：检查服务状态
- `POST /api/chat`：提交用户问题，返回 Agent 回复和耗时
- `GET /api/history`：查看历史问答记录
- `DELETE /api/history`：清空历史记录

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

