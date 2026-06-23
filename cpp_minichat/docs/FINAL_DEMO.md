# MiniChat + RPC 用户服务最终演示流程

## 1. 启动项目

一键启动 RPC 用户服务和 MiniChat：

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro/cpp_minichat
chmod +x run_all.sh
./run_all.sh
```

浏览器打开：

```text
http://127.0.0.1:19191/
```

如果你想手动启动，先开 `cpp_rpc_lab/rpc_server 18888`，再开 `cpp_minichat/minichat 19191 127.0.0.1 18888`。

## 2. 登录演示

1. 打开页面后，先用顶部表单注册或登录。
2. 账号示例：

```text
username: jerry
password: 123456
nickname: Jerry
```

3. 登录成功后右侧 `Current` 会显示当前身份。
4. 刷新页面，MiniChat 会通过 `/api/auth_me` 校验 token，token 有效就自动保持登录。
5. 点击 `Logout` 后会调用 `/api/auth_logout`，RPC 服务端 session 会失效。

这个点可以重点讲：MiniChat 本身不保存密码，而是通过 TCP RPC 调用 `cpp_rpc_lab` 用户服务。

## 3. 基础聊天演示

1. 打开三个浏览器窗口。
2. 分别登录 `jerry`、`tom`、`alice` 三个账号。
3. 在 `general` 房间发送公开消息。
4. 三个窗口都能实时看到消息。
5. 右侧状态显示 `realtime connected`，说明 SSE 长连接已经连上。

## 4. 私聊权限演示

1. Jerry 的 `private to` 填 `tom`。
2. Jerry 发送一条私聊消息。
3. Jerry 能看到，因为 Jerry 是发送者。
4. Tom 能看到，因为 Tom 是接收者。
5. Alice 看不到，因为服务端没有把这条私聊返回给 Alice。

这个点可以重点讲：私聊不是前端隐藏，而是后端按 `user` 和 `to` 做权限过滤。

## 5. 房间隔离演示

1. 切换到 `cpp` 房间。
2. 发送一条消息。
3. 切回 `general`。
4. `cpp` 的消息不会出现在 `general`。

## 6. 搜索演示

1. 在右侧 `Search` 输入关键词。
2. 搜索只查当前房间。
3. 搜索结果仍然遵守私聊权限。

比如 Alice 搜索 Jerry 发给 Tom 的私聊关键词，搜不到。

## 7. 清理演示数据

点击 `Clear Current Room` 可以清空当前房间消息，方便重新录制或重新演示。

它会同步重写：

```text
data/messages.tsv
```

## 8. 可以这样介绍项目

MiniChat 是一个基于 Linux socket 的 C++ Web 聊天系统，已经拆分出独立 RPC 用户服务。`cpp_rpc_lab` 负责注册、登录、token 校验和退出登录；`cpp_minichat` 负责聊天页面、HTTP API、SSE 实时推送、房间、私聊、搜索和消息持久化。这展示了从单体 C++ 服务向多服务后端架构演进的过程。

## 9. 项目技术点

- Linux socket：监听端口、接收连接、读取 HTTP 请求、返回 HTTP 响应
- HTTP API：登录、发送消息、拉取历史消息、搜索消息、在线用户、清理房间
- TCP RPC：MiniChat 调用 cpp_rpc_lab 完成注册、登录、`whoami` 和 `logout`
- Token 鉴权：浏览器保存 token，聊天接口由后端调用 RPC 校验
- SSE 长连接：浏览器通过 `EventSource` 接收服务端实时推送
- 多线程：每个连接由独立线程处理，避免长连接阻塞其他请求
- 互斥锁：保护消息列表和在线用户表
- 文件持久化：消息保存到 TSV 文件，服务重启后可恢复
- 权限过滤：私聊消息只返回给发送者和接收者

## 10. 后续可升级方向

- SQLite 或 MySQL 存储
- WebSocket 双向通信
- 离线消息
- 消息分页
- Docker 部署
- 公网云服务器部署
