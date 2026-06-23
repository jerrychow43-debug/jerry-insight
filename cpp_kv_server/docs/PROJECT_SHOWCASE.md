# MiniKV 项目展示文档

MiniKV 是一个使用 C++ 实现的轻量级键值存储服务。项目从最小 TCP 服务端逐步演进到支持 epoll 多客户端、AOF 持久化、HTTP API、Web 管理页和压测脚本的可展示后端项目。

## 项目目标

MiniKV 的目标不是直接替代 Redis，而是通过一个小而完整的项目，把 C++ Linux 后端常见能力串起来：

- Linux socket 网络编程
- epoll 事件驱动模型
- 文本协议解析
- 内存哈希表存储
- AOF 追加日志持久化
- HTTP API 封装
- Web 管理页面
- 压测与性能对比

## 当前功能

- `set key value`：写入键值
- `get key`：查询键值
- `del key`：删除键值
- `keys`：查看所有 key
- `flushall`：清空所有数据
- 多客户端同时连接
- AOF 日志恢复数据
- 浏览器 Web 管理页
- Python 压测脚本

## 架构图

```text
Browser / nc / benchmark
        |
        | TCP / HTTP
        v
+-------------------------+
| C++ MiniKV Server       |
|                         |
|  epoll event loop       |
|  connection manager     |
|  text protocol parser   |
|  HTTP API router        |
+-----------+-------------+
            |
            v
+-------------------------+
| KvStore                 |
| unordered_map           |
| AOF append log          |
+-----------+-------------+
            |
            v
      data/kv.aof
```

## 技术点说明

### 1. TCP 服务端

服务端通过 `socket`、`bind`、`listen` 创建监听端口，客户端可以通过 `nc` 或浏览器连接。

### 2. epoll 多客户端

早期版本一次只能处理一个客户端，升级后使用 `epoll_wait` 统一监听：

- 新连接事件
- 客户端读事件
- 客户端写事件
- 客户端断开事件

这样服务端可以同时维护多个连接。

### 3. KV 存储

内存中使用 `std::unordered_map<std::string, std::string>` 保存数据：

```text
name -> Jerry
city -> shanghai
```

### 4. AOF 持久化

最初版本每次 `set/del` 都重写整个 `kv.db`，写入性能较差。后来改成 AOF 追加日志：

```text
set name Jerry
set city shanghai
del name
flushall
```

服务端启动时读取 `data/kv.aof`，按顺序回放操作，恢复内存状态。

### 5. HTTP API 和 Web 页面

同一个服务端既支持文本命令，也支持浏览器访问：

```text
GET /api/set?key=name&value=Jerry
GET /api/get?key=name
GET /api/del?key=name
GET /api/keys
GET /api/flushall
```

浏览器打开：

```text
http://127.0.0.1:18080/
```

即可使用 Web 管理页进行 Set、Get、Delete、Clear All。

## 编译运行

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro/cpp_kv_server
make clean
make
./kv_server 18080
```

命令行测试：

```bash
nc 127.0.0.1 18080
```

浏览器访问：

```text
http://127.0.0.1:18080/
```

## 压测方式

```bash
python3 tools/bench.py --port 18080 -n 10000
```

一次压测结果示例：

```text
AOF 前：
set: 10000 requests in 77.9681s, qps=128.26
get: 10000 requests in 0.4753s, qps=21041.02

AOF 后：
set: 10000 requests in 25.0381s, qps=399.39
get: 10000 requests in 0.5444s, qps=18369.09
```

说明：当前项目运行在 WSL 的 `/mnt/c` Windows 文件系统下，磁盘写入会偏慢。后续如果把项目移动到 WSL Linux 原生目录，例如 `~/projects/minikv`，写入性能会更好。

## 项目演进过程

```text
V1 单客户端 TCP KV Server
V2 epoll 多客户端
V3 全量文件持久化
V4 AOF 追加日志
V5 压测脚本
V6 HTTP API + Web 管理页
```

## 后续可优化点

- AOF 文件常驻打开，减少每次写入 open/close 开销
- AOF rewrite，压缩历史日志
- 增加日志文件 `logs/kv.log`
- 支持过期时间 TTL
- 支持简单认证 token
- 拆分源码结构，形成更清晰的模块目录
- 增加 Dockerfile

## 简历描述示例

MiniKV：基于 C++ Linux socket/epoll 实现的轻量级键值存储服务，支持多客户端并发连接、文本协议、AOF 追加日志持久化、HTTP API、Web 管理页和 Python 压测脚本。项目用于实践 Reactor/epoll 网络模型、KV 存储设计、持久化策略与性能分析。
