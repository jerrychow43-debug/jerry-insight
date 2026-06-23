#include <arpa/inet.h>
#include <cerrno>
#include <csignal>
#include <cstring>
#include <fcntl.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <netinet/in.h>
#include <sstream>
#include <iomanip>
#include <string>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <unistd.h>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {

volatile std::sig_atomic_t g_running = 1;

void handle_signal(int) {
    g_running = 0;
}

std::string trim_cr(std::string line) {
    if (!line.empty() && line.back() == '\r') {
        line.pop_back();
    }
    return line;
}

std::vector<std::string> split_words(const std::string& line) {
    std::istringstream iss(line);
    std::vector<std::string> words;
    std::string word;
    while (iss >> word) {
        words.push_back(word);
    }
    return words;
}

bool set_nonblocking(int fd) {
    int flags = ::fcntl(fd, F_GETFL, 0);
    if (flags < 0) {
        return false;
    }
    return ::fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0;
}

std::string http_status_text(int status) {
    if (status == 200) return "OK";
    if (status == 400) return "Bad Request";
    if (status == 404) return "Not Found";
    if (status == 500) return "Internal Server Error";
    return "OK";
}

std::string http_response(int status, const std::string& content_type, const std::string& body) {
    std::ostringstream oss;
    oss << "HTTP/1.1 " << status << " " << http_status_text(status) << "\r\n"
        << "Content-Type: " << content_type << "; charset=utf-8\r\n"
        << "Content-Length: " << body.size() << "\r\n"
        << "Connection: close\r\n"
        << "Access-Control-Allow-Origin: *\r\n"
        << "\r\n"
        << body;
    return oss.str();
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
        if (input[i] == '+' ) {
            out += ' ';
        } else if (input[i] == '%' && i + 2 < input.size()) {
            int hi = hex_value(input[i + 1]);
            int lo = hex_value(input[i + 2]);
            if (hi >= 0 && lo >= 0) {
                out += static_cast<char>((hi << 4) | lo);
                i += 2;
            } else {
                out += input[i];
            }
        } else {
            out += input[i];
        }
    }
    return out;
}

std::unordered_map<std::string, std::string> parse_query(const std::string& target) {
    std::unordered_map<std::string, std::string> result;
    size_t q = target.find('?');
    if (q == std::string::npos || q + 1 >= target.size()) {
        return result;
    }

    std::string query = target.substr(q + 1);
    size_t start = 0;
    while (start <= query.size()) {
        size_t amp = query.find('&', start);
        std::string pair = query.substr(start, amp == std::string::npos ? std::string::npos : amp - start);
        size_t eq = pair.find('=');
        if (eq != std::string::npos) {
            result[url_decode(pair.substr(0, eq))] = url_decode(pair.substr(eq + 1));
        }
        if (amp == std::string::npos) {
            break;
        }
        start = amp + 1;
    }
    return result;
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

std::string html_page() {
    return R"HTML(<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MiniKV</title>
<style>
body { margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f7fb; color: #1f2937; }
main { max-width: 880px; margin: 40px auto; padding: 0 20px; }
h1 { margin: 0 0 8px; font-size: 34px; }
.sub { color: #667085; margin-bottom: 24px; }
.panel { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 8px 24px rgba(15,23,42,.06); }
.row { display: grid; grid-template-columns: 1fr 1fr auto; gap: 12px; align-items: end; }
label { display: block; font-size: 13px; color: #475467; margin-bottom: 6px; }
input { width: 100%; box-sizing: border-box; padding: 10px 12px; border: 1px solid #d0d5dd; border-radius: 6px; font-size: 15px; }
button { padding: 10px 14px; border: 0; border-radius: 6px; background: #2563eb; color: #fff; font-weight: 650; cursor: pointer; }
button.secondary { background: #475467; }
button.danger { background: #dc2626; }
.actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
pre { min-height: 90px; white-space: pre-wrap; background: #101828; color: #d1fadf; padding: 14px; border-radius: 8px; overflow: auto; }
.keys { display: flex; flex-wrap: wrap; gap: 8px; }
.key { background: #eef2ff; color: #3730a3; border: 1px solid #c7d2fe; padding: 6px 10px; border-radius: 999px; font-size: 13px; }
@media (max-width: 720px) { .row { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<main>
<h1>MiniKV</h1>
<div class="sub">C++ Linux TCP/epoll 键值存储服务，支持 AOF 持久化。</div>
<section class="panel">
<div class="row">
<div><label>Key</label><input id="key" value="name"></div>
<div><label>Value</label><input id="value" value="Jerry"></div>
<button onclick="setValue()">Set</button>
</div>
<div class="actions">
<button class="secondary" onclick="getValue()">Get</button>
<button class="danger" onclick="delValue()">Delete</button>
<button class="secondary" onclick="loadKeys()">Refresh Keys</button>
<button class="danger" onclick="flushAll()">Clear All</button>
</div>
</section>
<section class="panel"><label>Result</label><pre id="result">ready</pre></section>
<section class="panel"><label>Keys</label><div class="keys" id="keys"></div></section>
</main>
<script>
async function api(path) {
  const res = await fetch(path);
  const data = await res.json();
  document.getElementById('result').textContent = JSON.stringify(data, null, 2);
  await loadKeys(false);
  return data;
}
function enc(v) { return encodeURIComponent(v); }
async function setValue() { await api(`/api/set?key=${enc(key.value)}&value=${enc(value.value)}`); }
async function getValue() { await api(`/api/get?key=${enc(key.value)}`); }
async function delValue() { await api(`/api/del?key=${enc(key.value)}`); }
async function flushAll() { if (confirm('Clear all keys?')) await api('/api/flushall'); }
async function loadKeys(show = true) {
  const res = await fetch('/api/keys');
  const data = await res.json();
  const box = document.getElementById('keys');
  box.innerHTML = '';
  for (const k of data.keys || []) {
    const span = document.createElement('button');
    span.className = 'key';
    span.textContent = k;
    span.onclick = () => { key.value = k; getValue(); };
    box.appendChild(span);
  }
  if (show) document.getElementById('result').textContent = JSON.stringify(data, null, 2);
}
loadKeys(false);
</script>
</body>
</html>)HTML";
}
class KvStore {
public:
    explicit KvStore(std::string aof_path) : aof_path_(std::move(aof_path)) {
        load();
    }

    std::string execute(const std::string& raw_line, bool& should_close) {
        should_close = false;

        std::string line = trim_cr(raw_line);
        auto words = split_words(line);
        if (words.empty()) {
            return "ERR empty command\n";
        }

        const std::string& cmd = words[0];
        if (cmd == "set") {
            if (words.size() < 3) {
                return "ERR usage: set key value\n";
            }
            const std::string& key = words[1];
            size_t value_pos = line.find(key);
            if (value_pos == std::string::npos) {
                return "ERR invalid command\n";
            }
            value_pos += key.size();
            while (value_pos < line.size() && line[value_pos] == ' ') {
                ++value_pos;
            }
            if (value_pos >= line.size()) {
                return "ERR usage: set key value\n";
            }
            return set_value(key, line.substr(value_pos)) ? "OK\n" : "ERR save failed\n";
        }
        if (cmd == "get") {
            if (words.size() != 2) {
                return "ERR usage: get key\n";
            }
            std::string value;
            return get_value(words[1], value) ? value + "\n" : "(nil)\n";
        }
        if (cmd == "del") {
            if (words.size() != 2) {
                return "ERR usage: del key\n";
            }
            bool existed = false;
            bool ok = delete_key(words[1], existed);
            if (!existed) {
                return "(nil)\n";
            }
            return ok ? "OK\n" : "ERR save failed\n";
        }
        if (cmd == "keys") {
            return keys_text();
        }
        if (cmd == "flushall") {
            return flush_all() ? "OK\n" : "ERR save failed\n";
        }
        if (cmd == "help") {
            return help_text();
        }
        if (cmd == "exit" || cmd == "quit") {
            should_close = true;
            return "bye\n";
        }
        return "ERR unknown command, try: help\n";
    }

    bool set_value(const std::string& key, const std::string& value) {
        if (key.empty()) {
            return false;
        }
        data_[key] = value;
        return append_aof("set " + key + " " + value);
    }

    bool get_value(const std::string& key, std::string& value) const {
        auto it = data_.find(key);
        if (it == data_.end()) {
            return false;
        }
        value = it->second;
        return true;
    }

    bool delete_key(const std::string& key, bool& existed) {
        size_t erased = data_.erase(key);
        existed = erased == 1;
        if (!existed) {
            return true;
        }
        return append_aof("del " + key);
    }

    bool flush_all() {
        data_.clear();
        return append_aof("flushall");
    }

    std::vector<std::string> keys() const {
        std::vector<std::string> result;
        result.reserve(data_.size());
        for (const auto& item : data_) {
            result.push_back(item.first);
        }
        return result;
    }

private:
    std::string keys_text() const {
        if (data_.empty()) {
            return "(empty)\n";
        }

        std::string out;
        for (const auto& item : data_) {
            out += item.first;
            out += "\n";
        }
        return out;
    }

    std::string help_text() const {
        return "commands:\n"
               "  set key value\n"
               "  get key\n"
               "  del key\n"
               "  keys\n"
               "  flushall\n"
               "  exit\n";
    }

    void load() {
        std::ifstream in(aof_path_);
        if (!in.is_open()) {
            return;
        }

        std::string line;
        while (std::getline(in, line)) {
            replay(line);
        }
        std::cout << "loaded " << data_.size() << " keys from " << aof_path_ << "\n";
    }

    void replay(const std::string& raw_line) {
        std::string line = trim_cr(raw_line);
        auto words = split_words(line);
        if (words.empty()) {
            return;
        }

        if (words[0] == "set" && words.size() >= 3) {
            const std::string& key = words[1];
            size_t value_pos = line.find(key);
            if (value_pos == std::string::npos) {
                return;
            }
            value_pos += key.size();
            while (value_pos < line.size() && line[value_pos] == ' ') {
                ++value_pos;
            }
            if (value_pos < line.size()) {
                data_[key] = line.substr(value_pos);
            }
        } else if (words[0] == "del" && words.size() == 2) {
            data_.erase(words[1]);
        } else if (words[0] == "flushall") {
            data_.clear();
        }
    }

    bool append_aof(const std::string& command) const {
        std::filesystem::path path(aof_path_);
        if (path.has_parent_path()) {
            std::filesystem::create_directories(path.parent_path());
        }

        std::ofstream out(aof_path_, std::ios::app);
        if (!out.is_open()) {
            return false;
        }
        out << command << '\n';
        return out.good();
    }

    std::string aof_path_;
    std::unordered_map<std::string, std::string> data_;
};
int create_listen_socket(uint16_t port) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        std::cerr << "socket failed: " << std::strerror(errno) << "\n";
        return -1;
    }

    int reuse = 1;
    if (::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse)) < 0) {
        std::cerr << "setsockopt failed: " << std::strerror(errno) << "\n";
        ::close(fd);
        return -1;
    }

    if (!set_nonblocking(fd)) {
        std::cerr << "set nonblocking failed: " << std::strerror(errno) << "\n";
        ::close(fd);
        return -1;
    }

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

std::string handle_http_request(const std::string& request, KvStore& store) {
    std::istringstream iss(request);
    std::string method;
    std::string target;
    std::string version;
    iss >> method >> target >> version;

    if (method != "GET") {
        return http_response(400, "application/json", "{\"ok\":false,\"error\":\"only GET is supported\"}");
    }

    std::string path = target;
    size_t q = path.find('?');
    if (q != std::string::npos) {
        path = path.substr(0, q);
    }
    auto query = parse_query(target);

    if (path == "/" || path == "/index.html") {
        return http_response(200, "text/html", html_page());
    }
    if (path == "/api/set") {
        auto key_it = query.find("key");
        auto value_it = query.find("value");
        if (key_it == query.end() || value_it == query.end() || key_it->second.empty()) {
            return http_response(400, "application/json", "{\"ok\":false,\"error\":\"missing key or value\"}");
        }
        bool ok = store.set_value(key_it->second, value_it->second);
        return http_response(ok ? 200 : 500, "application/json", ok ? "{\"ok\":true}" : "{\"ok\":false,\"error\":\"save failed\"}");
    }
    if (path == "/api/get") {
        auto key_it = query.find("key");
        if (key_it == query.end() || key_it->second.empty()) {
            return http_response(400, "application/json", "{\"ok\":false,\"error\":\"missing key\"}");
        }
        std::string value;
        bool found = store.get_value(key_it->second, value);
        if (!found) {
            return http_response(200, "application/json", "{\"ok\":true,\"found\":false}");
        }
        return http_response(200, "application/json", "{\"ok\":true,\"found\":true,\"value\":\"" + json_escape(value) + "\"}");
    }
    if (path == "/api/del") {
        auto key_it = query.find("key");
        if (key_it == query.end() || key_it->second.empty()) {
            return http_response(400, "application/json", "{\"ok\":false,\"error\":\"missing key\"}");
        }
        bool existed = false;
        bool ok = store.delete_key(key_it->second, existed);
        return http_response(ok ? 200 : 500, "application/json", "{\"ok\":" + std::string(ok ? "true" : "false") + ",\"existed\":" + std::string(existed ? "true" : "false") + "}");
    }
    if (path == "/api/flushall") {
        bool ok = store.flush_all();
        return http_response(ok ? 200 : 500, "application/json", ok ? "{\"ok\":true}" : "{\"ok\":false,\"error\":\"save failed\"}");
    }
    if (path == "/api/keys") {
        auto keys = store.keys();
        std::string body = "{\"ok\":true,\"keys\":[";
        for (size_t i = 0; i < keys.size(); ++i) {
            if (i > 0) body += ",";
            body += "\"" + json_escape(keys[i]) + "\"";
        }
        body += "]}";
        return http_response(200, "application/json", body);
    }

    return http_response(404, "application/json", "{\"ok\":false,\"error\":\"not found\"}");
}
struct Client {
    std::string input;
    std::string output;
    bool close_after_write = false;
    bool greeted = false;
};

class EpollServer {
public:
    EpollServer(int listen_fd, KvStore& store) : listen_fd_(listen_fd), store_(store) {}

    ~EpollServer() {
        for (const auto& item : clients_) {
            ::close(item.first);
        }
        if (epoll_fd_ >= 0) {
            ::close(epoll_fd_);
        }
    }

    bool run() {
        epoll_fd_ = ::epoll_create1(0);
        if (epoll_fd_ < 0) {
            std::cerr << "epoll_create1 failed: " << std::strerror(errno) << "\n";
            return false;
        }

        if (!add_fd(listen_fd_, EPOLLIN)) {
            return false;
        }

        std::cout << "epoll event loop started\n";

        std::vector<epoll_event> events(1024);
        while (g_running) {
            int n = ::epoll_wait(epoll_fd_, events.data(), static_cast<int>(events.size()), 1000);
            if (n < 0) {
                if (errno == EINTR) {
                    continue;
                }
                std::cerr << "epoll_wait failed: " << std::strerror(errno) << "\n";
                return false;
            }

            for (int i = 0; i < n; ++i) {
                int fd = events[i].data.fd;
                uint32_t ev = events[i].events;

                if (fd == listen_fd_) {
                    accept_clients();
                    continue;
                }

                if ((ev & (EPOLLERR | EPOLLHUP | EPOLLRDHUP)) != 0) {
                    close_client(fd);
                    continue;
                }
                if ((ev & EPOLLIN) != 0) {
                    read_client(fd);
                }
                if (clients_.find(fd) != clients_.end() && (ev & EPOLLOUT) != 0) {
                    write_client(fd);
                }
            }
        }

        return true;
    }

private:
    bool add_fd(int fd, uint32_t events) {
        epoll_event event {};
        event.events = events;
        event.data.fd = fd;
        if (::epoll_ctl(epoll_fd_, EPOLL_CTL_ADD, fd, &event) < 0) {
            std::cerr << "epoll_ctl add failed: " << std::strerror(errno) << "\n";
            return false;
        }
        return true;
    }

    bool modify_fd(int fd, uint32_t events) {
        epoll_event event {};
        event.events = events;
        event.data.fd = fd;
        if (::epoll_ctl(epoll_fd_, EPOLL_CTL_MOD, fd, &event) < 0) {
            std::cerr << "epoll_ctl mod failed: " << std::strerror(errno) << "\n";
            return false;
        }
        return true;
    }

    void accept_clients() {
        while (true) {
            sockaddr_in client_addr {};
            socklen_t client_len = sizeof(client_addr);
            int client_fd = ::accept(listen_fd_, reinterpret_cast<sockaddr*>(&client_addr), &client_len);
            if (client_fd < 0) {
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    return;
                }
                if (errno == EINTR) {
                    continue;
                }
                std::cerr << "accept failed: " << std::strerror(errno) << "\n";
                return;
            }

            if (!set_nonblocking(client_fd)) {
                std::cerr << "set client nonblocking failed: " << std::strerror(errno) << "\n";
                ::close(client_fd);
                continue;
            }

            Client client;
            clients_.emplace(client_fd, std::move(client));
            add_fd(client_fd, EPOLLIN | EPOLLRDHUP);

            char ip[INET_ADDRSTRLEN] {};
            ::inet_ntop(AF_INET, &client_addr.sin_addr, ip, sizeof(ip));
            std::cout << "client connected: " << ip << ":" << ntohs(client_addr.sin_port)
                      << " fd=" << client_fd << "\n";
        }
    }

    void read_client(int fd) {
        auto it = clients_.find(fd);
        if (it == clients_.end()) {
            return;
        }

        char temp[1024];
        while (true) {
            ssize_t n = ::recv(fd, temp, sizeof(temp), 0);
            if (n < 0) {
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    process_lines(fd);
                    return;
                }
                if (errno == EINTR) {
                    continue;
                }
                std::cerr << "recv failed fd=" << fd << ": " << std::strerror(errno) << "\n";
                close_client(fd);
                return;
            }
            if (n == 0) {
                close_client(fd);
                return;
            }
            it->second.input.append(temp, static_cast<size_t>(n));
        }
    }

    void process_lines(int fd) {
        auto it = clients_.find(fd);
        if (it == clients_.end()) {
            return;
        }

        Client& client = it->second;
        if (client.input.rfind("GET ", 0) == 0 || client.input.rfind("POST ", 0) == 0) {
            size_t header_end = client.input.find("\r\n\r\n");
            if (header_end == std::string::npos) {
                header_end = client.input.find("\n\n");
            }
            if (header_end == std::string::npos) {
                return;
            }
            client.output += handle_http_request(client.input, store_);
            client.input.clear();
            client.close_after_write = true;
            modify_fd(fd, EPOLLIN | EPOLLOUT | EPOLLRDHUP);
            return;
        }

        if (!client.greeted) {
            client.output += "welcome to kv_server, try: help\n";
            client.greeted = true;
        }

        size_t pos = 0;
        while ((pos = client.input.find('\n')) != std::string::npos) {
            std::string line = client.input.substr(0, pos);
            client.input.erase(0, pos + 1);

            bool should_close = false;
            client.output += store_.execute(line, should_close);
            if (should_close) {
                client.close_after_write = true;
                break;
            }
        }

        modify_fd(fd, EPOLLIN | EPOLLOUT | EPOLLRDHUP);
    }
    void write_client(int fd) {
        auto it = clients_.find(fd);
        if (it == clients_.end()) {
            return;
        }

        Client& client = it->second;
        while (!client.output.empty()) {
            ssize_t n = ::send(fd, client.output.data(), client.output.size(), MSG_NOSIGNAL);
            if (n < 0) {
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    return;
                }
                if (errno == EINTR) {
                    continue;
                }
                std::cerr << "send failed fd=" << fd << ": " << std::strerror(errno) << "\n";
                close_client(fd);
                return;
            }
            if (n == 0) {
                return;
            }
            client.output.erase(0, static_cast<size_t>(n));
        }

        if (client.close_after_write) {
            close_client(fd);
            return;
        }

        modify_fd(fd, EPOLLIN | EPOLLRDHUP);
    }

    void close_client(int fd) {
        ::epoll_ctl(epoll_fd_, EPOLL_CTL_DEL, fd, nullptr);
        clients_.erase(fd);
        ::close(fd);
        std::cout << "client disconnected fd=" << fd << "\n";
    }

    int listen_fd_;
    int epoll_fd_ = -1;
    KvStore& store_;
    std::unordered_map<int, Client> clients_;
};

} // namespace

int main(int argc, char* argv[]) {
    uint16_t port = 6379;
    if (argc >= 2) {
        int parsed = std::stoi(argv[1]);
        if (parsed <= 0 || parsed > 65535) {
            std::cerr << "invalid port: " << argv[1] << "\n";
            return 1;
        }
        port = static_cast<uint16_t>(parsed);
    }

    std::signal(SIGINT, handle_signal);
    std::signal(SIGTERM, handle_signal);

    int listen_fd = create_listen_socket(port);
    if (listen_fd < 0) {
        return 1;
    }

    std::string aof_path = argc >= 3 ? argv[2] : "data/kv.aof";
    KvStore store(aof_path);
    std::cout << "kv_server listening on 0.0.0.0:" << port << "\n";

    EpollServer server(listen_fd, store);
    server.run();

    ::close(listen_fd);
    std::cout << "kv_server stopped\n";
    return 0;
}










