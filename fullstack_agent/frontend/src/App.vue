<template>
  <main class="app-shell">
    <section class="top-bar">
      <div>
        <p class="eyebrow">Jerry-Insight Agent Pro</p>
        <h1>省钱智探工作台</h1>
      </div>
      <div class="backend-pill" :class="{ online: backendOk }">
        <span></span>
        <strong>{{ backendOk ? "后端已连接" : "后端未连接" }}</strong>
      </div>
    </section>

    <section class="workspace">
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

onMounted(refreshAll);
</script>
