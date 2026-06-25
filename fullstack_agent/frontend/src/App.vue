<template>
  <main class="app-shell">
    <header class="top-bar">
      <div>
        <p class="eyebrow">Jerry Insight Pro</p>
        <h1>工程化 Agent 工作台</h1>
      </div>
      <div class="backend-pill" :class="{ online: backendOk }">
        <span></span>
        <strong>{{ backendOk ? "后端已连接" : "后端未连接" }}</strong>
      </div>
    </header>

    <nav class="mode-tabs" aria-label="Project modes">
      <button type="button" :class="{ active: activeTab === 'deal' }" @click="activeTab = 'deal'">
        省钱智探 Pro
      </button>
      <button type="button" :class="{ active: activeTab === 'ops' }" @click="activeTab = 'ops'">
        ProjectOps 排障 Agent
      </button>
    </nav>

    <section v-if="activeTab === 'deal'" class="project-layout">
      <section class="hero-panel">
        <div>
          <p class="eyebrow">Data Agent + Search Agent + MCP</p>
          <h2>把旧省钱智探升级成消费决策工程应用</h2>
          <p>
            复用 Tavily、平台定向搜索、账本、记忆和确认购买闭环。新版会把搜索来源整理成 evidence、decision、event trace 和可执行动作。
          </p>
        </div>
        <form class="query-box" @submit.prevent="runDealResearch">
          <textarea
            v-model="dealQuery"
            rows="3"
            placeholder="例如：我想买一个 1000 元以内适合写代码的显示器，帮我研究值不值得买"
          ></textarea>
          <button class="primary-button" type="submit" :disabled="dealLoading || !dealQuery.trim()">
            {{ dealLoading ? "研究中..." : "生成购买研究报告" }}
          </button>
        </form>
      </section>

      <section v-if="latestDealRun" class="result-grid">
        <article class="decision-card">
          <small>最终建议</small>
          <strong>{{ latestDealRun.decision.verdict }}</strong>
          <p>{{ latestDealRun.decision.reason }}</p>
          <div class="decision-meta">
            <span>可信度：{{ latestDealRun.decision.confidence }}</span>
            <span>预算：{{ latestDealRun.decision.budget ? `${latestDealRun.decision.budget} 元` : "未识别" }}</span>
            <span>估算价：{{ formatMoney(latestDealRun.decision.estimated_price) }}</span>
          </div>
          <div class="action-row">
            <button class="light-button" type="button" @click="confirmDealPurchase">确认购买并记账</button>
            <button class="ghost-button" type="button" @click="skipDealPurchase">放弃购买</button>
          </div>
        </article>

        <article class="context-card">
          <h3>省钱智探能力复用结果</h3>
          <div class="metric-grid">
            <div>
              <small>Tavily 来源</small>
              <strong>{{ latestDealRun.legacy_audit.search_sources.length }} 条</strong>
            </div>
            <div>
              <small>平台价格来源</small>
              <strong>{{ latestDealRun.legacy_audit.price_table.length }} 条</strong>
            </div>
            <div>
              <small>搜索补充来源</small>
              <strong>{{ latestDealRun.legacy_audit.crawler_sources.length }} 条</strong>
            </div>
            <div>
              <small>当前余额</small>
              <strong>{{ formatMoney(latestDealRun.personal_context.current_surplus) }}</strong>
            </div>
          </div>
        </article>

        <article class="wide-card">
          <div class="section-head">
            <h3>Planner 拆解</h3>
            <span>{{ latestDealRun.product }}</span>
          </div>
          <div class="question-list">
            <div v-for="question in latestDealRun.questions" :key="question.owner">
              <strong>{{ question.owner }} <span class="zh-label">{{ roleLabel(question.owner) }}</span></strong>
              <p>{{ question.question }}</p>
              <small>{{ question.purpose }}</small>
            </div>
          </div>
        </article>

        <article class="wide-card">
          <div class="section-head">
            <h3>多 Agent 编排</h3>
            <span>{{ latestDealRun.agent_runs?.length || 0 }} agents · {{ latestDealRun.mcp_calls?.length || 0 }} MCP calls</span>
          </div>
          <div class="agent-grid">
            <div v-for="agent in latestDealRun.agent_runs || []" :key="agent.agent" class="agent-card">
              <small>{{ agent.status }}</small>
              <strong>{{ agent.agent }} <span class="zh-label">{{ agentLabel(agent.agent) }}</span></strong>
              <p>{{ agent.role }}</p>
              <em>{{ agent.summary }}</em>
              <div class="tool-chip-row">
                <span v-for="call in agent.tool_calls" :key="`${agent.agent}-${call.tool}`">{{ call.tool }}</span>
              </div>
            </div>
          </div>
        </article>

        <article class="wide-card">
          <div class="section-head">
            <h3>证据卡片</h3>
            <span>{{ latestDealRun.evidence.length }} 条</span>
          </div>
          <div class="evidence-grid">
            <div v-for="item in latestDealRun.evidence" :key="`${item.category}-${item.title}-${item.url}`" class="evidence-card">
              <small>{{ item.category }} · {{ categoryLabel(item.category) }} · {{ item.confidence }}</small>
              <strong>{{ item.title }}</strong>
              <span v-if="item.price_text" class="price-badge">{{ item.price_text }}</span>
              <p>{{ item.summary }}</p>
              <a v-if="item.url" :href="item.url" target="_blank" rel="noreferrer">打开来源</a>
              <span v-else>{{ item.source }}</span>
            </div>
          </div>
        </article>

        <article class="wide-card">
          <div class="section-head">
            <h3>价格与来源</h3>
            <span>Tavily / 平台定向搜索来源</span>
          </div>
          <div class="source-table">
            <div class="table-row table-head">
              <span>类型</span>
              <span>价格</span>
              <span>说明</span>
              <span>域名</span>
              <span>链接</span>
            </div>
            <div v-for="row in sourceRows" :key="`${row.type}-${row.url}-${row.info}`" class="table-row">
              <span>{{ row.type }}</span>
              <strong :class="{ muted: !row.priceText }">{{ row.priceText || "未在摘要暴露" }}</strong>
              <span>{{ row.info }}</span>
              <span>{{ row.domain || "-" }}</span>
              <a v-if="row.url" :href="row.url" target="_blank" rel="noreferrer">打开</a>
              <span v-else>-</span>
            </div>
          </div>
        </article>

        <article class="wide-card">
          <details open>
            <summary>省钱智探原始判断</summary>
            <pre>{{ latestDealRun.legacy_audit.display_answer || "暂无原始判断" }}</pre>
          </details>
        </article>

        <article class="wide-card">
          <div class="section-head">
            <h3>账本与历史</h3>
            <span>来自 finance.context.read</span>
          </div>
          <div class="history-grid">
            <section>
              <h4>最近账本</h4>
              <div v-for="row in latestDealRun.personal_context.recent_ledger || []" :key="`ledger-${row.id}`" class="history-row">
                <strong>{{ row.item }}</strong>
                <span>{{ formatMoney(row.amount) }} · {{ row.status }} · {{ row.created_at }}</span>
              </div>
              <p v-if="!(latestDealRun.personal_context.recent_ledger || []).length" class="empty-note">暂无账本记录。</p>
            </section>
            <section>
              <h4>历史与放弃购买</h4>
              <div v-for="row in latestDealRun.personal_context.blocked_items || []" :key="`blocked-${row.id}`" class="history-row">
                <strong>{{ row.item }}</strong>
                <span>{{ row.reason }} · {{ row.created_at }}</span>
              </div>
              <div v-for="row in latestDealRun.personal_context.history || []" :key="`history-${row.id}`" class="history-row">
                <strong>{{ row.intent }}</strong>
                <span>{{ row.user_message }}</span>
              </div>
              <p v-if="!(latestDealRun.personal_context.blocked_items || []).length && !(latestDealRun.personal_context.history || []).length" class="empty-note">暂无历史记录。</p>
            </section>
          </div>
        </article>
      </section>

      <section v-else class="empty-panel">
        <strong>先输入一个真实购买意图。</strong>
        <span>这里会展示联网搜索、价格来源、个人账本上下文和购买动作。</span>
      </section>
    </section>

    <section v-else class="project-layout">
      <section class="hero-panel">
        <div>
          <p class="eyebrow">Project Import + MCP Tool Calling</p>
          <h2>先导入自己的项目，再基于真实文件排障</h2>
          <p>
            这个 Agent 不做万能猜测。它通过 MCP 工具扫描你导入的项目目录，读取真实代码、配置、日志和 runbook，再对故障描述做证据驱动分析。
          </p>
        </div>
        <form class="query-box" @submit.prevent="importOpsProject">
          <input v-model="opsProjectName" placeholder="项目名，例如 Jerry Insight Pro" />
          <input v-model="opsProjectPath" placeholder="项目路径，例如 C:\\Users\\Jerry\\Desktop\\AIstudy\\Jerry-Insight-Pro" />
          <button class="primary-button" type="submit" :disabled="opsImporting || !opsProjectPath.trim()">
            {{ opsImporting ? "导入中..." : "导入项目并生成 ProjectMap" }}
          </button>
          <p v-if="opsImportError" class="form-error">{{ opsImportError }}</p>
        </form>
      </section>

      <section v-if="currentProject" class="ops-grid">
        <article class="score-card">
          <small>当前项目</small>
          <strong>{{ currentProject.name }}</strong>
          <p>{{ currentProject.project_map.scanned_files }} 个文件 · {{ currentProject.project_map.api_routes.length }} 个 API · {{ currentProject.project_map.services.length }} 个服务信号</p>
        </article>

        <article class="pitch-card">
          <h3>处置方式</h3>
          <p>先收集故障事件，再读取项目文件、日志、配置和文档，最后输出检查清单。</p>
          <div class="tool-chip-row">
            <span>项目建图</span>
            <span>日志检索</span>
            <span>代码定位</span>
            <span>安全门</span>
          </div>
        </article>

        <article class="wide-card">
          <div class="section-head">
            <h3>ProjectMap</h3>
            <span>{{ currentProject.project_id }}</span>
          </div>
          <div class="legacy-grid">
            <div>
              <small>扫描文件</small>
              <strong>{{ currentProject.project_map.scanned_files }}</strong>
            </div>
            <div>
              <small>服务信号</small>
              <strong>{{ currentProject.project_map.services.length }}</strong>
            </div>
            <div>
              <small>API 路由</small>
              <strong>{{ currentProject.project_map.api_routes.length }}</strong>
            </div>
            <div>
              <small>Runbook 文档</small>
              <strong>{{ currentProject.project_map.runbooks.length }}</strong>
            </div>
          </div>
        </article>

        <article class="wide-card">
          <div class="section-head">
            <h3>创建故障事件</h3>
            <span>信息越具体，定位越可靠</span>
          </div>
          <form class="incident-box" @submit.prevent="runIncident">
            <div class="incident-form-grid">
              <label>
                <span>故障类型</span>
                <select v-model="incidentType">
                  <option value="api_error">接口报错</option>
                  <option value="startup_error">启动失败</option>
                  <option value="latency_high">超时 / 变慢</option>
                  <option value="dependency_error">依赖异常</option>
                  <option value="deploy_related">部署后异常</option>
                </select>
              </label>
              <label>
                <span>服务 / 模块</span>
                <input v-model="incidentService" placeholder="例如 fullstack_agent/backend 或 order-service" />
              </label>
            </div>
            <label class="field-block">
              <span>错误日志 / traceback</span>
              <textarea
                v-model="incidentErrorLog"
                rows="5"
                placeholder="粘贴后端终端报错、HTTP 状态码、timeout 日志或 import error 堆栈"
              ></textarea>
            </label>
            <div class="incident-form-grid">
              <label>
                <span>最近变更</span>
                <input v-model="incidentRecentChange" placeholder="例如 刚改了依赖、路径、环境变量、部署配置" />
              </label>
              <label>
                <span>影响范围</span>
                <input v-model="incidentImpact" placeholder="例如 后端启动失败 / 某个接口 500 / 前端连不上" />
              </label>
            </div>
            <button class="primary-button" type="submit" :disabled="incidentLoading || !incidentAlert.trim()">
              {{ incidentLoading ? "分析中..." : "生成处置方案" }}
            </button>
          </form>
        </article>

        <template v-if="latestIncident">
          <article class="decision-card">
            <small>处置结论</small>
            <strong>{{ confidenceLabel(latestIncident.diagnosis.confidence) }}</strong>
            <p>{{ latestIncident.resolution?.headline || latestIncident.diagnosis.primary }}</p>
            <div class="decision-meta">
              <span>证据：{{ latestIncident.diagnosis.evidence_count }}</span>
              <span>服务：{{ latestIncident.resolution?.service || latestIncident.signals.service || "未知" }}</span>
            </div>
          </article>

          <article class="context-card">
            <h3>证据充分性</h3>
            <div class="metric-grid">
              <div>
                <small>判断</small>
                <strong>{{ latestIncident.resolution?.evidence_state || evidenceQuality }}</strong>
              </div>
              <div>
                <small>日志</small>
                <strong>{{ latestIncident.resolution?.evidence_counts?.logs || 0 }} 条</strong>
              </div>
              <div>
                <small>代码</small>
                <strong>{{ latestIncident.resolution?.evidence_counts?.code || 0 }} 条</strong>
              </div>
              <div>
                <small>安全门</small>
                <strong>{{ latestIncident.diagnosis.needs_human_confirmation ? "危险动作需确认" : "只读" }}</strong>
              </div>
            </div>
          </article>

          <article class="wide-card">
            <div class="section-head">
              <h3>下一步检查清单</h3>
              <span>按顺序处理</span>
            </div>
            <div class="checklist-grid">
              <div v-for="(check, index) in latestIncident.next_checks || []" :key="check.title" class="check-card">
                <small>Step {{ index + 1 }}</small>
                <strong>{{ check.title }}</strong>
                <p>{{ check.detail }}</p>
                <span>{{ check.target }}</span>
              </div>
            </div>
          </article>

          <article class="wide-card">
            <div class="section-head">
              <h3>证据摘要</h3>
              <span>只展示和处置有关的证据</span>
            </div>
            <div class="evidence-grid">
              <div v-for="item in evidenceCards" :key="item.title" class="evidence-card">
                <small>{{ item.type }}</small>
                <strong>{{ item.title }}</strong>
                <p>{{ item.summary }}</p>
              </div>
            </div>
            <p v-if="!evidenceCards.length" class="empty-note">
              当前没有命中真实日志或代码证据。建议导入包含 logs 目录的项目，或把报错堆栈保存为 .log/.jsonl 后重新运行。
            </p>
          </article>

          <article class="wide-card">
            <details>
              <summary>技术细节：Runbook / 多 Agent / MCP 调用</summary>
              <div class="technical-stack">
                <section>
                  <h4>Runbook 计划</h4>
                  <div v-for="step in latestIncident.plan" :key="step.step" class="history-row">
                    <strong>{{ step.step }}</strong>
                    <span>{{ step.why }} · {{ step.tool }}</span>
                  </div>
                </section>
                <section>
                  <h4>Agent 链路</h4>
                  <div v-for="agent in latestIncident.agent_runs || []" :key="agent.agent" class="history-row">
                    <strong>{{ agent.agent }} · {{ agentLabel(agent.agent) }}</strong>
                    <span>{{ agent.summary }}</span>
                  </div>
                </section>
              </div>
              <pre>{{ JSON.stringify(latestIncident.mcp_calls, null, 2) }}</pre>
            </details>
          </article>

          <article class="wide-card">
            <details>
              <summary>排障报告 Markdown</summary>
              <pre>{{ latestIncident.report }}</pre>
            </details>
          </article>
        </template>
      </section>

      <section v-else class="empty-panel">
        <strong>先导入一个真实项目目录。</strong>
        <span>导入后，Agent 才能通过 MCP 工具读取项目上下文并排障。</span>
      </section>
    </section>
  </main>
</template>

<script setup>
import axios from "axios";
import { computed, onMounted, ref } from "vue";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

const activeTab = ref("deal");
const backendOk = ref(false);

const dealQuery = ref("我想买一个 1000 元以内适合写代码的显示器，帮我研究值不值得买");
const dealLoading = ref(false);
const dealRuns = ref([]);

const opsProjectName = ref("Jerry Insight Pro");
const opsProjectPath = ref("C:\\Users\\Jerry\\Desktop\\AIstudy\\Jerry-Insight-Pro");
const opsImporting = ref(false);
const opsImportError = ref("");
const opsProjects = ref([]);
const incidentType = ref("api_error");
const incidentService = ref("fullstack_agent/backend");
const incidentErrorLog = ref("ImportError: cannot import name ...\n或粘贴 uvicorn 终端里的完整 traceback");
const incidentRecentChange = ref("刚修改了后端 import / requirements / 启动路径");
const incidentImpact = ref("后端接口报错，前端显示后端未连接或请求失败");
const incidentLoading = ref(false);
const incidentRuns = ref([]);
const mcpTools = ref([]);

const latestDealRun = computed(() => dealRuns.value[0] || null);
const currentProject = computed(() => opsProjects.value[0] || null);
const latestIncident = computed(() => incidentRuns.value[0] || null);
const incidentAlert = computed(() =>
  [incidentType.value, incidentService.value, incidentErrorLog.value, incidentRecentChange.value, incidentImpact.value]
    .filter(Boolean)
    .join("\n")
);

const sourceRows = computed(() => {
  const legacy = latestDealRun.value?.legacy_audit;
  if (!legacy) return [];
  const priceRows = (legacy.price_table || []).map((row) => ({
    type: row.platform || "平台价格来源",
    priceText: row.price_text || "",
    info: row.info || "点击链接核实实时价格",
    domain: row.domain || "",
    url: row.url || "",
  }));
  const crawlerRows = (legacy.crawler_sources || []).map((row) => ({
    type: row.platform || "搜索补充来源",
    priceText: row.price_text || "",
    info: row.info || "优惠线索",
    domain: row.domain || "",
    url: row.url || "",
  }));
  return [...priceRows, ...crawlerRows];
});

const evidenceCards = computed(() => {
  const run = latestIncident.value;
  if (!run) return [];
  const cards = [];
  for (const item of run.evidence.logs.slice(0, 4)) {
    cards.push({ type: "log", title: `${item.file}:${item.line}`, summary: item.snippet });
  }
  for (const item of run.evidence.code.slice(0, 4)) {
    cards.push({ type: "code", title: `${item.file}:${item.line}`, summary: item.snippet });
  }
  for (const item of run.evidence.configs.slice(0, 4)) {
    cards.push({ type: "config", title: item.file, summary: (item.signals || []).join(", ") || "配置文件" });
  }
  for (const item of run.evidence.runbooks.slice(0, 2)) {
    cards.push({ type: "runbook", title: item.file, summary: item.snippet });
  }
  return cards;
});

const evidenceQuality = computed(() => {
  const run = latestIncident.value;
  if (!run) return "-";
  const logs = run.evidence.logs?.length || 0;
  const code = run.evidence.code?.length || 0;
  if (logs && code) return "日志+代码";
  if (logs) return "仅日志";
  if (code) return "仅代码";
  return "缺少运行证据";
});

function formatMoney(value) {
  if (value === "" || value === null || value === undefined) return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return "-";
  return `${num.toFixed(2)} 元`;
}

function roleLabel(owner) {
  const labels = {
    "Price Researcher": "价格研究员",
    "Risk Researcher": "风险研究员",
    "Alternative Researcher": "替代品研究员",
    "Personal Context Agent": "个人上下文 Agent",
  };
  return labels[owner] || "研究员";
}

function categoryLabel(category) {
  const labels = {
    price: "价格",
    deal: "优惠",
    risk: "风险",
    fallback: "降级",
  };
  return labels[category] || category;
}

function confidenceLabel(confidence) {
  const labels = {
    high: "高可信",
    medium: "中可信",
    low: "低可信",
  };
  return labels[confidence] || confidence;
}

function agentLabel(agent) {
  const labels = {
    "Price Research Agent": "价格研究",
    "Risk Evidence Agent": "风险证据",
    "Personal Finance Agent": "个人财务",
    "Decision Agent": "决策融合",
    "Project Mapper Agent": "项目建图",
    "Runbook Agent": "预案检索",
    "Log Investigator Agent": "日志调查",
    "Code Investigator Agent": "代码调查",
    "Diagnosis Agent": "根因诊断",
  };
  return labels[agent] || "Agent";
}

async function checkBackend() {
  try {
    const res = await axios.get(`${API_BASE}/api/health`);
    backendOk.value = res.data.status === "ok";
  } catch (err) {
    backendOk.value = false;
  }
}

async function loadMcpTools() {
  try {
    const res = await axios.get(`${API_BASE}/api/mcp/tools`);
    mcpTools.value = res.data.tools || [];
  } catch (err) {
    mcpTools.value = [];
  }
}

async function loadDealRuns() {
  try {
    const res = await axios.get(`${API_BASE}/api/deal-research/runs`);
    dealRuns.value = res.data.items || [];
  } catch (err) {
    dealRuns.value = [];
  }
}

async function loadOpsProjects() {
  try {
    const res = await axios.get(`${API_BASE}/api/project-ops/projects`);
    opsProjects.value = res.data.items || [];
  } catch (err) {
    opsProjects.value = [];
  }
}

async function loadIncidentRuns() {
  try {
    const res = await axios.get(`${API_BASE}/api/project-ops/incidents`);
    incidentRuns.value = res.data.items || [];
  } catch (err) {
    incidentRuns.value = [];
  }
}

async function runDealResearch() {
  if (!dealQuery.value.trim() || dealLoading.value) return;
  dealLoading.value = true;
  try {
    const res = await axios.post(`${API_BASE}/api/deal-research/run`, { query: dealQuery.value });
    dealRuns.value = [res.data, ...dealRuns.value.filter((item) => item.run_id !== res.data.run_id)];
    await checkBackend();
  } finally {
    dealLoading.value = false;
  }
}

async function confirmDealPurchase() {
  const run = latestDealRun.value;
  if (!run) return;
  const suggested = run.decision.estimated_price || run.legacy_audit?.estimated_price || 15;
  const amountText = window.prompt(`请输入「${run.product}」实际记账金额`, suggested);
  const amount = Number(amountText);
  if (!amount || amount <= 0) return;
  await axios.post(`${API_BASE}/api/confirm-purchase`, {
    item: run.product,
    amount,
    raw_query: run.query,
  });
  await checkBackend();
}

async function skipDealPurchase() {
  const run = latestDealRun.value;
  if (!run) return;
  await axios.post(`${API_BASE}/api/skip-purchase`, {
    item: run.product,
    reason: "用户在 Deal Research 后选择放弃购买",
    raw_query: run.query,
  });
}

async function importOpsProject() {
  if (!opsProjectPath.value.trim() || opsImporting.value) return;
  opsImporting.value = true;
  opsImportError.value = "";
  try {
    const res = await axios.post(`${API_BASE}/api/project-ops/import`, {
      name: opsProjectName.value,
      project_path: opsProjectPath.value,
    });
    opsProjects.value = [res.data, ...opsProjects.value.filter((item) => item.project_id !== res.data.project_id)];
    activeTab.value = "ops";
  } catch (err) {
    opsImportError.value = err.response?.data?.detail || "导入失败，请确认路径是本机存在的项目文件夹。";
  } finally {
    opsImporting.value = false;
  }
}

async function runIncident() {
  const project = currentProject.value;
  if (!project || !incidentAlert.value.trim() || incidentLoading.value) return;
  incidentLoading.value = true;
  try {
    const res = await axios.post(`${API_BASE}/api/project-ops/incident`, {
      project_id: project.project_id,
      incident_type: incidentType.value,
      service: incidentService.value,
      error_log: incidentErrorLog.value,
      recent_change: incidentRecentChange.value,
      impact: incidentImpact.value,
      alert: incidentAlert.value,
    });
    incidentRuns.value = [res.data, ...incidentRuns.value.filter((item) => item.run_id !== res.data.run_id)];
  } finally {
    incidentLoading.value = false;
  }
}

onMounted(async () => {
  await checkBackend();
  await Promise.all([loadMcpTools(), loadDealRuns(), loadOpsProjects(), loadIncidentRuns()]);
});
</script>
