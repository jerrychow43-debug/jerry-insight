#include <algorithm>
#include <arpa/inet.h>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cctype>
#include <cstring>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <netinet/in.h>
#include <sstream>
#include <string>
#include <sys/socket.h>
#include <unistd.h>
#include <unordered_set>
#include <vector>

namespace {

volatile std::sig_atomic_t g_running = 1;
const std::string kUploadDir = "uploads";
const std::string kDataDir = "data";
const std::string kMetaPath = "data/images.tsv";

struct ImageMeta {
    std::string name;
    std::string url;
    std::string content_type;
    std::string uploaded_at;
    uintmax_t size = 0;
    uint64_t views = 0;
};

void handle_signal(int) { g_running = 0; }

std::string status_text(int status) {
    if (status == 200) return "OK";
    if (status == 201) return "Created";
    if (status == 400) return "Bad Request";
    if (status == 404) return "Not Found";
    if (status == 500) return "Internal Server Error";
    return "OK";
}

std::string http_response(int status, const std::string& content_type, const std::string& body) {
    std::ostringstream oss;
    oss << "HTTP/1.1 " << status << " " << status_text(status) << "\r\n"
        << "Content-Type: " << content_type << "; charset=utf-8\r\n"
        << "Content-Length: " << body.size() << "\r\n"
        << "Connection: close\r\n\r\n"
        << body;
    return oss.str();
}

std::string binary_response(int status, const std::string& content_type, const std::string& body) {
    std::ostringstream oss;
    oss << "HTTP/1.1 " << status << " " << status_text(status) << "\r\n"
        << "Content-Type: " << content_type << "\r\n"
        << "Content-Length: " << body.size() << "\r\n"
        << "Connection: close\r\n\r\n";
    return oss.str() + body;
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

int hex_value(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

std::string url_decode(const std::string& input) {
    std::string out;
    for (size_t i = 0; i < input.size(); ++i) {
        if (input[i] == '+') {
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

std::string html_page() {
    return R"HTML(<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mini Image Hosting</title>
<style>
body { margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f8fb; color: #1f2937; }
main { max-width: 980px; margin: 44px auto; padding: 0 20px; }
h1 { font-size: 34px; margin: 0 0 8px; }
.sub { color: #667085; margin-bottom: 24px; }
.panel { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 22px; box-shadow: 0 8px 24px rgba(15,23,42,.06); margin-bottom: 18px; }
input[type=file] { display: block; width: 100%; box-sizing: border-box; padding: 12px; border: 1px dashed #98a2b3; border-radius: 8px; background: #f9fafb; margin-bottom: 14px; }
button { padding: 11px 16px; border: 0; border-radius: 6px; background: #2563eb; color: #fff; font-weight: 700; cursor: pointer; }
button.secondary { background: #475467; margin-left: 8px; }
button.danger { background: #dc2626; margin-left: 8px; padding: 8px 10px; }
pre { min-height: 90px; white-space: pre-wrap; background: #101828; color: #d1fadf; padding: 14px; border-radius: 8px; overflow: auto; }
.preview { margin-top: 18px; }
.preview img { max-width: 100%; max-height: 420px; border-radius: 8px; border: 1px solid #e5e7eb; }
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 14px; }
.card { border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #fff; }
.card img { width: 100%; height: 140px; object-fit: cover; display: block; background: #f2f4f7; }
.card .meta { padding: 10px; font-size: 13px; color: #475467; }
.card a { display: inline-block; margin-top: 6px; color: #2563eb; word-break: break-all; }
.card .row { display: flex; gap: 8px; align-items: center; justify-content: space-between; }
a { color: #2563eb; }
</style>
</head>
<body>
<main>
<h1>Mini Image Hosting</h1>
<div class="sub">C++ HTTP 图片上传服务，保存图片并返回访问链接。</div>
<section class="panel">
<input id="file" type="file" accept="image/*">
<button onclick="upload()">Upload</button>
<button class="secondary" onclick="loadImages()">Refresh Gallery</button>
<pre id="result">ready</pre>
<div class="preview" id="preview"></div>
</section>
<section class="panel">
<h2>Uploaded Images</h2>
<div class="gallery" id="gallery"></div>
</section>
</main>
<script>
function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 / 1024).toFixed(2) + ' MB';
}
function formatTime(ts) {
  const n = Number(ts);
  if (!n) return '-';
  return new Date(n * 1000).toLocaleString();
}
async function upload() {
  const file = document.getElementById('file').files[0];
  if (!file) { result.textContent = '请选择一张图片'; return; }
  const form = new FormData();
  form.append('image', file);
  result.textContent = 'uploading...';
  const res = await fetch('/upload', { method: 'POST', body: form });
  const data = await res.json();
  result.textContent = JSON.stringify(data, null, 2);
  if (data.ok && data.url) {
    preview.innerHTML = `<p><a href="${data.url}" target="_blank">${data.url}</a></p><img src="${data.url}" alt="uploaded">`;
  }
  await loadImages(false);
}
async function deleteImage(name) {
  if (!confirm('Delete ' + name + '?')) return;
  const res = await fetch('/api/delete?name=' + encodeURIComponent(name));
  const data = await res.json();
  result.textContent = JSON.stringify(data, null, 2);
  await loadImages(false);
}
async function loadImages(show = true) {
  const res = await fetch('/api/images');
  const data = await res.json();
  const box = document.getElementById('gallery');
  box.innerHTML = '';
  for (const img of data.images || []) {
    const div = document.createElement('div');
    div.className = 'card';
    div.innerHTML = `<img src="${img.url}" alt="${img.name}"><div class="meta"><div>${img.name}</div><div>${formatSize(img.size)}</div><div>${formatTime(img.uploaded_at)}</div><div>Views: ${img.views || 0}</div><div class="row"><a href="${img.url}" target="_blank">open</a><button class="danger" onclick="deleteImage('${img.name.replaceAll("'", "\\'")}')">Delete</button></div></div>`;
    box.appendChild(div);
  }
  if (show) result.textContent = JSON.stringify(data, null, 2);
}
loadImages(false);
</script>
</body>
</html>)HTML";
}

std::string extension_from_content_type(const std::string& type) {
    if (type.find("image/png") != std::string::npos) return ".png";
    if (type.find("image/jpeg") != std::string::npos) return ".jpg";
    if (type.find("image/gif") != std::string::npos) return ".gif";
    if (type.find("image/webp") != std::string::npos) return ".webp";
    return ".bin";
}

std::string content_type_from_path(const std::string& path) {
    if (path.ends_with(".png")) return "image/png";
    if (path.ends_with(".jpg") || path.ends_with(".jpeg")) return "image/jpeg";
    if (path.ends_with(".gif")) return "image/gif";
    if (path.ends_with(".webp")) return "image/webp";
    return "application/octet-stream";
}

std::string make_file_name(const std::string& ext) {
    auto now = std::chrono::system_clock::now().time_since_epoch();
    auto us = std::chrono::duration_cast<std::chrono::microseconds>(now).count();
    return std::to_string(us) + ext;
}

std::string now_epoch() {
    auto now = std::chrono::system_clock::now();
    return std::to_string(std::chrono::system_clock::to_time_t(now));
}

std::string find_header(const std::string& request, const std::string& name) {
    std::string key = name + ":";
    size_t pos = request.find(key);
    if (pos == std::string::npos) return "";
    pos += key.size();
    while (pos < request.size() && request[pos] == ' ') ++pos;
    size_t end = request.find("\r\n", pos);
    if (end == std::string::npos) return "";
    return request.substr(pos, end - pos);
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

std::vector<ImageMeta> load_metadata() {
    std::vector<ImageMeta> images;
    std::ifstream in(kMetaPath);
    if (!in.is_open()) return images;

    std::string line;
    while (std::getline(in, line)) {
        auto parts = split_tsv(line);
        if (parts.size() < 5) continue;
        ImageMeta img;
        img.name = parts[0];
        img.url = parts[1];
        img.size = static_cast<uintmax_t>(std::stoull(parts[2]));
        img.content_type = parts[3];
        img.uploaded_at = parts[4];
        if (parts.size() >= 6) {
            img.views = static_cast<uint64_t>(std::stoull(parts[5]));
        }
        if (std::filesystem::exists(std::filesystem::path(kUploadDir) / img.name)) {
            images.push_back(img);
        }
    }
    return images;
}

void save_metadata(const std::vector<ImageMeta>& images) {
    std::filesystem::create_directories(kDataDir);
    std::ofstream out(kMetaPath, std::ios::trunc);
    for (const auto& img : images) {
        out << img.name << '\t' << img.url << '\t' << img.size << '\t' << img.content_type << '\t' << img.uploaded_at << '\t' << img.views << '\n';
    }
}

void append_metadata(const ImageMeta& img) {
    std::filesystem::create_directories(kDataDir);
    std::ofstream out(kMetaPath, std::ios::app);
    out << img.name << '\t' << img.url << '\t' << img.size << '\t' << img.content_type << '\t' << img.uploaded_at << '\t' << img.views << '\n';
}

std::vector<ImageMeta> list_all_images() {
    std::filesystem::create_directories(kUploadDir);
    auto images = load_metadata();
    std::unordered_set<std::string> known;
    for (const auto& img : images) known.insert(img.name);

    for (const auto& entry : std::filesystem::directory_iterator(kUploadDir)) {
        if (!entry.is_regular_file()) continue;
        std::filesystem::path path = entry.path();
        std::string name = path.filename().string();
        if (known.count(name) > 0) continue;
        std::string ct = content_type_from_path(path.string());
        if (ct == "application/octet-stream") continue;
        images.push_back({name, "/uploads/" + name, ct, "", std::filesystem::file_size(path), 0});
    }

    std::sort(images.begin(), images.end(), [](const auto& a, const auto& b) {
        return a.name > b.name;
    });
    return images;
}

std::string images_json() {
    auto images = list_all_images();
    std::string body = "{\"ok\":true,\"images\":[";
    for (size_t i = 0; i < images.size(); ++i) {
        const auto& img = images[i];
        if (i > 0) body += ",";
        body += "{\"name\":\"" + json_escape(img.name) + "\","
                "\"url\":\"" + json_escape(img.url) + "\","
                "\"size\":" + std::to_string(img.size) + ","
                "\"content_type\":\"" + json_escape(img.content_type) + "\","
                "\"uploaded_at\":\"" + json_escape(img.uploaded_at) + "\","
                "\"views\":" + std::to_string(img.views) + "}";
    }
    body += "]}";
    return http_response(200, "application/json", body);
}

void increment_view_count(const std::string& name) {
    auto images = load_metadata();
    bool changed = false;
    for (auto& img : images) {
        if (img.name == name) {
            ++img.views;
            changed = true;
            break;
        }
    }
    if (changed) {
        save_metadata(images);
    }
}
bool delete_image_by_name(const std::string& name) {
    if (name.empty() || name.find("..") != std::string::npos || name.find('/') != std::string::npos) {
        return false;
    }
    std::filesystem::path path = std::filesystem::path(kUploadDir) / name;
    bool removed_file = !std::filesystem::exists(path) || std::filesystem::remove(path);
    auto images = load_metadata();
    images.erase(std::remove_if(images.begin(), images.end(), [&](const auto& img) { return img.name == name; }), images.end());
    save_metadata(images);
    return removed_file;
}

std::string handle_upload(const std::string& request) {
    std::string content_type = find_header(request, "Content-Type");
    size_t boundary_pos = content_type.find("boundary=");
    if (boundary_pos == std::string::npos) {
        return http_response(400, "application/json", "{\"ok\":false,\"error\":\"missing boundary\"}");
    }

    std::string boundary = "--" + content_type.substr(boundary_pos + 9);
    size_t body_pos = request.find("\r\n\r\n");
    if (body_pos == std::string::npos) {
        return http_response(400, "application/json", "{\"ok\":false,\"error\":\"missing body\"}");
    }
    body_pos += 4;

    size_t part_start = request.find(boundary, body_pos);
    if (part_start == std::string::npos) {
        return http_response(400, "application/json", "{\"ok\":false,\"error\":\"missing part\"}");
    }
    part_start += boundary.size() + 2;

    size_t part_header_end = request.find("\r\n\r\n", part_start);
    if (part_header_end == std::string::npos) {
        return http_response(400, "application/json", "{\"ok\":false,\"error\":\"missing part header\"}");
    }

    std::string part_header = request.substr(part_start, part_header_end - part_start);
    std::string content_type_for_file = part_header;
    std::string ext = extension_from_content_type(part_header);
    if (ext == ".bin") {
        return http_response(400, "application/json", "{\"ok\":false,\"error\":\"unsupported image type\"}");
    }

    size_t data_start = part_header_end + 4;
    size_t data_end = request.find("\r\n" + boundary, data_start);
    if (data_end == std::string::npos || data_end <= data_start) {
        return http_response(400, "application/json", "{\"ok\":false,\"error\":\"missing file data\"}");
    }

    std::string file_data = request.substr(data_start, data_end - data_start);
    if (file_data.size() > 10 * 1024 * 1024) {
        return http_response(400, "application/json", "{\"ok\":false,\"error\":\"file too large\"}");
    }

    std::filesystem::create_directories(kUploadDir);
    std::string filename = make_file_name(ext);
    std::filesystem::path path = std::filesystem::path(kUploadDir) / filename;
    std::ofstream out(path, std::ios::binary);
    if (!out.is_open()) {
        return http_response(500, "application/json", "{\"ok\":false,\"error\":\"save failed\"}");
    }
    out.write(file_data.data(), static_cast<std::streamsize>(file_data.size()));
    out.close();

    std::string url = "/uploads/" + filename;
    std::string saved_content_type = content_type_from_path(filename);
    ImageMeta meta{filename, url, saved_content_type, now_epoch(), file_data.size(), 0};
    append_metadata(meta);

    std::string body = "{\"ok\":true,\"url\":\"" + url + "\",\"size\":" + std::to_string(file_data.size()) + "}";
    return http_response(201, "application/json", body);
}

std::string serve_upload(const std::string& target) {
    std::string prefix = "/uploads/";
    if (target.rfind(prefix, 0) != 0) return http_response(404, "text/plain", "not found");
    std::string name = target.substr(prefix.size());
    if (name.find("..") != std::string::npos || name.find('/') != std::string::npos) {
        return http_response(400, "text/plain", "bad path");
    }

    std::filesystem::path path = std::filesystem::path(kUploadDir) / name;
    std::ifstream in(path, std::ios::binary);
    if (!in.is_open()) return http_response(404, "text/plain", "not found");
    increment_view_count(name);
    std::string body((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    return binary_response(200, content_type_from_path(path.string()), body);
}

std::string handle_request(const std::string& request) {
    std::istringstream iss(request);
    std::string method, target, version;
    iss >> method >> target >> version;
    if (method == "GET" && (target == "/" || target == "/index.html")) return http_response(200, "text/html", html_page());
    if (method == "GET" && target == "/api/images") return images_json();
    if (method == "GET" && target.rfind("/api/delete", 0) == 0) {
        bool ok = delete_image_by_name(query_value(target, "name"));
        return http_response(ok ? 200 : 400, "application/json", ok ? "{\"ok\":true}" : "{\"ok\":false,\"error\":\"delete failed\"}");
    }
    if (method == "GET" && target.rfind("/uploads/", 0) == 0) return serve_upload(target);
    if (method == "POST" && target == "/upload") return handle_upload(request);
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
    char buf[8192];
    size_t expected_total = 0;
    while (true) {
        ssize_t n = ::recv(fd, buf, sizeof(buf), 0);
        if (n < 0) { if (errno == EINTR) continue; break; }
        if (n == 0) break;
        request.append(buf, static_cast<size_t>(n));
        size_t header_end = request.find("\r\n\r\n");
        if (header_end != std::string::npos && expected_total == 0) {
            std::string len = find_header(request, "Content-Length");
            expected_total = header_end + 4;
            if (!len.empty()) expected_total += static_cast<size_t>(std::stoul(len));
        }
        if (expected_total > 0 && request.size() >= expected_total) break;
        if (request.size() > 12 * 1024 * 1024) break;
    }
    return request;
}

void handle_client(int fd) {
    std::string request = read_request(fd);
    std::string response = request.empty() ? http_response(400, "text/plain", "bad request") : handle_request(request);
    send_all(fd, response);
}

} // namespace

int main(int argc, char* argv[]) {
    uint16_t port = 19090;
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
    int listen_fd = create_listen_socket(port);
    if (listen_fd < 0) return 1;
    std::cout << "image_hosting listening on http://127.0.0.1:" << port << "\n";
    while (g_running) {
        sockaddr_in client_addr {};
        socklen_t len = sizeof(client_addr);
        int client_fd = ::accept(listen_fd, reinterpret_cast<sockaddr*>(&client_addr), &len);
        if (client_fd < 0) {
            if (errno == EINTR) continue;
            std::cerr << "accept failed: " << std::strerror(errno) << "\n";
            break;
        }
        handle_client(client_fd);
        ::close(client_fd);
    }
    ::close(listen_fd);
    std::cout << "image_hosting stopped\n";
    return 0;
}



