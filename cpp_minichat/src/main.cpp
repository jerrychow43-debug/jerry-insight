#include <algorithm>
#include <arpa/inet.h>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <netinet/in.h>
#include <mutex>
#include <sstream>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>
#include <unordered_map>
#include <vector>

namespace {

volatile std::sig_atomic_t g_running = 1;
const std::string kDataDir = "data";
const std::string kMessagePath = "data/messages.tsv";
std::string g_rpc_host = "127.0.0.1";
uint16_t g_rpc_port = 18888;

struct Message {
    uint64_t id = 0;
    std::string room;
    std::string user;
    std::string to;
    std::string text;
    uint64_t ts = 0;
};

std::vector<Message> g_messages;
std::unordered_map<std::string, uint64_t> g_users;
std::mutex g_state_mu;
uint64_t g_next_id = 1;

void handle_signal(int) { g_running = 0; }

uint64_t now_epoch() {
    return static_cast<uint64_t>(std::chrono::system_clock::to_time_t(std::chrono::system_clock::now()));
}

std::string status_text(int status) {
    if (status == 200) return "OK";
    if (status == 400) return "Bad Request";
    if (status == 404) return "Not Found";
    return "OK";
}

std::string http_response(int status, const std::string& content_type, const std::string& body) {
    std::ostringstream oss;
    oss << "HTTP/1.1 " << status << " " << status_text(status) << "\r\n"
        << "Content-Type: " << content_type << "; charset=utf-8\r\n"
        << "Content-Length: " << body.size() << "\r\n"
        << "Connection: close\r\n"
        << "Access-Control-Allow-Origin: *\r\n"
        << "\r\n"
        << body;
    return oss.str();
}

bool send_all(int fd, const std::string& data) {
    const char* p = data.data();
    size_t left = data.size();
    while (left > 0) {
        ssize_t n = ::send(fd, p, left, MSG_NOSIGNAL);
        if (n < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        if (n == 0) return false;
        p += n;
        left -= static_cast<size_t>(n);
    }
    return true;
}

int hex_value(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

std::string url_decode(const std::string& input) {
    std::string out;
    for (size_t i = 0; i < input.size(); ++i) {
        if (input[i] == '+') out += ' ';
        else if (input[i] == '%' && i + 2 < input.size()) {
            int hi = hex_value(input[i + 1]);
            int lo = hex_value(input[i + 2]);
            if (hi >= 0 && lo >= 0) {
                out += static_cast<char>((hi << 4) | lo);
                i += 2;
            } else out += input[i];
        } else out += input[i];
    }
    return out;
}

std::string query_value(const std::string& target, const std::string& key) {
    size_t q = target.find('?');
    if (q == std::string::npos) return "";
    std::string query = target.substr(q + 1);
    size_t start = 0;
    while (start <= query.size()) {
        size_t amp = query.find('&', start);
        std::string pair = query.substr(start, amp == std::string::npos ? std::string::npos : amp - start);
        size_t eq = pair.find('=');
        if (eq != std::string::npos && url_decode(pair.substr(0, eq)) == key) {
            return url_decode(pair.substr(eq + 1));
        }
        if (amp == std::string::npos) break;
        start = amp + 1;
    }
    return "";
}

std::string json_escape(const std::string& value) {
    std::string out;
    for (char c : value) {
        switch (c) {
            case '\\': out += "\\\\"; break;
            case '"': out += "\\\""; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default: out += c; break;
        }
    }
    return out;
}

std::vector<std::string> split_tsv(const std::string& line) {
    std::vector<std::string> parts;
    size_t start = 0;
    while (start <= line.size()) {
        size_t tab = line.find('\t', start);
        parts.push_back(line.substr(start, tab == std::string::npos ? std::string::npos : tab - start));
        if (tab == std::string::npos) break;
        start = tab + 1;
    }
    return parts;
}

std::vector<std::string> split_space(const std::string& text) {
    std::vector<std::string> parts;
    std::istringstream iss(text);
    std::string part;
    while (iss >> part) parts.push_back(part);
    return parts;
}

std::string rpc_call(const std::string& request) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return "";

    sockaddr_in addr {};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(g_rpc_port);
    if (::inet_pton(AF_INET, g_rpc_host.c_str(), &addr.sin_addr) != 1) {
        ::close(fd);
        return "";
    }
    if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        ::close(fd);
        return "";
    }

    if (!send_all(fd, request + "\n")) {
        ::close(fd);
        return "";
    }

    std::string line;
    char c = 0;
    while (line.size() < 4096) {
        ssize_t n = ::recv(fd, &c, 1, 0);
        if (n < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (n == 0 || c == '\n') break;
        if (c != '\r') line.push_back(c);
    }
    ::close(fd);
    return line;
}

bool rpc_whoami(const std::string& token, std::string& username, std::string& nickname) {
    if (token.empty()) return false;
    std::string response = rpc_call("whoami " + token);
    auto parts = split_space(response);
    if (parts.size() < 4 || parts[0] != "OK" || parts[1] != "me") return false;
    username = parts[2];
    nickname = parts[3];
    return true;
}

bool resolve_request_user(const std::string& target, std::string& user, std::string& error) {
    std::string token = query_value(target, "token");
    if (token.empty()) {
        error = "login required";
        return false;
    }
    std::string nickname;
    if (!rpc_whoami(token, user, nickname)) {
        error = "invalid token or rpc user service unavailable";
        return false;
    }
    return true;
}

std::string message_json(const Message& msg) {
    return "{\"id\":" + std::to_string(msg.id) + ","
           "\"room\":\"" + json_escape(msg.room) + "\","
           "\"user\":\"" + json_escape(msg.user) + "\","
           "\"to\":\"" + json_escape(msg.to) + "\","
           "\"text\":\"" + json_escape(msg.text) + "\","
           "\"ts\":" + std::to_string(msg.ts) + "}";
}

bool can_view_message(const Message& msg, const std::string& room, const std::string& user) {
    if (msg.room != room) return false;
    if (msg.to.empty()) return true;
    return msg.user == user || msg.to == user;
}

void load_messages() {
    std::ifstream in(kMessagePath);
    if (!in.is_open()) return;
    std::string line;
    while (std::getline(in, line)) {
        auto parts = split_tsv(line);
        if (parts.size() < 4) continue;
        Message msg;
        msg.id = static_cast<uint64_t>(std::stoull(parts[0]));
        if (parts.size() >= 6) {
            msg.room = parts[1];
            msg.user = parts[2];
            msg.to = parts[3];
            msg.ts = static_cast<uint64_t>(std::stoull(parts[4]));
            msg.text = parts[5];
        } else if (parts.size() >= 5) {
            msg.room = parts[1];
            msg.user = parts[2];
            msg.ts = static_cast<uint64_t>(std::stoull(parts[3]));
            msg.text = parts[4];
        } else {
            msg.room = "general";
            msg.user = parts[1];
            msg.ts = static_cast<uint64_t>(std::stoull(parts[2]));
            msg.text = parts[3];
        }
        g_messages.push_back(msg);
        g_next_id = std::max(g_next_id, msg.id + 1);
    }
    if (!g_messages.empty()) std::cout << "loaded " << g_messages.size() << " messages\n";
}

void write_message_line(std::ofstream& out, const Message& msg) {
    out << msg.id << '\t' << msg.room << '\t' << msg.user << '\t' << msg.to << '\t' << msg.ts << '\t' << msg.text << '\n';
}

void append_message(const Message& msg) {
    std::filesystem::create_directories(kDataDir);
    std::ofstream out(kMessagePath, std::ios::app);
    write_message_line(out, msg);
}

void rewrite_messages_locked() {
    std::filesystem::create_directories(kDataDir);
    std::ofstream out(kMessagePath, std::ios::trunc);
    for (const auto& msg : g_messages) write_message_line(out, msg);
}

std::string html_page() {
    return R"HTML(<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MiniChat</title>
<style>
body { margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f7fb; color: #1f2937; }
main { max-width: 980px; margin: 38px auto; padding: 0 20px; }
h1 { margin: 0 0 8px; font-size: 34px; }
.sub { color: #667085; margin-bottom: 22px; }
.auth { display: grid; grid-template-columns: 1fr 1fr 1fr auto auto auto; gap: 10px; margin-bottom: 16px; }
.auth input { min-width: 0; }
.authmsg { color: #667085; font-size: 13px; margin: -6px 0 16px; min-height: 18px; }
.authmsg.err { color: #b42318; }
.authmsg.ok { color: #027a48; }
.layout { display: grid; grid-template-columns: 1fr 240px; gap: 16px; }
.panel { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; box-shadow: 0 8px 24px rgba(15,23,42,.06); }
.chat { height: 520px; display: flex; flex-direction: column; }
.messages { flex: 1; overflow: auto; padding: 18px; }
.msg { margin-bottom: 12px; }
.msg.own { text-align: right; }
.meta { color: #667085; font-size: 13px; margin-bottom: 4px; }
.bubble { display: inline-block; background: #eef2ff; border: 1px solid #c7d2fe; color: #1e1b4b; padding: 9px 11px; border-radius: 8px; max-width: 78%; white-space: pre-wrap; text-align: left; }
.msg.own .bubble { background: #dcfce7; border-color: #86efac; color: #064e3b; }
.form { border-top: 1px solid #e5e7eb; padding: 14px; display: grid; grid-template-columns: 110px 130px 130px 1fr auto; gap: 10px; }
input { padding: 10px 12px; border: 1px solid #d0d5dd; border-radius: 6px; font-size: 15px; }
button { padding: 10px 14px; border: 0; border-radius: 6px; background: #2563eb; color: #fff; font-weight: 700; cursor: pointer; }
.side { padding: 16px; }
.user { background: #ecfdf3; color: #027a48; padding: 7px 9px; border-radius: 999px; margin: 0 6px 8px 0; display: inline-block; font-size: 13px; cursor: pointer; }
.room { background: #eef2ff; color: #3730a3; padding: 7px 9px; border-radius: 999px; margin: 0 6px 8px 0; display: inline-block; font-size: 13px; cursor: pointer; }
.identity { background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px; margin: 4px 0 18px; color: #475467; font-size: 14px; }
.identity strong { color: #111827; }
.status { display: inline-block; margin-top: 8px; padding: 5px 8px; border-radius: 999px; background: #fef3c7; color: #92400e; font-size: 12px; }
.status.on { background: #dcfce7; color: #166534; }
.status.off { background: #fee2e2; color: #991b1b; }
.tools { display: grid; grid-template-columns: 1fr; gap: 8px; margin-bottom: 18px; }
.danger { background: #dc2626; }
.search { display: grid; grid-template-columns: 1fr auto; gap: 8px; margin-bottom: 10px; }
.search input { min-width: 0; }
.search button { padding: 9px 10px; }
.result { border: 1px solid #e5e7eb; border-radius: 8px; padding: 9px 10px; margin-bottom: 8px; background: #f8fafc; font-size: 13px; }
.result .meta { margin-bottom: 4px; }
.result .text { color: #111827; line-height: 1.45; word-break: break-word; }
.hint { color: #667085; font-size: 13px; line-height: 1.45; margin-top: 8px; }
.private { background: #fff7ed; border-color: #fed7aa; color: #7c2d12; }
.msg.own .private { background: #fff7ed; border-color: #fed7aa; color: #7c2d12; }
@media (max-width: 760px) { .layout { grid-template-columns: 1fr; } .form { grid-template-columns: 1fr; } .auth { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<main>
<h1>MiniChat</h1>
<div class="sub">C++ Web 聊天室，支持房间、私聊、消息持久化和在线用户列表。</div>
<div class="auth panel" style="padding:14px">
<input id="authUser" placeholder="username" value="jerry">
<input id="authPass" placeholder="password" type="password" value="123456">
<input id="authNick" placeholder="nickname" value="Jerry">
<button onclick="registerUser()">Register</button>
<button onclick="loginUser()">Login</button>
<button onclick="logoutUser()">Logout</button>
</div>
<div id="authMsg" class="authmsg"></div>
<div class="layout">
<section class="panel chat">
<div id="messages" class="messages"></div>
<div class="form">
<input id="room" placeholder="room" value="general" onchange="switchRoom()">
<input id="user" placeholder="nickname" value="Jerry" disabled>
<input id="to" placeholder="private to" onchange="savePrefs()">
<input id="text" placeholder="message" onkeydown="if(event.key==='Enter') sendMsg()">
<button onclick="sendMsg()">Send</button>
</div>
</section>
<aside class="panel side">
<h3>Current</h3>
<div class="identity">当前身份：<strong id="whoami">未登录</strong><br>房间：<strong id="whereami">general</strong><br><span id="connStatus" class="status">connecting</span></div>
<div class="tools"><button class="danger" onclick="clearRoom()">Clear Current Room</button></div>
<h3>Search</h3>
<div class="search"><input id="searchText" placeholder="keyword" onkeydown="if(event.key==='Enter') searchMessages()"><button onclick="searchMessages()">Search</button></div>
<div id="searchResults"></div>
<h3>Rooms</h3>
<div><span class="room" onclick="setRoom('general')">general</span><span class="room" onclick="setRoom('cpp')">cpp</span><span class="room" onclick="setRoom('game')">game</span></div>
<h3>Online</h3>
<div id="users"></div>
<div class="hint">登录后才能聊天。点击在线用户可填入私聊对象。私聊消息由服务端过滤，只有发送者和接收者会收到。</div>
</aside>
</div>
</main>
<script>
let lastId = 0;
let authToken = localStorage.getItem('minichat.token') || "";
const seenIds = new Set();
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function time(ts) { return new Date(Number(ts) * 1000).toLocaleTimeString(); }
function currentRoom() { return room.value.trim() || 'general'; }
function currentUser() { return user.value.trim() || 'anonymous'; }
function tokenParam() { return authToken ? `&token=${encodeURIComponent(authToken)}` : ""; }
function requireLogin() { if (authToken) return true; setAuthMsg('Please login first.', false); return false; }
function setAuthMsg(msg, ok=true) { authMsg.textContent = msg; authMsg.className = `authmsg ${ok ? 'ok' : 'err'}`; }
function savePrefs() {
  localStorage.setItem('minichat.room', currentRoom());
  localStorage.setItem('minichat.to', to.value.trim());
}
function loadPrefs() {
  room.value = localStorage.getItem('minichat.room') || room.value;
  authToken = localStorage.getItem('minichat.token') || '';
  user.value = localStorage.getItem('minichat.user') || user.value;
  to.value = localStorage.getItem('minichat.to') || '';
}

async function registerUser() {
  const username = authUser.value.trim();
  const password = authPass.value.trim();
  const nickname = authNick.value.trim() || username;
  const res = await fetch(`/api/auth_register?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}&nickname=${encodeURIComponent(nickname)}`);
  const data = await res.json();
  if (!data.ok) { setAuthMsg(data.error || 'register failed', false); return; }
  setAuthMsg('Registered. Now login.');
}
async function logoutUser() {
  const oldToken = authToken;
  authToken = "";
  localStorage.removeItem('minichat.token');
  if (oldToken) await fetch(`/api/auth_logout?token=${encodeURIComponent(oldToken)}`).catch(() => {});
  setAuthMsg('Logged out.');
  updateIdentity();
  closeEvents();
  messages.innerHTML = "";
  users.innerHTML = "";
  setStatus('login required', 'off');
}
async function loginUser() {
  const username = authUser.value.trim();
  const password = authPass.value.trim();
  const res = await fetch(`/api/auth_login?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`);
  const data = await res.json();
  if (!data.ok) { setAuthMsg(data.error || 'login failed', false); return; }
  authToken = data.token;
  user.value = data.username;
  localStorage.setItem('minichat.token', authToken);
  localStorage.setItem('minichat.user', data.username);
  setAuthMsg(`Logged in as ${data.username}`);
  switchRoom();
}

function setRoom(name) { room.value = name; switchRoom(); }
function updateIdentity() { whoami.textContent = authToken ? currentUser() : '未登录'; whereami.textContent = currentRoom(); }
function switchRoom() { savePrefs(); updateIdentity(); closeEvents(); lastId = 0; seenIds.clear(); messages.innerHTML = ''; searchResults.innerHTML = ''; if (!authToken) { setStatus('login required', 'off'); return; } loadMessages().then(connectEvents); loadUsers(); }
async function sendMsg() {
  if (!requireLogin()) return;
  const r = currentRoom();
  const u = currentUser();
  const target = to.value.trim();
  const t = text.value.trim();
  if (!t) return;
  savePrefs();
  text.value = '';
  await fetch(`/api/send?room=${encodeURIComponent(r)}&user=${encodeURIComponent(u)}&to=${encodeURIComponent(target)}&msg=${encodeURIComponent(t)}${tokenParam()}`);
  await loadMessages();
  await loadUsers();
}
let events = null;
function closeEvents() { if (events) { events.close(); events = null; } }
function renderMessage(m) {
  const id = Number(m.id);
  if (seenIds.has(id)) return;
  seenIds.add(id);
  lastId = Math.max(lastId, id);
  const box = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = m.user === currentUser() ? 'msg own' : 'msg';
  const privateMark = m.to ? ` · 私聊 ${esc(m.user)} -> ${esc(m.to)} · 只对双方可见` : ` · ${esc(m.user)}`;
  const bubbleClass = m.to ? 'bubble private' : 'bubble';
  div.innerHTML = `<div class="meta">#${esc(m.room)}${privateMark} · ${time(m.ts)}</div><div class="${bubbleClass}">${esc(m.text)}</div>`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}
async function loadMessages() {
  const res = await fetch(`/api/messages?room=${encodeURIComponent(currentRoom())}&user=${encodeURIComponent(currentUser())}&since=${lastId}${tokenParam()}`);
  const data = await res.json();
  for (const m of data.messages || []) renderMessage(m);
}
function setStatus(text, cls) { connStatus.textContent = text; connStatus.className = `status ${cls}`; }
function connectEvents() {
  closeEvents();
  setStatus('connecting', '');
  events = new EventSource(`/events?room=${encodeURIComponent(currentRoom())}&user=${encodeURIComponent(currentUser())}&since=${lastId}${tokenParam()}`);
  events.onopen = () => setStatus('realtime connected', 'on');
  events.onerror = () => setStatus('reconnecting', 'off');
  events.onmessage = event => renderMessage(JSON.parse(event.data));
}
async function clearRoom() {
  if (!requireLogin()) return;
  if (!confirm(`Clear all messages in room ${currentRoom()}?`)) return;
  await fetch(`/api/clear?room=${encodeURIComponent(currentRoom())}&user=${encodeURIComponent(currentUser())}${tokenParam()}`);
  closeEvents();
  lastId = 0;
  seenIds.clear();
  messages.innerHTML = '';
  searchResults.innerHTML = '';
  await loadMessages();
  connectEvents();
}
async function searchMessages() {
  if (!requireLogin()) return;
  const q = searchText.value.trim();
  searchResults.innerHTML = '';
  if (!q) return;
  const res = await fetch(`/api/search?room=${encodeURIComponent(currentRoom())}&user=${encodeURIComponent(currentUser())}&q=${encodeURIComponent(q)}${tokenParam()}`);
  const data = await res.json();
  if (!data.messages || data.messages.length === 0) {
    searchResults.innerHTML = '<div class="hint">No results in current room.</div>';
    return;
  }
  for (const m of data.messages) {
    const div = document.createElement('div');
    div.className = 'result';
    const privateMark = m.to ? `私聊 ${esc(m.user)} -> ${esc(m.to)}` : esc(m.user);
    div.innerHTML = `<div class="meta">#${esc(m.room)} · ${privateMark} · ${time(m.ts)}</div><div class="text">${esc(m.text)}</div>`;
    searchResults.appendChild(div);
  }
}

async function initApp() {
  loadPrefs();
  if (authToken) {
    const res = await fetch(`/api/auth_me?token=${encodeURIComponent(authToken)}`);
    const data = await res.json();
    if (!data.ok) {
      authToken = "";
      localStorage.removeItem('minichat.token');
      setAuthMsg('Session expired. Please login again.', false);
    } else {
      user.value = data.username;
      localStorage.setItem('minichat.user', data.username);
      setAuthMsg(`Logged in as ${data.username}`);
    }
  }
  updateIdentity();
  if (authToken) { loadMessages().then(connectEvents); loadUsers(); } else { setStatus('login required', 'off'); }
}

async function loadUsers() {
  const res = await fetch(`/api/users?room=${encodeURIComponent(currentRoom())}&user=${encodeURIComponent(currentUser())}${tokenParam()}`);
  const data = await res.json();
  users.innerHTML = '';
  for (const name of data.users || []) {
    const span = document.createElement('span');
    span.className = 'user';
    span.textContent = name;
    span.title = '点击私聊 ' + name;
    span.onclick = () => { if (name !== currentUser()) to.value = name; };
    users.appendChild(span);
  }
}
setInterval(() => { if (authToken) loadUsers(); }, 3000);
initApp();
</script>
</body>
</html>)HTML";
}


std::string auth_register(const std::string& target) {
    std::string username = query_value(target, "username");
    std::string password = query_value(target, "password");
    std::string nickname = query_value(target, "nickname");
    if (username.empty() || password.empty() || nickname.empty()) {
        return http_response(400, "application/json", "{\"ok\":false,\"error\":\"missing username password or nickname\"}");
    }
    std::string response = rpc_call("register " + username + " " + password + " " + nickname);
    if (response.rfind("OK", 0) == 0) return http_response(200, "application/json", "{\"ok\":true,\"message\":\"registered\"}");
    return http_response(400, "application/json", "{\"ok\":false,\"error\":\"" + json_escape(response.empty() ? "rpc user service unavailable" : response) + "\"}");
}

std::string auth_login(const std::string& target) {
    std::string username = query_value(target, "username");
    std::string password = query_value(target, "password");
    if (username.empty() || password.empty()) {
        return http_response(400, "application/json", "{\"ok\":false,\"error\":\"missing username or password\"}");
    }
    std::string response = rpc_call("login " + username + " " + password);
    auto parts = split_space(response);
    if (parts.size() >= 6 && parts[0] == "OK" && parts[1] == "login" && parts[4] == "token") {
        return http_response(200, "application/json", "{\"ok\":true,\"username\":\"" + json_escape(parts[2]) + "\",\"nickname\":\"" + json_escape(parts[3]) + "\",\"token\":\"" + json_escape(parts[5]) + "\"}");
    }
    return http_response(400, "application/json", "{\"ok\":false,\"error\":\"" + json_escape(response.empty() ? "rpc user service unavailable" : response) + "\"}");
}


std::string auth_me(const std::string& target) {
    std::string token = query_value(target, "token");
    std::string username;
    std::string nickname;
    if (!rpc_whoami(token, username, nickname)) {
        return http_response(401, "application/json", "{\"ok\":false,\"error\":\"invalid token or rpc user service unavailable\"}");
    }
    return http_response(200, "application/json", "{\"ok\":true,\"username\":\"" + json_escape(username) + "\",\"nickname\":\"" + json_escape(nickname) + "\"}");
}

std::string auth_logout(const std::string& target) {
    std::string token = query_value(target, "token");
    if (token.empty()) {
        return http_response(400, "application/json", "{\"ok\":false,\"error\":\"missing token\"}");
    }
    std::string response = rpc_call("logout " + token);
    if (response.rfind("OK", 0) == 0) return http_response(200, "application/json", "{\"ok\":true,\"message\":\"logout\"}");
    return http_response(400, "application/json", "{\"ok\":false,\"error\":\"" + json_escape(response.empty() ? "rpc user service unavailable" : response) + "\"}");
}

std::string send_message(const std::string& target) {
    std::string room = query_value(target, "room");
    std::string user;
    std::string error;
    if (!resolve_request_user(target, user, error)) return http_response(401, "application/json", "{\"ok\":false,\"error\":\"" + json_escape(error) + "\"}");
    std::string to = query_value(target, "to");
    std::string text = query_value(target, "msg");
    if (room.empty()) room = "general";
    if (text.empty()) return http_response(400, "application/json", "{\"ok\":false,\"error\":\"empty message\"}");
    if (room.size() > 32 || user.size() > 32 || to.size() > 32 || text.size() > 1000) return http_response(400, "application/json", "{\"ok\":false,\"error\":\"too long\"}");
    Message msg;
    {
        std::lock_guard<std::mutex> lock(g_state_mu);
        msg = Message{g_next_id++, room, user, to, text, now_epoch()};
        g_messages.push_back(msg);
        append_message(msg);
        g_users[room + ":" + user] = msg.ts;
    }
    return http_response(200, "application/json", "{\"ok\":true,\"id\":" + std::to_string(msg.id) + "}");
}

std::string messages_json(const std::string& target) {
    std::string room = query_value(target, "room");
    std::string user;
    std::string error;
    if (!resolve_request_user(target, user, error)) return http_response(401, "application/json", "{\"ok\":false,\"error\":\"" + json_escape(error) + "\"}");
    if (room.empty()) room = "general";
    std::string since_text = query_value(target, "since");
    uint64_t since = since_text.empty() ? 0 : static_cast<uint64_t>(std::stoull(since_text));
    std::string body = "{\"ok\":true,\"messages\":[";
    bool first = true;
    std::lock_guard<std::mutex> lock(g_state_mu);
    for (const auto& msg : g_messages) {
        if (msg.id <= since || !can_view_message(msg, room, user)) continue;
        if (!first) body += ",";
        first = false;
        body += message_json(msg);
    }
    body += "]}";
    return http_response(200, "application/json", body);
}

std::string search_json(const std::string& target) {
    std::string room = query_value(target, "room");
    std::string user;
    std::string error;
    if (!resolve_request_user(target, user, error)) return http_response(401, "application/json", "{\"ok\":false,\"error\":\"" + json_escape(error) + "\"}");
    std::string q = query_value(target, "q");
    if (room.empty()) room = "general";
    if (q.empty()) return http_response(200, "application/json", "{\"ok\":true,\"messages\":[]}");
    if (q.size() > 100) return http_response(400, "application/json", "{\"ok\":false,\"error\":\"query too long\"}");

    std::vector<Message> hits;
    {
        std::lock_guard<std::mutex> lock(g_state_mu);
        for (auto it = g_messages.rbegin(); it != g_messages.rend() && hits.size() < 50; ++it) {
            if (!can_view_message(*it, room, user)) continue;
            if (it->text.find(q) == std::string::npos && it->user.find(q) == std::string::npos) continue;
            hits.push_back(*it);
        }
    }

    std::string body = "{\"ok\":true,\"messages\":[";
    bool first = true;
    for (const auto& msg : hits) {
        if (!first) body += ",";
        first = false;
        body += message_json(msg);
    }
    body += "]}";
    return http_response(200, "application/json", body);
}
std::string clear_room(const std::string& target) {
    std::string room = query_value(target, "room");
    if (room.empty()) room = "general";

    size_t removed = 0;
    {
        std::lock_guard<std::mutex> lock(g_state_mu);
        auto old_size = g_messages.size();
        g_messages.erase(std::remove_if(g_messages.begin(), g_messages.end(), [&](const Message& msg) {
            return msg.room == room;
        }), g_messages.end());
        removed = old_size - g_messages.size();
        rewrite_messages_locked();
    }

    return http_response(200, "application/json", "{\"ok\":true,\"removed\":" + std::to_string(removed) + "}");
}
std::string users_json(const std::string& target) {
    std::string room = query_value(target, "room");
    std::string user;
    std::string error;
    if (!resolve_request_user(target, user, error)) return http_response(401, "application/json", "{\"ok\":false,\"error\":\"" + json_escape(error) + "\"}");
    if (room.empty()) room = "general";
    uint64_t now = now_epoch();
    std::lock_guard<std::mutex> lock(g_state_mu);
    if (!user.empty()) g_users[room + ":" + user] = now;
    std::string body = "{\"ok\":true,\"users\":[";
    bool first = true;
    std::string prefix = room + ":";
    for (auto it = g_users.begin(); it != g_users.end();) {
        if (now > it->second + 15) {
            it = g_users.erase(it);
            continue;
        }
        if (it->first.rfind(prefix, 0) != 0) {
            ++it;
            continue;
        }
        if (!first) body += ",";
        first = false;
        body += "\"" + json_escape(it->first.substr(prefix.size())) + "\"";
        ++it;
    }
    body += "]}";
    return http_response(200, "application/json", body);
}

void stream_events(int fd, const std::string& target) {
    std::string room = query_value(target, "room");
    std::string user;
    std::string error;
    if (!resolve_request_user(target, user, error)) {
        send_all(fd, http_response(401, "application/json", "{\"ok\":false,\"error\":\"" + json_escape(error) + "\"}"));
        return;
    }
    if (room.empty()) room = "general";
    std::string since_text = query_value(target, "since");
    uint64_t since = since_text.empty() ? 0 : static_cast<uint64_t>(std::stoull(since_text));

    std::string header = "HTTP/1.1 200 OK\r\n"
                         "Content-Type: text/event-stream; charset=utf-8\r\n"
                         "Cache-Control: no-cache\r\n"
                         "Connection: keep-alive\r\n"
                         "Access-Control-Allow-Origin: *\r\n"
                         "\r\n";
    if (!send_all(fd, header)) return;
    if (!send_all(fd, ": connected\n\n")) return;

    int idle_ticks = 0;
    while (g_running) {
        std::string events;
        {
            std::lock_guard<std::mutex> lock(g_state_mu);
            g_users[room + ":" + user] = now_epoch();
            for (const auto& msg : g_messages) {
                if (msg.id <= since || !can_view_message(msg, room, user)) continue;
                events += "data: " + message_json(msg) + "\n\n";
                since = std::max(since, msg.id);
            }
        }
        if (!events.empty()) {
            if (!send_all(fd, events)) return;
            idle_ticks = 0;
        } else {
            ++idle_ticks;
            if (idle_ticks >= 20) {
                if (!send_all(fd, ": keepalive\n\n")) return;
                idle_ticks = 0;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(300));
        }
    }
}
std::string handle_request(const std::string& request) {
    std::istringstream iss(request);
    std::string method, target, version;
    iss >> method >> target >> version;
    if (method == "GET" && (target == "/" || target == "/index.html")) return http_response(200, "text/html", html_page());
    if (method == "GET" && target.rfind("/api/auth_register", 0) == 0) return auth_register(target);
    if (method == "GET" && target.rfind("/api/auth_login", 0) == 0) return auth_login(target);
    if (method == "GET" && target.rfind("/api/auth_me", 0) == 0) return auth_me(target);
    if (method == "GET" && target.rfind("/api/auth_logout", 0) == 0) return auth_logout(target);
    if (method == "GET" && target.rfind("/api/send", 0) == 0) return send_message(target);
    if (method == "GET" && target.rfind("/api/messages", 0) == 0) return messages_json(target);
    if (method == "GET" && target.rfind("/api/search", 0) == 0) return search_json(target);
    if (method == "GET" && target.rfind("/api/clear", 0) == 0) return clear_room(target);
    if (method == "GET" && target.rfind("/api/users", 0) == 0) return users_json(target);
    return http_response(404, "text/plain", "not found");
}

int create_listen_socket(uint16_t port) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        std::cerr << "socket failed: " << std::strerror(errno) << "\n";
        return -1;
    }
    int reuse = 1;
    ::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    sockaddr_in addr {};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(port);
    if (::bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        std::cerr << "bind failed: " << std::strerror(errno) << "\n";
        ::close(fd);
        return -1;
    }
    if (::listen(fd, SOMAXCONN) < 0) {
        std::cerr << "listen failed: " << std::strerror(errno) << "\n";
        ::close(fd);
        return -1;
    }
    return fd;
}

std::string read_request(int fd) {
    std::string request;
    char buf[4096];
    while (true) {
        ssize_t n = ::recv(fd, buf, sizeof(buf), 0);
        if (n < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (n == 0) break;
        request.append(buf, static_cast<size_t>(n));
        if (request.find("\r\n\r\n") != std::string::npos) break;
        if (request.size() > 64 * 1024) break;
    }
    return request;
}

void handle_client(int fd) {
    std::string request = read_request(fd);
    if (request.empty()) {
        send_all(fd, http_response(400, "text/plain", "bad request"));
        return;
    }

    std::istringstream iss(request);
    std::string method, target, version;
    iss >> method >> target >> version;
    if (method == "GET" && target.rfind("/events", 0) == 0) {
        stream_events(fd, target);
        return;
    }

    send_all(fd, handle_request(request));
}

} // namespace

int main(int argc, char* argv[]) {
    uint16_t port = 19191;
    if (argc >= 2) {
        int parsed = std::stoi(argv[1]);
        if (parsed <= 0 || parsed > 65535) {
            std::cerr << "invalid chat port\n";
            return 1;
        }
        port = static_cast<uint16_t>(parsed);
    }
    if (argc >= 3) {
        g_rpc_host = argv[2];
    }
    if (argc >= 4) {
        int parsed = std::stoi(argv[3]);
        if (parsed <= 0 || parsed > 65535) {
            std::cerr << "invalid rpc port\n";
            return 1;
        }
        g_rpc_port = static_cast<uint16_t>(parsed);
    }
    std::signal(SIGINT, handle_signal);
    std::signal(SIGTERM, handle_signal);
    load_messages();
    int listen_fd = create_listen_socket(port);
    if (listen_fd < 0) return 1;
    std::cout << "minichat listening on http://127.0.0.1:" << port << "\n";
    std::cout << "rpc user service: " << g_rpc_host << ":" << g_rpc_port << "\n";
    while (g_running) {
        sockaddr_in client_addr {};
        socklen_t len = sizeof(client_addr);
        int client_fd = ::accept(listen_fd, reinterpret_cast<sockaddr*>(&client_addr), &len);
        if (client_fd < 0) {
            if (errno == EINTR) continue;
            std::cerr << "accept failed: " << std::strerror(errno) << "\n";
            break;
        }
        std::thread([client_fd]() {
            handle_client(client_fd);
            ::close(client_fd);
        }).detach();
    }
    ::close(listen_fd);
    std::cout << "minichat stopped\n";
    return 0;
}













