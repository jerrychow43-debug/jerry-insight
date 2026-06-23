# MiniChat 项目展示说明

## 项目一句话介绍

MiniChat 是一个用 C++ 写的小型 Web 聊天系统，并接入了独立的 C++ RPC 用户服务。浏览器访问 MiniChat 页面，MiniChat 负责聊天、实时推送和消息权限；`cpp_rpc_lab` 负责注册、登录、token 校验和退出登录。

## 为什么做这个项目

这个项目适合展示 Linux C++ 后端开发能力。它不是只写算法题，而是把网络编程、HTTP 协议、SSE 长连接、RPC 服务调用、登录态、状态管理、文件持久化和前后端联调串成了一个能运行的小产品。

## 已完成能力

- HTTP 服务端：浏览器可以直接打开聊天页面
- RPC 用户服务：MiniChat 通过 TCP RPC 调用 `cpp_rpc_lab`
- 注册登录：页面支持注册、登录、退出登录
- Token 校验：刷新页面后通过 `/api/auth_me` 校验登录态
- 消息发送：通过 `/api/send` 接收浏览器发来的消息
- 历史消息拉取：通过 `/api/messages` 返回历史消息
- 实时推送：通过 `/events` 建立 SSE 长连接，服务端主动推送新消息
- 多线程连接处理：每个客户端连接独立处理，避免长连接阻塞其他请求
- 在线列表：通过 `/api/users` 维护最近活跃用户
- 消息搜索：按当前房间和当前身份搜索消息，私聊结果继续遵守权限过滤
- 演示清理：可以清空当前房间测试消息，并同步重写持久化文件
- 房间隔离：不同房间的消息互不影响
- 私聊过滤：私聊消息只有发送者和接收者能看到
- 文件持久化：服务重启后还能加载历史消息
- 旧数据兼容：兼容之前没有房间或没有私聊字段的消息格式

## 演示脚本

1. 一键启动服务：

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro/cpp_minichat
chmod +x run_all.sh
./run_all.sh
```

2. 浏览器打开：

```text
http://127.0.0.1:19191/
```

3. 打开三个窗口并分别登录：

- 窗口 A 登录 `jerry`
- 窗口 B 登录 `tom`
- 窗口 C 登录 `alice`

4. 演示公开消息：

- `private to` 留空
- Jerry 发一条消息
- Tom 和 Alice 都能看到

5. 演示私聊：

- Jerry 的 `private to` 填 `tom`
- Jerry 再发一条消息
- Jerry 和 Tom 能看到
- Alice 看不到这条私聊

6. 演示房间隔离：

- 点击 `cpp` 房间
- 发一条消息
- 切回 `general`，这条消息不会出现在 general 里

7. 演示登录态：

- 刷新页面，token 有效时仍保持登录
- 点击 Logout，再尝试发消息，会提示需要登录

## 项目讲解重点

### 1. C++ 服务端怎么响应浏览器

浏览器访问页面或调用接口时，本质上都是给 C++ 服务端发 HTTP 请求。服务端从 socket 读到请求字符串，再根据路径分发到不同函数。

核心入口：

```cpp
std::string handle_request(const std::string& request)
```

### 2. MiniChat 怎么调用 RPC 用户服务

MiniChat 自己不保存密码。用户登录时，MiniChat 通过 TCP 连接调用 `cpp_rpc_lab`：

```text
login jerry 123456
whoami <token>
logout <token>
```

这样聊天服务和用户服务被拆开，形成了一个很小的多服务后端架构。

### 3. 消息怎么保存

每条消息被表示成一个 `Message`：

```cpp
struct Message {
    uint64_t id;
    std::string room;
    std::string user;
    std::string to;
    std::string text;
    uint64_t ts;
};
```

服务端内存里有 `g_messages`，同时会追加写入 `data/messages.tsv`。

### 4. 私聊怎么实现

私聊不是前端隐藏，而是服务端过滤：

- `to` 为空：公开消息，房间内所有人可见
- `to` 不为空：只有 `msg.user` 和 `msg.to` 能看到

这就是后端权限控制的雏形。

## 简历写法参考

C++ MiniChat：基于 Linux socket 实现的轻量级 Web 聊天系统，接入独立 RPC 用户服务，支持注册登录、token 鉴权、HTTP 接口、SSE 长连接实时推送、多线程连接处理、房间隔离、私聊权限过滤、消息搜索、在线用户维护、测试数据清理和文件持久化。项目覆盖网络编程、协议解析、RPC 服务调用、并发处理、状态管理和前后端联调等后端核心能力。
