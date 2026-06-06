# Jerry-Insight Vue Frontend

这是省钱智探 Agent 的 Vue 3 前端演示版本，用于调用 FastAPI 后端接口。

## 启动

先启动后端：

```bash
cd fullstack_agent/backend
python -m uvicorn main:app --reload --port 8000
```

再启动前端：

```bash
cd fullstack_agent/frontend
npm install
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

