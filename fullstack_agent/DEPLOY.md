# Jerry-Insight Pro Deployment

Recommended deployment:

- Backend: Render Web Service
- Frontend: Vercel Project

The latest local version is the two-tab Agent workspace:

- `省钱智探 Pro`
- `ProjectOps 排障 Agent`

If the deployed site still shows `AgentForge Lab`, it is an older Vercel build and needs redeployment from the latest GitHub commit.

## 1. Push Code To GitHub

From the repository root:

```bash
git add fullstack_agent .gitignore
git commit -m "Update Jerry Insight Pro agent workspace"
git push
```

Do not commit `.env`, local databases, logs, `node_modules`, or cache folders.

## 2. Deploy Backend To Render

Create or update a Render `Web Service`.

Settings:

```text
Root Directory: fullstack_agent/backend
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
```

Environment variables:

```text
DEEPSEEK_API_KEY=your_deepseek_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
TAVILY_API_KEY=your_tavily_key
DINGTALK_WEBHOOK=your_optional_dingtalk_webhook
```

After deployment, test:

```text
https://your-render-service.onrender.com/api/health
```

Expected response contains:

```json
{
  "status": "ok",
  "service": "jerry-insight-agent-api"
}
```

## 3. Deploy Frontend To Vercel

Create or update a Vercel project.

Settings:

```text
Root Directory: fullstack_agent/frontend
Framework Preset: Vite
Build Command: npm run build
Output Directory: dist
```

Environment variables:

```text
VITE_API_BASE=https://your-render-service.onrender.com
```

Redeploy after changing `VITE_API_BASE`.

## 4. Deployment Notes

- Vercel must not use `127.0.0.1:8000` in production.
- Render free services can cold start, so the first request may be slow.
- Render free filesystem persistence is not reliable for long-term data. SQLite is fine for demo use, but a production version should use a managed database.
- ProjectOps can only scan directories available to the backend environment. On Render, it cannot scan your Windows local path unless that project exists in the deployed filesystem.
