<template>
  <main class="app-shell">
    <section class="top-bar">
      <div>
        <p class="eyebrow">AgentForge Lab</p>
        <h1>开源 Agent 项目研究工作台</h1>
      </div>
      <div class="backend-pill" :class="{ online: backendOk }">
        <span></span>
        <strong>{{ backendOk ? "后端已连接" : "后端未连接" }}</strong>
      </div>
    </section>

    <section class="lifeops-workspace">
      <section class="lifeops-hero">
        <div>
          <p class="eyebrow">Event-driven Agent Runtime</p>
          <h2>AgentForge Lab</h2>
          <p>
            研究优质开源 Agent 项目，提取它们真正值得学的机制，再映射到 Jerry 自己的项目里。
            这里不是聊天入口，而是 Agent 项目研究工作台。
          </p>
        </div>
        <button class="primary-button" type="button" :disabled="lifeopsLoading" @click="runLifeOps">
          {{ lifeopsLoading ? "研究中" : "开始研究" }}
        </button>
      </section>

      <section class="lifeops-main-grid">
        <section class="lifeops-left">
          <section class="lifeops-card event-card">
            <header class="side-header">
              <h2>研究对象</h2>
              <button class="text-button" type="button" @click="loadLifeOpsSpec">刷新</button>
            </header>
            <div class="event-list compact-events">
              <button
                v-for="event in lifeopsSpec.event_types"
                :key="event.id"
                type="button"
                :class="{ active: selectedLifeOpsEvent === event.id }"
                @click="selectLifeOpsEvent(event)"
              >
                <strong>{{ event.name }}</strong>
                <span>{{ event.description }}</span>
              </button>
            </div>
          </section>

          <section class="lifeops-card goal-card">
            <header class="side-header">
              <h2>研究目标</h2>
            </header>
            <textarea v-model="lifeopsGoal" rows="6" placeholder="描述你想研究的 Agent 项目机制，以及希望怎么结合到自己的项目"></textarea>
            <div class="toolset-strip">
              <span v-for="toolset in lifeopsSpec.toolsets" :key="toolset.name">
                {{ toolset.name }}
              </span>
            </div>
          </section>

          <section class="lifeops-card runbook-card">
            <header class="side-header">
              <h2>Runbook</h2>
              <span>{{ currentRunbook.length }} steps</span>
            </header>
            <ol class="runbook-list compact-runbook">
              <li v-for="step in currentRunbook" :key="step.name">
                <strong>{{ step.name }}</strong>
                <span>{{ step.description }}</span>
                <code>{{ step.toolset.join(" / ") }}</code>
              </li>
            </ol>
          </section>
        </section>

        <section class="lifeops-right">
          <section v-if="latestLifeOpsRun" class="lifeops-card latest-result">
            <header class="side-header">
              <h2>研究结果</h2>
              <span>{{ latestLifeOpsRun.run_id }}</span>
            </header>

            <section class="plain-report focus-report">
              <div class="plain-head">
                <span>这次研究的是</span>
                <strong>{{ latestLifeOpsRun.sections.project_name }}</strong>
                <p>{{ latestLifeOpsRun.sections.one_liner }}</p>
              </div>

              <div class="focus-grid">
                <div class="focus-card primary">
                  <small>它到底强在哪</small>
                  <strong>{{ latestLifeOpsRun.sections.core_mechanism }}</strong>
                </div>
                <div class="focus-card">
                  <small>我项目可以怎么用</small>
                  <strong>{{ latestLifeOpsRun.sections.fit_for_jerry }}</strong>
                </div>
                <div class="focus-card">
                  <small>当前产物是什么</small>
                  <strong>一份面向 Jerry-Insight 的开源 Agent 机制研究卡片。</strong>
                </div>
              </div>

              <div class="plain-block highlight">
                <h3>先看这里：可借鉴点</h3>
                <ul>
                  <li v-for="point in latestLifeOpsRun.sections.borrowable_points" :key="point">
                    {{ point }}
                  </li>
                </ul>
              </div>
              <div class="plain-block">
                <h3>可以落到我项目里的改动</h3>
                <ul>
                  <li v-for="target in latestLifeOpsRun.sections.implementation_targets" :key="target">
                    {{ target }}
                  </li>
                </ul>
              </div>
              <div class="plain-block">
                <h3>面试官可能追问</h3>
                <ul>
                  <li v-for="question in latestLifeOpsRun.sections.interview_questions" :key="question">
                    {{ question }}
                  </li>
                </ul>
              </div>
            </section>

            <details class="technical-details">
              <summary>技术细节：Runbook / Memory / Safety（面试展开讲，不是主内容）</summary>
              <div class="latest-columns">
                <section>
                  <h3>Runbook Trace</h3>
                  <div v-for="step in latestLifeOpsRun.step_results" :key="`latest-${step.step}`" class="mini-block trace-step">
                    <strong>{{ step.step }}</strong>
                    <span>{{ step.finding }}</span>
                    <div class="tool-chip-row">
                      <span v-for="call in step.tool_calls" :key="`latest-${step.step}-${call.tool}`">{{ call.tool }}</span>
                    </div>
                  </div>
                </section>
                <section>
                  <h3>Safety Gate</h3>
                  <div class="mini-block">
                    <strong>{{ latestLifeOpsRun.safety.requires_human ? "需要人工确认" : "无需人工确认" }}</strong>
                    <span>{{ latestLifeOpsRun.safety.reason }}</span>
                  </div>
                  <h3>Memory</h3>
                  <div v-for="layer in latestLifeOpsRun.memory" :key="`latest-${layer.name}`" class="mini-block">
                    <strong>{{ layer.name }}</strong>
                    <span>{{ layer.items.length }} items</span>
                  </div>
                </section>
              </div>
            </details>

            <details class="report-box latest-report">
              <summary>查看 Markdown 原文</summary>
              <pre>{{ latestLifeOpsRun.report }}</pre>
            </details>
          </section>

          <section v-else class="lifeops-card latest-result empty-latest">
            <h2>等待研究</h2>
            <p>选择一个开源 Agent 项目，填写研究目标，点击右上角“开始研究”。结果会直接显示在这里。</p>
          </section>
        </section>
      </section>

      <section class="lifeops-runs">
        <header class="panel-header">
          <div>
            <h2>Research Runs</h2>
            <p>每次研究都会展示核心机制、可借鉴点、memory evidence、runbook trace 和面试追问。</p>
          </div>
          <button class="icon-button" type="button" title="刷新运行记录" @click="loadLifeOpsRuns">↻</button>
        </header>

        <article v-for="run in lifeopsRuns.slice(1)" :key="run.run_id" class="lifeops-run">
          <div class="run-title">
            <div>
              <strong>{{ run.title }}</strong>
              <span>{{ run.run_id }} · {{ run.status }} · {{ run.created_at }}</span>
            </div>
            <span class="risk-pill" :class="run.safety.level">{{ run.safety.level }}</span>
          </div>

          <section class="summary-card">
            <div>
              <small>事件状态</small>
              <strong>{{ run.summary.status_label }}</strong>
            </div>
            <div>
              <small>可信度</small>
              <strong>{{ run.summary.confidence }}</strong>
            </div>
            <div>
              <small>证据数量</small>
              <strong>{{ run.summary.evidence_count }}</strong>
            </div>
            <div class="summary-wide">
              <small>结论</small>
              <strong>{{ run.summary.conclusion }}</strong>
            </div>
            <div class="summary-wide">
              <small>推荐下一步</small>
              <strong>{{ run.summary.recommended_action }}</strong>
            </div>
          </section>

          <div class="run-columns">
            <section>
              <h3>Memory Layers</h3>
              <div v-for="layer in run.memory" :key="layer.name" class="mini-block">
                <strong>{{ layer.name }}</strong>
                <span>{{ layer.role }}</span>
                <small>{{ layer.items.length }} items</small>
              </div>
            </section>

            <section>
              <h3>Runbook Trace</h3>
              <div v-for="step in run.step_results" :key="`${run.run_id}-${step.step}`" class="mini-block trace-step">
                <strong>{{ step.step }}</strong>
                <span>{{ step.finding }}</span>
                <small>{{ step.description }}</small>
                <div class="tool-chip-row">
                  <span v-for="call in step.tool_calls" :key="`${step.step}-${call.tool}`">
                    {{ call.tool }}
                  </span>
                </div>
              </div>
            </section>

            <section>
              <h3>Safety Gate</h3>
              <div class="mini-block">
                <strong>{{ run.safety.requires_human ? "需要人工确认" : "无需人工确认" }}</strong>
                <span>{{ run.safety.reason }}</span>
                <small v-if="run.safety.blocked_actions.length">
                  blocked: {{ run.safety.blocked_actions.join(", ") }}
                </small>
              </div>
            </section>
          </div>

          <details class="report-box" open>
            <summary>处置报告</summary>
            <pre>{{ run.report }}</pre>
          </details>
        </article>

        <p v-if="lifeopsRuns.length <= 1" class="empty-note">暂无更多历史研究记录。</p>
      </section>
    </section>

    <section v-if="false" class="workspace">
      <section class="chat-panel">
        <header class="panel-header">
          <div>
            <h2>Agent 对话</h2>
            <p>问商品、直接记账、改账、撤销都从这里输入。</p>
          </div>
          <button class="icon-button" type="button" title="刷新数据" @click="refreshAll">↻</button>
        </header>

        <div class="messages" ref="messageBox">
          <article v-for="message in messages" :key="message.id" class="message" :class="message.role">
            <span class="message-role">{{ message.role === "user" ? "你" : "Agent" }}</span>
            <p v-if="message.role === 'user' || message.intent !== 'shopping_audit'" class="message-text">
              {{ message.content }}
            </p>

            <section v-if="message.payload && message.intent === 'shopping_audit'" class="audit-result">
              <div class="audit-summary">
                <div>
                  <small>商品</small>
                  <strong>{{ message.payload.item || "-" }}</strong>
                </div>
                <div>
                  <small>估算单价</small>
                  <strong>{{ formatMoney(message.payload.price) }}</strong>
                </div>
                <div>
                  <small>搜索来源</small>
                  <strong>{{ message.payload.search_sources?.length || 0 }} 条</strong>
                </div>
                <div>
                  <small>比价线索</small>
                  <strong>{{ priceRows(message.payload).length }} 条</strong>
                </div>
              </div>

              <div class="detail-section">
                <h3>网址与情报来源</h3>
                <ul v-if="message.payload.search_sources?.length" class="source-list">
                  <li v-for="(source, index) in message.payload.search_sources" :key="`s-${index}`">
                    <div>
                      <strong>来源 {{ index + 1 }}<template v-if="source.score"> · 匹配 {{ source.score }}</template></strong>
                      <p>{{ source.summary }}</p>
                    </div>
                    <a v-if="source.url" :href="source.url" target="_blank" rel="noreferrer">打开</a>
                  </li>
                </ul>
                <p v-else class="empty-note">这次没有拿到可展示的网址来源。</p>
              </div>

              <div class="detail-section">
                <h3>比价与价格线索</h3>
                <div v-if="priceRows(message.payload).length" class="data-table">
                  <div class="table-row table-head">
                    <span>平台</span>
                    <span>说明</span>
                    <span>链接</span>
                  </div>
                  <div v-for="(row, index) in priceRows(message.payload)" :key="`p-${index}`" class="table-row">
                    <span>{{ row.platform || "价格来源" }}</span>
                    <span>{{ row.info || "-" }}</span>
                    <a v-if="row.url" :href="row.url" target="_blank" rel="noreferrer">打开</a>
                    <span v-else>-</span>
                  </div>
                </div>
                <p v-else class="empty-note">这次没有拿到可展示的比价线索。</p>
              </div>

              <div class="detail-section advice-section">
                <h3>购买建议</h3>
                <p>{{ message.payload.display_answer || message.content }}</p>
              </div>

              <div class="action-row">
                <button class="primary-button" type="button" @click="confirmPurchase(message)">确认购入并记账</button>
                <button class="secondary-button" type="button" @click="skipPurchase(message)">放弃购买</button>
              </div>
            </section>
          </article>

          <div v-if="messages.length === 0" class="empty-state">
            <strong>试试输入：我想买东方树叶</strong>
            <span>也可以输入：买了雪碧花了3块 / 撤销上一条 / 加回来3块</span>
          </div>
        </div>

        <form class="composer" @submit.prevent="sendMessage">
          <input
            v-model="input"
            :disabled="loading"
            placeholder="输入：我想买可乐 / 买了雪碧花了3块 / 撤销上一条"
          />
          <button type="submit" :disabled="loading || !input.trim()">
            {{ loading ? "处理中" : "发送" }}
          </button>
        </form>
      </section>

      <aside class="side-panel">
        <section class="side-card">
          <div class="status-line">
            <span>{{ backendMessage }}</span>
          </div>
          <div class="metric-grid">
            <div>
              <small>当前余额</small>
              <strong>{{ formatMoney(currentSurplus) }}</strong>
            </div>
            <div>
              <small>最近意图</small>
              <strong>{{ latestIntent || "-" }}</strong>
            </div>
            <div>
              <small>总耗时</small>
              <strong>{{ latestLatency ? `${latestLatency} ms` : "-" }}</strong>
            </div>
            <div>
              <small>阶段数</small>
              <strong>{{ latestTrace?.stages?.length || 0 }}</strong>
            </div>
          </div>
          <div v-if="latestTrace?.stages?.length" class="trace-list">
            <div v-for="stage in latestTrace.stages" :key="stage.name + stage.latency_ms">
              <span>{{ stage.name }}</span>
              <strong>{{ stage.latency_ms }} ms</strong>
            </div>
          </div>
        </section>

        <section class="side-card">
          <header class="side-header">
            <h2>直接记账 / 改账</h2>
            <button class="text-button" type="button" @click="undoLedger">撤销</button>
          </header>
          <div class="ledger-form">
            <input v-model="ledgerItem" placeholder="商品，例如 雪碧" />
            <input v-model="ledgerAmount" type="number" min="0" step="0.01" placeholder="金额" />
            <div class="form-actions">
              <button class="primary-button" type="button" @click="quickRecord">扣钱记账</button>
              <button class="secondary-button" type="button" @click="quickRefund">加回余额</button>
            </div>
          </div>
        </section>

        <section class="side-card">
          <header class="side-header">
            <h2>历史记录</h2>
            <button class="text-button" type="button" @click="clearHistory">清空</button>
          </header>
          <ul class="compact-list">
            <li v-for="item in history" :key="item.id" @click="input = item.user_message">
              <strong>{{ item.user_message }}</strong>
              <span>{{ item.intent }} · {{ item.latency_ms }} ms</span>
            </li>
          </ul>
          <p v-if="history.length === 0" class="empty-note">暂无历史</p>
        </section>

        <section class="side-card">
          <header class="side-header">
            <h2>购入物品</h2>
            <button class="text-button" type="button" @click="loadLedger">刷新</button>
          </header>
          <ul class="compact-list">
            <li v-for="item in purchasedItems" :key="`purchased-${item.id}`">
              <strong>{{ item.item }} · {{ formatMoney(item.amount) }}</strong>
              <span>{{ item.created_at }} · {{ item.status }}</span>
            </li>
          </ul>
          <p v-if="purchasedItems.length === 0" class="empty-note">暂无购入记录</p>
        </section>

        <section class="side-card">
          <header class="side-header">
            <h2>拦截 / 放弃</h2>
          </header>
          <ul class="compact-list">
            <li v-for="item in blockedItems" :key="item.id">
              <strong>{{ item.item }}</strong>
              <span>{{ item.created_at }} · {{ item.reason }}</span>
            </li>
          </ul>
          <p v-if="blockedItems.length === 0" class="empty-note">暂无拦截记录</p>
        </section>
      </aside>
    </section>
  </main>
</template>

<script setup>
import axios from "axios";
import { computed, nextTick, onMounted, ref } from "vue";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

const input = ref("");
const loading = ref(false);
const backendOk = ref(false);
const backendMessage = ref("正在检查后端服务");
const messages = ref([]);
const history = ref([]);
const ledger = ref([]);
const blockedItems = ref([]);
const latestIntent = ref("");
const latestLatency = ref("");
const latestTrace = ref(null);
const currentSurplus = ref("");
const messageBox = ref(null);
const ledgerItem = ref("");
const ledgerAmount = ref("");
const AGENTFORGE_FALLBACK_SPEC = {
  event_types: [
    {
      id: "gpt_researcher",
      name: "GPT-Researcher",
      description: "研究 planner / executor / publisher，以及 citation 和报告质量。",
      example: "研究 GPT-Researcher 的核心机制，看看哪些点能借鉴到我的项目里。",
    },
    {
      id: "letta",
      name: "Letta / MemGPT",
      description: "研究三层 memory architecture：core、recall、archival。",
      example: "研究 Letta 的记忆系统，看看怎么用于我的面试准备和项目复盘。",
    },
    {
      id: "holmesgpt",
      name: "HolmesGPT",
      description: "研究 AIOps agent 的 runbook、toolset、权限安全和 fallback。",
      example: "研究 HolmesGPT 的 runbook 和 toolset 设计，看看我的项目能怎么借鉴。",
    },
    {
      id: "aider",
      name: "Aider",
      description: "研究 repo map、代码上下文筛选和 Git undo 机制。",
      example: "研究 Aider 的 repo map，看看能不能做我的项目资料 map。",
    },
  ],
  toolsets: [
    { name: "project_profile_toolset" },
    { name: "local_context_toolset" },
    { name: "adaptation_toolset" },
    { name: "report_toolset" },
  ],
  runbooks: {
    gpt_researcher: [
      { name: "load_profile", description: "读取开源项目的定位、核心机制和典型追问。", toolset: ["project_profile_toolset"] },
      { name: "read_my_context", description: "读取我的项目/笔记上下文，找到可以映射的地方。", toolset: ["local_context_toolset"] },
      { name: "extract_borrowable_points", description: "提取可借鉴点，避免写成生硬二改方案。", toolset: ["adaptation_toolset"] },
      { name: "publish_report", description: "生成研究报告、面试追问和结合建议。", toolset: ["report_toolset"] },
    ],
    letta: [
      { name: "load_profile", description: "读取开源项目的定位、核心机制和典型追问。", toolset: ["project_profile_toolset"] },
      { name: "read_my_context", description: "读取我的项目/笔记上下文，找到可以映射的地方。", toolset: ["local_context_toolset"] },
      { name: "extract_borrowable_points", description: "提取可借鉴点，避免写成生硬二改方案。", toolset: ["adaptation_toolset"] },
      { name: "publish_report", description: "生成研究报告、面试追问和结合建议。", toolset: ["report_toolset"] },
    ],
    holmesgpt: [
      { name: "load_profile", description: "读取开源项目的定位、核心机制和典型追问。", toolset: ["project_profile_toolset"] },
      { name: "read_my_context", description: "读取我的项目/笔记上下文，找到可以映射的地方。", toolset: ["local_context_toolset"] },
      { name: "extract_borrowable_points", description: "提取可借鉴点，避免写成生硬二改方案。", toolset: ["adaptation_toolset"] },
      { name: "publish_report", description: "生成研究报告、面试追问和结合建议。", toolset: ["report_toolset"] },
    ],
    aider: [
      { name: "load_profile", description: "读取开源项目的定位、核心机制和典型追问。", toolset: ["project_profile_toolset"] },
      { name: "read_my_context", description: "读取我的项目/笔记上下文，找到可以映射的地方。", toolset: ["local_context_toolset"] },
      { name: "extract_borrowable_points", description: "提取可借鉴点，避免写成生硬二改方案。", toolset: ["adaptation_toolset"] },
      { name: "publish_report", description: "生成研究报告、面试追问和结合建议。", toolset: ["report_toolset"] },
    ],
  },
};

const lifeopsSpec = ref(AGENTFORGE_FALLBACK_SPEC);
const selectedLifeOpsEvent = ref("gpt_researcher");
const lifeopsGoal = ref("研究 GPT-Researcher 的核心机制，看看哪些点能借鉴到我的项目里。");
const lifeopsRuns = ref([]);
const lifeopsLoading = ref(false);

const currentRunbook = computed(() => lifeopsSpec.value.runbooks?.[selectedLifeOpsEvent.value] || []);
const latestLifeOpsRun = computed(() => lifeopsRuns.value[0] || null);

const purchasedItems = computed(() =>
  ledger.value.filter((item) => item.status === "active" && item.amount > 0).slice(0, 12)
);

function formatMoney(value) {
  if (value === "" || value === null || value === undefined) return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return "-";
  return `${num.toFixed(2)} 元`;
}

function priceRows(payload) {
  return [...(payload?.price_table || []), ...(payload?.crawler_sources || [])];
}

async function checkBackend() {
  try {
    const res = await axios.get(`${API_BASE}/api/health`);
    backendOk.value = res.data.status === "ok";
    backendMessage.value = res.data.service || "FastAPI running";
    currentSurplus.value = res.data.current_surplus;
  } catch (err) {
    backendOk.value = false;
    backendMessage.value = "请先启动 FastAPI 后端";
  }
}

async function loadProfile() {
  try {
    const res = await axios.get(`${API_BASE}/api/profile`);
    currentSurplus.value = res.data.current_surplus;
  } catch (err) {
    currentSurplus.value = "";
  }
}

async function loadHistory() {
  try {
    const res = await axios.get(`${API_BASE}/api/history?limit=30`);
    history.value = res.data.items || [];
  } catch (err) {
    history.value = [];
  }
}

async function loadLedger() {
  try {
    const res = await axios.get(`${API_BASE}/api/ledger?limit=40`);
    ledger.value = res.data.items || [];
  } catch (err) {
    ledger.value = [];
  }
}

async function loadBlocked() {
  try {
    const res = await axios.get(`${API_BASE}/api/blocked?limit=30`);
    blockedItems.value = res.data.items || [];
  } catch (err) {
    blockedItems.value = [];
  }
}

async function loadLifeOpsSpec() {
  try {
    const res = await axios.get(`${API_BASE}/api/lifeops/spec`);
    const incoming = res.data || {};
    const ids = (incoming.event_types || []).map((item) => item.id);
    lifeopsSpec.value = ids.includes("gpt_researcher") ? incoming : AGENTFORGE_FALLBACK_SPEC;
    if (!selectedLifeOpsEvent.value && lifeopsSpec.value.event_types?.length) {
      selectLifeOpsEvent(lifeopsSpec.value.event_types[0]);
    }
  } catch (err) {
    lifeopsSpec.value = AGENTFORGE_FALLBACK_SPEC;
  }
}

async function loadLifeOpsRuns() {
  try {
    const res = await axios.get(`${API_BASE}/api/lifeops/runs`);
    lifeopsRuns.value = res.data.items || [];
  } catch (err) {
    lifeopsRuns.value = [];
  }
}

function selectLifeOpsEvent(event) {
  selectedLifeOpsEvent.value = event.id;
  lifeopsGoal.value = event.example || lifeopsGoal.value;
}

async function runLifeOps() {
  if (!lifeopsGoal.value.trim() || lifeopsLoading.value) return;
  lifeopsLoading.value = true;
  try {
    await axios.post(`${API_BASE}/api/lifeops/run`, {
      event_type: selectedLifeOpsEvent.value,
      goal: lifeopsGoal.value,
    });
    await loadLifeOpsRuns();
  } finally {
    lifeopsLoading.value = false;
  }
}

async function clearHistory() {
  await axios.delete(`${API_BASE}/api/history`);
  history.value = [];
}

async function refreshAll() {
  await checkBackend();
  await loadHistory();
  await loadLedger();
  await loadBlocked();
  await loadProfile();
}

async function scrollToBottom() {
  await nextTick();
  if (messageBox.value) {
    messageBox.value.scrollTop = messageBox.value.scrollHeight;
  }
}

async function sendMessage() {
  const message = input.value.trim();
  if (!message || loading.value) return;

  messages.value.push({
    id: `user-${Date.now()}`,
    role: "user",
    content: message,
  });
  input.value = "";
  loading.value = true;
  await scrollToBottom();

  try {
    const res = await axios.post(`${API_BASE}/api/chat`, { message });
    if (res.data.intent === "shopping_audit") {
      latestIntent.value = res.data.intent;
      latestLatency.value = res.data.latency_ms;
      latestTrace.value = res.data.trace;
    } else if (!latestTrace.value) {
      latestIntent.value = res.data.intent;
      latestLatency.value = res.data.latency_ms;
      latestTrace.value = res.data.trace;
    }
    messages.value.push({
      id: `agent-${res.data.id || Date.now()}`,
      role: "assistant",
      content: res.data.reply,
      intent: res.data.intent,
      payload: res.data.payload,
      trace: res.data.trace,
    });
    await refreshAll();
  } catch (err) {
    messages.value.push({
      id: `error-${Date.now()}`,
      role: "assistant",
      content: "请求失败，请确认 FastAPI 后端正在 8000 端口运行。",
      intent: "error",
    });
  } finally {
    loading.value = false;
    await scrollToBottom();
  }
}

async function confirmPurchase(message) {
  const item = message.payload?.item;
  const suggested = message.payload?.price || 15;
  if (!item) return;
  const amountText = window.prompt(`请输入「${item}」实际记账金额`, suggested);
  const amount = Number(amountText);
  if (!amount || amount <= 0) return;
  const res = await axios.post(`${API_BASE}/api/confirm-purchase`, {
    item,
    amount,
    raw_query: item,
  });
  messages.value.push({
    id: `confirm-${Date.now()}`,
    role: "assistant",
    content: `已确认购入：${res.data.item}，扣除 ${res.data.amount} 元。当前余额 ${res.data.current_surplus} 元。`,
    intent: "confirm_purchase",
  });
  await refreshAll();
}

async function skipPurchase(message) {
  const item = message.payload?.item || "该商品";
  await axios.post(`${API_BASE}/api/skip-purchase`, {
    item,
    reason: "用户在审计结果后选择放弃购买",
    raw_query: item,
  });
  messages.value.push({
    id: `skip-${Date.now()}`,
    role: "assistant",
    content: `已放弃购买：${item}。本次未扣除余额。`,
    intent: "skip_purchase",
  });
  await loadBlocked();
}

async function quickRecord() {
  if (!ledgerItem.value.trim() || !Number(ledgerAmount.value)) return;
  input.value = `买了${ledgerItem.value.trim()}花了${ledgerAmount.value}元`;
  await sendMessage();
  ledgerItem.value = "";
  ledgerAmount.value = "";
}

async function quickRefund() {
  if (!Number(ledgerAmount.value)) return;
  const item = ledgerItem.value.trim() || "余额修正";
  input.value = `加回来${item}${ledgerAmount.value}元`;
  await sendMessage();
  ledgerItem.value = "";
  ledgerAmount.value = "";
}

async function undoLedger() {
  input.value = "撤销上一条";
  await sendMessage();
}

onMounted(async () => {
  await refreshAll();
  await loadLifeOpsSpec();
  await loadLifeOpsRuns();
});
</script>
