#include <algorithm>
#include <arpa/inet.h>
#include <cerrno>
#include <cctype>
#include <csignal>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <mutex>
#include <netinet/in.h>
#include <random>
#include <sstream>
#include <string>
#include <sys/socket.h>
#include <chrono>
#include <thread>
#include <unistd.h>
#include <unordered_map>
#include <vector>

namespace {

volatile std::sig_atomic_t g_running = 1;
const std::string kDataDir = "data";
const std::string kUserPath = "data/users.tsv";

struct User {
    std::string username;
    std::string password;
    std::string nickname;
};

std::unordered_map<std::string, User> g_users;
std::unordered_map<std::string, std::string> g_sessions;
std::mutex g_mu;

void handle_signal(int) { g_running = 0; }

std::vector<std::string> split(const std::string& text, char delim) {
    std::vector<std::string> parts;
    size_t start = 0;
    while (start <= text.size()) {
        size_t pos = text.find(delim, start);
        parts.push_back(text.substr(start, pos == std::string::npos ? std::string::npos : pos - start));
        if (pos == std::string::npos) break;
        start = pos + 1;
    }
    return parts;
}

bool is_valid_name(const std::string& value) {
    if (value.empty() || value.size() > 32) return false;
    return std::all_of(value.begin(), value.end(), [](unsigned char c) {
        return std::isalnum(c) || c == '_' || c == '-';
    });
}

std::string escape_field(std::string value) {
    for (char& c : value) {
        if (c == '\t' || c == '\n' || c == '\r') c = ' ';
    }
    return value;
}
std::string make_token(const std::string& username) {
    static thread_local std::mt19937_64 rng(std::random_device{}());
    auto now = std::chrono::steady_clock::now().time_since_epoch().count();
    std::uniform_int_distribution<unsigned long long> dist;
    std::ostringstream oss;
    oss << "tok_" << username << "_" << std::hex << now << "_" << dist(rng);
    return oss.str();
}


void load_users() {
    std::ifstream in(kUserPath);
    if (!in.is_open()) return;
    std::string line;
    while (std::getline(in, line)) {
        auto parts = split(line, '\t');
        if (parts.size() < 3) continue;
        g_users[parts[0]] = User{parts[0], parts[1], parts[2]};
    }
    std::cout << "loaded " << g_users.size() << " users\n";
}

void save_users_locked() {
    std::filesystem::create_directories(kDataDir);
    std::ofstream out(kUserPath, std::ios::trunc);
    for (const auto& [_, user] : g_users) {
        out << escape_field(user.username) << '\t'
            << escape_field(user.password) << '\t'
            << escape_field(user.nickname) << '\n';
    }
}

std::string ok(const std::string& body = "") {
    return body.empty() ? "OK\n" : "OK " + body + "\n";
}

std::string err(const std::string& message) {
    return "ERR " + message + "\n";
}

std::string handle_register(const std::vector<std::string>& args) {
    if (args.size() < 4) return err("usage: register <username> <password> <nickname>");
    std::string username = args[1];
    std::string password = args[2];
    std::string nickname = args[3];
    if (!is_valid_name(username)) return err("invalid username");
    if (password.empty() || password.size() > 64) return err("invalid password");
    if (nickname.empty() || nickname.size() > 32) return err("invalid nickname");

    std::lock_guard<std::mutex> lock(g_mu);
    if (g_users.find(username) != g_users.end()) return err("user exists");
    g_users[username] = User{username, password, nickname};
    save_users_locked();
    return ok("registered " + username);
}

std::string handle_login(const std::vector<std::string>& args) {
    if (args.size() < 3) return err("usage: login <username> <password>");
    std::lock_guard<std::mutex> lock(g_mu);
    auto it = g_users.find(args[1]);
    if (it == g_users.end()) return err("user not found");
    if (it->second.password != args[2]) return err("wrong password");
    std::string token = make_token(it->second.username);
    g_sessions[token] = it->second.username;
    return ok("login " + it->second.username + " " + it->second.nickname + " token " + token);
}

std::string handle_get_user(const std::vector<std::string>& args) {
    if (args.size() < 2) return err("usage: get_user <username>");
    std::lock_guard<std::mutex> lock(g_mu);
    auto it = g_users.find(args[1]);
    if (it == g_users.end()) return err("user not found");
    return ok("user " + it->second.username + " " + it->second.nickname);
}

std::string handle_whoami(const std::vector<std::string>& args) {
    if (args.size() < 2) return err("usage: whoami <token>");
    std::lock_guard<std::mutex> lock(g_mu);
    auto session_it = g_sessions.find(args[1]);
    if (session_it == g_sessions.end()) return err("invalid token");
    auto user_it = g_users.find(session_it->second);
    if (user_it == g_users.end()) return err("user not found");
    return ok("me " + user_it->second.username + " " + user_it->second.nickname);
}

std::string handle_logout(const std::vector<std::string>& args) {
    if (args.size() < 2) return err("usage: logout <token>");
    std::lock_guard<std::mutex> lock(g_mu);
    auto erased = g_sessions.erase(args[1]);
    if (erased == 0) return err("invalid token");
    return ok("logout");
}

std::string dispatch(const std::string& line) {
    auto args = split(line, ' ');
    if (args.empty() || args[0].empty()) return err("empty method");
    if (args[0] == "register") return handle_register(args);
    if (args[0] == "login") return handle_login(args);
    if (args[0] == "get_user") return handle_get_user(args);
    if (args[0] == "whoami") return handle_whoami(args);
    if (args[0] == "logout") return handle_logout(args);
    if (args[0] == "ping") return ok("pong");
    return err("unknown method");
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

std::string recv_line(int fd) {
    std::string line;
    char c = 0;
    while (line.size() < 4096) {
        ssize_t n = ::recv(fd, &c, 1, 0);
        if (n < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (n == 0) break;
        if (c == '\n') break;
        if (c != '\r') line.push_back(c);
    }
    return line;
}

void handle_client(int fd) {
    while (g_running) {
        std::string line = recv_line(fd);
        if (line.empty()) break;
        std::string response = dispatch(line);
        if (!send_all(fd, response)) break;
    }
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

} // namespace

int main(int argc, char* argv[]) {
    uint16_t port = 18888;
    if (argc >= 2) {
        int parsed = std::stoi(argv[1]);
        if (parsed <= 0 || parsed > 65535) {
            std::cerr << "invalid port\n";
            return 1;
        }
        port = static_cast<uint16_t>(parsed);
    }

    std::signal(SIGINT, handle_signal);
    std::signal(SIGTERM, handle_signal);
    load_users();

    int listen_fd = create_listen_socket(port);
    if (listen_fd < 0) return 1;
    std::cout << "rpc_server listening on 0.0.0.0:" << port << "\n";
    std::cout << "methods: ping, register, login, get_user, whoami, logout\n";

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
    std::cout << "rpc_server stopped\n";
    return 0;
}


