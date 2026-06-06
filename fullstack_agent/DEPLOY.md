# Vue + FastAPI 上线部署说明

推荐组合：

- 后端：Render
- 前端：Vercel

## 1. 先提交代码到 GitHub

在项目根目录执行：

```bash
git add fullstack_agent .gitignore
git commit -m "add vue fastapi fullstack agent"
git push
```

## 2. 部署 FastAPI 后端到 Render

1. 打开 Render，新建 `Web Service`。
2. 选择你的 GitHub 仓库。
3. Root Directory 填：

```text
fullstack_agent/backend
```

4. Build Command 填：

```bash
pip install -r requirements.txt
```

5. Start Command 填：

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

6. Environment Variables 里添加：

```text
DEEPSEEK_API_KEY=你的 DeepSeek Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
TAVILY_API_KEY=你的 Tavily Key
DINGTALK_WEBHOOK=你的钉钉机器人 Webhook
```

7. 部署完成后，记录后端地址，例如：

```text
https://jerry-insight-api.onrender.com
```

测试：

```text
https://jerry-insight-api.onrender.com/api/health
```

## 3. 部署 Vue 前端到 Vercel

1. 打开 Vercel，新建 Project。
2. 选择同一个 GitHub 仓库。
3. Root Directory 填：

```text
fullstack_agent/frontend
```

4. Framework Preset 选择：

```text
Vite
```

5. Build Command：

```bash
npm run build
```

6. Output Directory：

```text
dist
```

7. Environment Variables 添加：

```text
VITE_API_BASE=https://你的 Render 后端地址
```

例如：

```text
VITE_API_BASE=https://jerry-insight-api.onrender.com
```

8. 部署完成后，Vercel 会给你一个前端公网地址。

## 4. 注意事项

- 前端不能填 `127.0.0.1:8000`，上线后必须填 Render 后端公网地址。
- Render 免费服务可能冷启动，第一次打开会慢一点。
- 当前 SQLite 数据库在 Render 免费环境里不适合长期稳定持久化，演示可以，正式长期使用建议迁移到云数据库。
- 不要把 `.env` 提交到 GitHub，只提交 `.env.example`。
