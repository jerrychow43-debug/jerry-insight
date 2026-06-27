# MiniChat / cpp_rpc_lab 面试复盘文档

这份文档用于面试前快速吃透 Linux 聊天项目。重点不是把项目吹得很大，而是把你真实做过的东西讲清楚：Linux 网络编程、C++ 服务端、HTTP/SSE、RPC、并发、数据持久化、Docker 部署。

## 1. 项目一句话介绍

这是一个基于 Linux Socket 和 C++20 实现的轻量级网页聊天室项目。项目拆成两个服务：

- `cpp_rpc_lab`：负责用户注册、登录、会话 token、用户信息查询。
- `cpp_minichat`：负责网页聊天、消息收发、在线用户列表、私聊、公聊、搜索、SSE 实时推送。

可以这样向面试官介绍：

> 我做了一个 C++ Linux 聊天室练手项目，底层没有用现成 Web 框架，而是自己用 socket 实现 TCP 监听、HTTP 请求解析、响应返回和 SSE 实时推送。用户系统单独拆成一个简单 RPC 服务，聊天室服务通过 TCP 文本协议调用 RPC 服务完成登录鉴权。

## 2. 项目架构

```text
Browser
  |
  | HTTP / EventSource(SSE)
  v
cpp_minichat  :19191
  |
  | TCP text RPC
  v
cpp_rpc_lab   :18888

Data files:
- cpp_minichat/data/messages.tsv
- cpp_rpc_lab/data/users.tsv
```

核心链路：

1. 浏览器访问 `cpp_minichat` 的网页。
2. 用户注册或登录时，`cpp_minichat` 通过 TCP 调用 `cpp_rpc_lab`。
3. RPC 服务校验用户并返回 token。
4. 聊天服务用 token 识别用户身份。
5. 用户发消息后，消息写入内存和 TSV 文件。
6. 前端通过 SSE 连接接收新消息和在线用户更新。

## 3. 已实现功能

### 聊天服务 cpp_minichat

- 自己实现 HTTP Server。
- 支持浏览器访问内置 HTML 页面。
- 支持用户注册、登录、退出。
- 支持公聊消息。
- 支持指定用户私聊。
- 支持按房间区分消息。
- 支持消息搜索。
- 支持清空消息。
- 支持在线用户列表。
- 支持 SSE 实时推送消息。
- 支持把消息持久化到 `messages.tsv`。
- 支持 Docker Compose 部署。

### RPC 用户服务 cpp_rpc_lab

- 自己实现 TCP RPC Server。
- 支持 `register` 注册。
- 支持 `login` 登录。
- 支持 `whoami` 根据 token 查询用户。
- 支持 `get_user` 查询用户信息。
- 支持 `logout` 删除会话。
- 支持 `ping` 健康检查。
- 用户数据持久化到 `users.tsv`。

## 4. 核心接口

### MiniChat HTTP 接口

| 接口 | 作用 |
| --- | --- |
| `/` | 返回内置聊天页面 |
| `/api/auth_register` | 注册用户，内部调用 RPC |
| `/api/auth_login` | 登录用户，内部调用 RPC |
| `/api/auth_me` | 根据 token 查询当前用户 |
| `/api/auth_logout` | 退出登录 |
| `/api/send` | 发送消息 |
| `/api/messages` | 获取消息列表 |
| `/api/search` | 搜索消息 |
| `/api/clear` | 清空消息 |
| `/api/users` | 获取在线用户 |
| `/events` | SSE 实时推送 |

### RPC 文本协议

| 命令 | 作用 |
| --- | --- |
| `register username password nickname` | 注册 |
| `login username password` | 登录并返回 token |
| `whoami token` | 根据 token 查当前用户 |
| `get_user username` | 查用户资料 |
| `logout token` | 退出登录 |
| `ping` | 健康检查 |

这个 RPC 不是 gRPC，也不是 HTTP RPC，而是一个自己定义的 TCP 文本协议。优点是简单、适合学习网络通信；缺点是没有成熟协议的序列化、错误码、超时、重试、版本管理。

## 5. 关键数据结构

### 消息结构

```cpp
struct Message {
    int id;
    string room;
    string user;
    string to;
    string text;
    long long ts;
};
```

字段含义：

- `id`：消息自增 ID。
- `room`：房间名。
- `user`：发送者。
- `to`：私聊对象，空字符串表示公聊。
- `text`：消息内容。
- `ts`：时间戳。

### 在线用户

```cpp
unordered_map<string, OnlineUser> g_users;
```

在线用户通过 token 或用户名维护，SSE 连接和接口访问会刷新在线状态。过期用户会根据时间剔除。

### 用户服务数据

```cpp
struct User {
    string username;
    string password;
    string nickname;
};
```

用户数据存储在 `users.tsv`。目前密码是明文保存，这是学习项目里的不足，面试时要主动说明后续会改成哈希加盐。

## 6. Linux / C++ 知识点总览

### 6.1 Socket 服务端生命周期

项目里的服务端基本流程是：

```text
socket()
  -> setsockopt(SO_REUSEADDR)
  -> bind()
  -> listen()
  -> accept()
  -> recv()
  -> send()
  -> close()
```

面试回答：

> 我在项目里没有直接用 Web 框架，而是自己写了 socket 服务端。服务启动后创建 TCP socket，设置端口复用，绑定 `INADDR_ANY`，监听端口。每次 `accept` 拿到一个客户端连接，然后开一个线程处理这个连接。

### 6.2 SO_REUSEADDR

`SO_REUSEADDR` 的作用是允许服务重启后快速重新绑定端口，避免因为 TCP `TIME_WAIT` 状态导致端口暂时不可用。

面试回答：

> 开发时服务经常重启，如果不设置 `SO_REUSEADDR`，可能会遇到 address already in use。设置它之后，服务端重启体验会好很多。

### 6.3 网络字节序

项目使用：

- `htons(port)`：host to network short，把端口转成网络字节序。
- `htonl(INADDR_ANY)`：把监听地址转成网络字节序。

面试回答：

> 网络协议要求统一使用大端字节序，所以服务端绑定端口和地址时需要用 `htons`、`htonl` 做转换。

### 6.4 TCP 是字节流

TCP 不是消息协议，而是字节流协议。一次 `recv` 不一定收到完整 HTTP 请求，也可能收到多个请求片段。

项目处理方式：

- HTTP 请求读取到 `\r\n\r\n` 为止。
- `send_all` 循环发送，避免一次 `send` 没发完。

面试回答：

> 我知道 TCP 没有消息边界，所以读 HTTP 请求时会循环 `recv`，直到读到请求头结束标记。发送响应时也不是只调用一次 `send`，而是写了 `send_all` 保证数据尽量完整发出。

### 6.5 MSG_NOSIGNAL

Linux 下如果对已经断开的连接写数据，进程可能收到 `SIGPIPE`。项目里发送数据时使用 `MSG_NOSIGNAL`，避免服务因为客户端断开而被信号杀掉。

面试回答：

> SSE 长连接里客户端刷新页面或关闭页面很常见，所以服务端写 socket 时要考虑对端断开。用 `MSG_NOSIGNAL` 可以避免 `SIGPIPE` 直接终止进程。

### 6.6 HTTP 请求解析

项目没有引入 HTTP 框架，而是做了最小可用解析：

- 解析请求行：方法、路径、查询参数。
- 解析 Header。
- 支持 GET / POST 的基本处理。
- 从 query 或 body 中读取参数。
- 进行 URL decode。
- 返回 JSON 或 HTML。

局限：

- 不支持完整 HTTP 标准。
- 不支持 chunked body。
- 不适合直接暴露为生产服务。

面试回答：

> 这个项目的 HTTP parser 是为了学习网络协议做的最小实现，不是生产级。真正线上会用 nginx、Boost.Beast、libevent、workflow 或成熟 Web 框架。

### 6.7 JSON 转义

返回 JSON 时必须处理特殊字符，例如：

- 双引号
- 反斜杠
- 换行
- 回车

否则用户输入特殊字符可能导致 JSON 格式损坏。

面试回答：

> 项目里有 `json_escape`，避免用户消息里带引号或换行时把 JSON 返回弄坏。

### 6.8 多线程模型

项目采用简单的 thread-per-connection 模型：

```text
accept 一个连接
  -> 创建一个 detached thread
  -> 在线程里处理请求
```

共享数据：

- `g_messages`
- `g_users`
- `g_next_id`

保护方式：

- 使用 `mutex` 保护共享状态。

优点：

- 实现简单。
- 便于理解并发服务端。

缺点：

- 高并发下线程数量不可控。
- 线程创建销毁成本高。
- 更适合学习项目，不适合大规模生产。

可改进：

- 线程池。
- epoll。
- 非阻塞 IO。
- 事件循环。
- coroutine。

### 6.9 SSE 实时推送

SSE 全称 Server-Sent Events。浏览器通过 `EventSource` 建立一个 HTTP 长连接，服务端持续推送文本事件：

```text
data: {"type":"message","text":"hello"}

```

项目中 `/events` 接口会：

- 返回 `Content-Type: text/event-stream`。
- 保持连接不断开。
- 定期推送消息和在线用户变化。
- 发送 keepalive 注释，避免连接长时间无数据。

SSE 和 WebSocket 的区别：

| 对比 | SSE | WebSocket |
| --- | --- | --- |
| 通信方向 | 服务端到客户端为主 | 双向 |
| 协议 | HTTP 长连接 | 独立升级协议 |
| 浏览器支持 | EventSource 原生支持 | WebSocket 原生支持 |
| 适合场景 | 通知、日志、消息流 | 聊天、游戏、实时协作 |

这个项目虽然是聊天室，但用户发送消息走普通 HTTP，接收新消息走 SSE，所以也能实现实时效果。

面试回答：

> 我这里没有用 WebSocket，而是用 SSE 做消息推送。因为项目规模小，浏览器原生支持 EventSource，实现成本低。发送消息用 HTTP POST，接收消息用 SSE 长连接。

### 6.10 私聊权限过滤

私聊消息不能只靠前端隐藏，服务端必须过滤。

项目里的逻辑：

- 公聊消息：`to` 为空，房间内所有人可见。
- 私聊消息：只有发送者和接收者可见。
- 房间不匹配的消息不可见。

核心思想：

```text
can_view_message(message, current_user, room)
```

面试回答：

> 私聊权限我放在服务端判断，不信任前端。拉取消息和搜索消息时都会判断当前用户是否有权限看这条消息。

### 6.11 RPC 服务拆分

这个项目把用户系统拆到了 `cpp_rpc_lab`，聊天室服务不直接管理用户密码，而是通过 TCP RPC 调用。

好处：

- 练习服务间通信。
- 聊天服务和用户服务职责分离。
- 后续可以替换用户服务实现。

局限：

- 协议比较简单。
- 没有 request id。
- 没有超时重试封装。
- 没有服务发现。
- 没有鉴权加密。

面试回答：

> 我把认证能力拆成了一个独立 RPC 服务，主要是为了练习服务拆分和 TCP 通信。这个 RPC 是简单文本协议，不是生产级方案，但能体现服务间调用的基本流程。

### 6.12 TSV 持久化

项目使用 TSV 文件保存数据：

- 用户：`users.tsv`
- 消息：`messages.tsv`

TSV 是 tab 分隔文本。实现简单，方便调试。

不足：

- 并发写入能力弱。
- 查询效率低。
- 数据一致性能力弱。
- 不适合大数据量。

可改进：

- SQLite。
- MySQL / PostgreSQL。
- Redis 做在线状态。

### 6.13 Docker Compose 部署

项目支持通过 Docker Compose 启动两个服务：

```text
rpc service
minichat service
```

Compose 里：

- `rpc` 暴露内部 `18888`。
- `minichat` 对外暴露 `19191`。
- `minichat` 通过服务名 `rpc` 访问 RPC 服务。
- 数据通过 volume 持久化。

面试回答：

> 我用 Docker Compose 把两个 C++ 服务编排起来。聊天室容器通过服务名访问 RPC 容器，这样本地和云服务器部署时配置比较统一。

## 7. 核心流程讲解

### 7.1 用户注册

```text
Browser
  -> POST /api/auth_register
  -> MiniChat 解析 username/password/nickname
  -> MiniChat TCP 连接 RPC 服务
  -> 发送 register 命令
  -> RPC 校验用户名和密码
  -> 写入 users.tsv
  -> 返回 OK
  -> MiniChat 返回 JSON
```

### 7.2 用户登录

```text
Browser
  -> POST /api/auth_login
  -> MiniChat 调用 RPC login
  -> RPC 校验密码
  -> 生成 token
  -> 保存 token -> username 映射
  -> 返回 token
  -> 前端 localStorage 保存 token
```

### 7.3 发送消息

```text
Browser
  -> POST /api/send
  -> MiniChat 根据 token 调 whoami
  -> 获取当前用户名
  -> 构造 Message
  -> 加锁写入 g_messages
  -> append 到 messages.tsv
  -> 返回发送成功
```

### 7.4 接收消息

```text
Browser
  -> EventSource('/events')
  -> MiniChat 保持 SSE 长连接
  -> 服务端检查新消息
  -> 根据当前用户过滤可见消息
  -> 推送 data: JSON
```

### 7.5 私聊

```text
发送者发送消息时带 to 字段
  -> 服务端保存 to
  -> 拉取或推送消息时调用 can_view_message
  -> 只有 sender / receiver 能看到
```

## 8. 实现过程复盘

可以按这个顺序向面试官讲：

1. 先实现最小 TCP Server，能监听端口并返回固定 HTTP 响应。
2. 再实现基础 HTTP 解析，根据路径分发不同接口。
3. 写内置 HTML 页面，让浏览器可以直接访问。
4. 实现消息结构和 `/api/send`、`/api/messages`。
5. 加入文件持久化，把消息写入 TSV。
6. 增加 SSE，让前端不用轮询也能收到新消息。
7. 增加在线用户列表和心跳更新。
8. 增加私聊字段和服务端权限过滤。
9. 单独实现 RPC 用户服务，支持注册、登录和 token。
10. 聊天服务接入 RPC，不再自己处理用户认证。
11. 写 Makefile、run 脚本和 Docker Compose，方便启动部署。

## 9. 遇到的问题和解决方式

### 问题 1：服务重启后端口被占用

现象：

```text
bind failed: Address already in use
```

原因：

TCP 连接关闭后可能处于 `TIME_WAIT`，端口短时间不能重新绑定。

解决：

使用 `setsockopt` 设置 `SO_REUSEADDR`。

面试回答：

> 这个问题让我理解了 TCP 连接生命周期和服务端端口复用。开发阶段频繁重启服务，`SO_REUSEADDR` 很必要。

### 问题 2：浏览器刷新后 SSE 连接断开

现象：

用户刷新页面或关闭浏览器后，服务端继续写 socket，可能报错或触发信号。

解决：

- 发送时使用 `MSG_NOSIGNAL`。
- 写失败就退出 SSE 循环并关闭连接。
- SSE 中加入 keepalive。

### 问题 3：一次 send 不一定发完

现象：

响应数据较大时，一次 `send` 可能只发送部分数据。

解决：

实现 `send_all`，循环发送直到全部发送完成或出错。

### 问题 4：TCP recv 没有消息边界

现象：

一次 `recv` 不一定拿到完整 HTTP 请求头。

解决：

循环读取，直到出现 `\r\n\r\n`。

### 问题 5：多线程访问共享消息列表有竞态

现象：

多个用户同时发消息、查消息时，共享 vector 和在线用户 map 可能并发读写。

解决：

使用 `mutex` 加锁保护共享状态。

### 问题 6：用户消息包含引号导致 JSON 错误

现象：

用户发送 `"hello"` 或换行，返回 JSON 可能被破坏。

解决：

实现 `json_escape`，返回 JSON 前统一转义。

### 问题 7：私聊不能只靠前端隐藏

现象：

如果只在前端隐藏私聊消息，用户可以直接调用接口拿到别人的私聊。

解决：

在服务端实现 `can_view_message`，所有消息获取和搜索都走服务端权限判断。

### 问题 8：服务拆分后本地地址和容器地址不同

现象：

本地运行时 RPC host 可能是 `127.0.0.1`，Docker Compose 里应该用服务名 `rpc`。

解决：

把 RPC host 和 port 做成启动参数或环境配置，Compose 中使用服务名访问。

## 10. 面试高频问题和回答

### Q1：你这个项目最大的技术点是什么？

回答：

> 最大的技术点是我没有用现成 Web 框架，而是自己实现了 Linux socket 服务端，包括 TCP 监听、HTTP 基础解析、响应发送、SSE 长连接推送和多线程并发处理。另外我把用户认证拆成了一个独立 TCP RPC 服务，练习了服务间调用和简单协议设计。

### Q2：为什么用 SSE，不用 WebSocket？

回答：

> 这个项目里消息发送可以走普通 HTTP，服务端只需要把新消息推给浏览器，所以 SSE 足够。SSE 实现简单，浏览器原生 EventSource 支持，适合通知流和消息流。如果要做更复杂的双向实时交互，比如已读回执、输入中状态、多人协作，我会考虑 WebSocket。

### Q3：你这个项目并发怎么处理？

回答：

> 目前是 thread-per-connection，每个连接一个线程处理。共享的消息列表、在线用户 map 和消息 ID 用 mutex 保护。这个模型适合学习和小规模 demo，但高并发下线程数量会成为瓶颈，后续可以改成线程池或 epoll 事件驱动。

### Q4：你怎么保证私聊安全？

回答：

> 私聊权限是在服务端过滤的。消息有 `to` 字段，空表示公聊，不为空表示私聊。获取消息、搜索消息、SSE 推送时都会判断当前用户是不是发送者或接收者，不依赖前端隐藏。

### Q5：你的 RPC 是怎么实现的？

回答：

> RPC 服务本质是一个 TCP Server，我定义了简单文本命令，比如 `login username password`、`whoami token`。聊天室服务作为 client 连接 RPC 服务，发送命令并读取响应。它不是生产级 RPC，但让我理解了服务拆分、协议设计、请求响应和 token 会话管理。

### Q6：这个项目有什么不足？

回答：

> 不足我比较清楚。第一，HTTP parser 是最小实现，不完整。第二，密码现在是明文存储，应该改成加盐哈希。第三，持久化用 TSV，不适合高并发和复杂查询。第四，并发模型是每连接一线程，高并发下不够好。第五，token 没有完善过期和刷新机制。后续我会用 SQLite/MySQL、线程池或 epoll、HTTPS、密码哈希和更完整的鉴权来改进。

### Q7：为什么不用数据库？

回答：

> 这个项目第一目标是练 Linux 网络编程，所以我先用 TSV 降低外部依赖，把重点放在 socket、HTTP、SSE、RPC 和并发上。后续如果面向真实使用，会把用户和消息迁移到 SQLite 或 MySQL。

### Q8：Docker Compose 起了什么作用？

回答：

> 它把用户 RPC 服务和聊天室服务一起编排。聊天室容器依赖 RPC 容器，通过服务名 `rpc` 通信，对外只暴露聊天服务端口。这样部署时不用手动开两个终端分别启动服务。

### Q9：如果让你优化性能，你会怎么做？

回答：

> 我会先把 thread-per-connection 改成线程池或 epoll，减少线程数量；消息存储从 vector/TSV 换成数据库；在线状态放 Redis；SSE 推送做更细的增量；RPC 调用加超时、重试和连接池。

### Q10：这个项目和普通 CRUD 有什么区别？

回答：

> 它更偏底层服务端练习。普通 CRUD 通常依赖 Web 框架和数据库，而这个项目自己处理 TCP 连接、HTTP 协议、SSE 长连接、并发锁和服务间 TCP 调用，所以更能体现 Linux/C++ 网络编程基础。

## 11. 项目不足和后续改进

面试时主动说不足反而更可信：

- 密码应改为 bcrypt / Argon2 / salted hash。
- token 应增加过期时间和刷新机制。
- HTTP parser 应替换为成熟库。
- 文件持久化应替换为 SQLite / MySQL。
- 在线用户状态可放 Redis。
- 并发模型可升级为线程池或 epoll。
- RPC 协议可增加 request id、错误码、超时、重试。
- 部署时应加 Nginx 反向代理和 HTTPS。
- 增加日志、监控和压测。
- 增加单元测试和接口测试。

## 12. 简历写法

推荐写法：

> 基于 C++20 和 Linux Socket 实现轻量级网页聊天室，手写 TCP 服务端、HTTP 请求解析、JSON 响应、SSE 实时推送和多线程连接处理；拆分独立 RPC 用户服务，实现注册、登录、token 会话、用户查询等能力；使用 mutex 保证消息列表和在线用户状态的线程安全，基于 TSV 完成消息与用户数据持久化，并通过 Docker Compose 编排双服务部署。

不要写：

- 不要写高并发聊天室平台。
- 不要写生产级 IM 系统。
- 不要写用了成熟 RPC 框架。
- 不要写用了 WebSocket，除非代码真的改了。
- 不要写数据库存储，当前是 TSV。

## 13. 30 秒口头介绍

> 我做过一个 C++ Linux 聊天室项目，主要是为了练底层网络编程。项目分两个服务，一个是聊天 HTTP 服务，一个是用户 RPC 服务。聊天服务自己用 socket 实现监听、HTTP 解析、接口分发和 SSE 实时推送，支持公聊、私聊、在线用户和消息搜索。用户服务也是 TCP Server，提供注册、登录、token 查询。这个项目让我比较系统地练了 socket、TCP 字节流、多线程、mutex、简单 RPC、SSE 和 Docker Compose 部署。

## 14. 2 分钟详细介绍

> 这个项目是一个 C++20 写的轻量级网页聊天室。我没有使用现成 Web 框架，而是自己基于 Linux socket 实现服务端。服务启动后创建 TCP socket，设置 `SO_REUSEADDR`，绑定端口并 listen。每次 accept 到连接后，用一个线程处理请求。
>
> 聊天服务里我实现了基础 HTTP 解析，包括请求行、路径、query、body，然后根据不同路径分发到接口。前端页面是内置 HTML，用户可以注册登录、发公聊、发私聊、搜索消息、查看在线用户。实时消息推送用的是 SSE，也就是浏览器 EventSource 建立长连接，服务端持续发送 `text/event-stream` 数据。
>
> 用户认证我拆成了独立的 RPC 服务。RPC 服务也是 C++ socket server，定义了简单文本协议，比如 register、login、whoami、logout。聊天室服务收到登录请求后，会作为 TCP client 去调用 RPC 服务。登录成功后 RPC 返回 token，后续聊天接口通过 token 查当前用户。
>
> 并发方面，目前是每连接一个线程，共享的消息列表、在线用户表和消息 ID 用 mutex 保护。持久化方面，用 TSV 文件保存用户和消息，虽然不适合生产，但对学习项目来说方便调试。部署方面，我写了 Makefile、启动脚本和 Docker Compose，可以同时启动 RPC 服务和聊天服务。
>
> 这个项目的不足我也比较清楚，比如 HTTP parser 不是完整实现、密码应该加盐哈希、TSV 应该换数据库、并发模型后续可以改成 epoll 或线程池。但它比较完整地覆盖了 Linux C++ 服务端的核心基础。

## 15. 面试前必背关键词

- Linux Socket
- TCP 字节流
- `socket / bind / listen / accept / recv / send`
- `SO_REUSEADDR`
- `htons / htonl`
- `send_all`
- `MSG_NOSIGNAL`
- HTTP 最小解析
- URL decode
- JSON escape
- SSE / EventSource
- 多线程
- mutex
- 线程安全
- RPC 文本协议
- token 会话
- 私聊权限服务端过滤
- TSV 持久化
- Docker Compose

## 16. 面试时最重要的态度

这个项目不要包装成大型生产项目。最好的讲法是：

> 这是我为了补 Linux/C++ 网络编程能力做的完整练习项目。它不是生产级 IM，但我从底层实现了一遍服务端链路，并且知道它现在的不足和下一步怎么改。

这样讲最稳，也最容易让面试官继续问你能答上的问题。
