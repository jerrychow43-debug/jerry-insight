#include <arpa/inet.h>
#include <cerrno>
#include <cstring>
#include <iostream>
#include <netinet/in.h>
#include <sstream>
#include <string>
#include <sys/socket.h>
#include <unistd.h>
#include <vector>

namespace {

std::string join_args(int start, int argc, char* argv[]) {
    std::string line;
    for (int i = start; i < argc; ++i) {
        if (!line.empty()) line += ' ';
        line += argv[i];
    }
    return line;
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

int connect_server(const std::string& host, uint16_t port) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        std::cerr << "socket failed: " << std::strerror(errno) << "\n";
        return -1;
    }

    sockaddr_in addr {};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    if (::inet_pton(AF_INET, host.c_str(), &addr.sin_addr) != 1) {
        std::cerr << "invalid host: " << host << "\n";
        ::close(fd);
        return -1;
    }

    if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        std::cerr << "connect failed: " << std::strerror(errno) << "\n";
        ::close(fd);
        return -1;
    }
    return fd;
}

bool call_once(int fd, const std::string& request) {
    if (!send_all(fd, request + "\n")) {
        std::cerr << "send failed\n";
        return false;
    }
    std::string response = recv_line(fd);
    if (response.empty()) {
        std::cerr << "empty response\n";
        return false;
    }
    std::cout << response << "\n";
    return response.rfind("OK", 0) == 0;
}

void print_help() {
    std::cout << "commands:\n"
              << "  ping\n"
              << "  register <username> <password> <nickname>\n"
              << "  login <username> <password>\n"
              << "  get_user <username>\n"
              << "  whoami <token>\n"
              << "  logout <token>\n"
              << "  quit\n";
}

} // namespace

int main(int argc, char* argv[]) {
    std::string host = "127.0.0.1";
    uint16_t port = 18888;
    int command_start = 1;

    if (argc >= 3 && std::string(argv[1]) == "--host") {
        host = argv[2];
        command_start = 3;
    }
    if (argc >= command_start + 2 && std::string(argv[command_start]) == "--port") {
        int parsed = std::stoi(argv[command_start + 1]);
        if (parsed <= 0 || parsed > 65535) {
            std::cerr << "invalid port\n";
            return 1;
        }
        port = static_cast<uint16_t>(parsed);
        command_start += 2;
    }

    int fd = connect_server(host, port);
    if (fd < 0) return 1;

    if (argc > command_start) {
        std::string request = join_args(command_start, argc, argv);
        bool ok = call_once(fd, request);
        ::close(fd);
        return ok ? 0 : 2;
    }

    std::cout << "connected to " << host << ":" << port << "\n";
    print_help();
    std::string line;
    while (true) {
        std::cout << "rpc> " << std::flush;
        if (!std::getline(std::cin, line)) break;
        if (line == "quit" || line == "exit") break;
        if (line == "help") {
            print_help();
            continue;
        }
        if (line.empty()) continue;
        call_once(fd, line);
    }

    ::close(fd);
    return 0;
}

