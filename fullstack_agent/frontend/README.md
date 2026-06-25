# Jerry-Insight Pro Frontend

Vue 3 + Vite frontend for the Jerry-Insight Pro Agent workspace.

Current UI has two main tabs:

- `省钱智探 Pro`: purchase decision research with evidence, price sources, ledger context and human confirmation actions.
- `ProjectOps 排障 Agent`: import a project directory, build a ProjectMap, search logs/code/config/runbooks and generate an incident triage report.

## Local Run

Start backend first:

```bash
cd fullstack_agent/backend
python -m uvicorn main:app --reload --port 8000
```

Start frontend:

```bash
cd fullstack_agent/frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## Environment Variables

For local development, the frontend defaults to:

```text
http://127.0.0.1:8000
```

For Vercel deployment, configure:

```env
VITE_API_BASE=https://your-render-backend.onrender.com
```
