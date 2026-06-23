# MiniChat

MiniChat 是第三个 C++ Linux 后端练习项目：一个小型 Web 聊天系统。

它不是套壳页面，核心逻辑在 C++ 服务端里：浏览器发 HTTP 请求，C++ 解析请求、保存消息、按房间和私聊规则返回消息。

## 已实现功能

- 浏览器聊天页面
- RPC 用户服务登录
- 注册/登录后才能聊天
- 刷新页面后自动校验 token
- 退出登录会让 RPC session 失效
- 按房间聊天：`general`、`cpp`、`game`，也可以自己输入房间名
- 私聊：`private to` 输入对方昵称，只有发送者和接收者能看到
- 多浏览器窗口通过 SSE 长连接实时接收新消息
- 当前房间在线用户列表
- 当前房间消息搜索，搜索结果也遵守私聊权限
- 清空当前房间测试消息，方便演示
- 显示 SSE 实时连接状态
- 点击在线用户可快速填入私聊对象
- 浏览器本地记住昵称、房间和私聊对象
- 自己发的消息靠右显示，别人发的消息靠左显示
- 消息持久化到 `data/messages.tsv`
- 兼容旧版消息数据格式

## 编译运行

一键启动两个服务：

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro/cpp_minichat
chmod +x run_all.sh
./run_all.sh
```

也可以手动启动。先启动 RPC 用户服务：

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro/cpp_rpc_lab
make clean
make
./rpc_server 18888
```

再启动 MiniChat：

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro/cpp_minichat
make clean
make
./minichat 19191 127.0.0.1 18888
```

MiniChat 参数说明：

```text
./minichat <chat_port> <rpc_host> <rpc_port>
```

不传参数时默认是：`19191 127.0.0.1 18888`。

Docker 启动：

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro
docker compose up -d --build
```

公网部署说明见根目录 `PUBLIC_DEPLOYMENT.md`。

浏览器打开：

```text
http://127.0.0.1:19191/
```

## 演示方法

1. 打开三个浏览器窗口，都进入 `http://127.0.0.1:19191/`。
2. 每个窗口先注册/登录一个账号，比如 `jerry`、`tom`、`alice`。刷新页面后如果 token 仍有效，会自动保持登录。
3. 不填 `private to`，直接发消息，这是房间公开消息，三个人都能看到。
4. Jerry 的 `private to` 填 `Tom`，再发消息，这是私聊消息。
5. Jerry 能看到，因为 Jerry 是发送者。
6. Tom 能看到，因为 Tom 是接收者。
7. Alice 看不到，因为服务端不会把这条私聊返回给 Alice。
8. 切换到 `cpp` 或 `game` 房间，可以看到不同房间的消息互相隔离。

注意：如果某个窗口右侧 `Current` 还是 `Jerry`，那它当然能看到 `Jerry -> Tom` 的私聊。要验证“别人看不到”，必须把第三个窗口昵称改成 `Alice` 或其他名字。

## 当前 API

```text
GET /api/auth_register?username=<name>&password=<pwd>&nickname=<nick>
GET /api/auth_login?username=<name>&password=<pwd>
GET /api/auth_me?token=<token>
GET /api/auth_logout?token=<token>
GET /api/send?room=<room>&user=<name>&token=<token>&to=<target>&msg=<message>
GET /api/messages?room=<room>&user=<name>&token=<token>&since=<id>
GET /api/search?room=<room>&user=<name>&token=<token>&q=<keyword>
GET /api/clear?room=<room>&user=<name>&token=<token>
GET /api/users?room=<room>&user=<name>&token=<token>
GET /events?room=<room>&user=<name>&token=<token>&since=<id>
```

`to` 可以为空；为空就是公开消息，不为空就是私聊。

## 这个项目练什么

- Linux socket 编程
- HTTP 请求解析和响应拼装
- URL query 参数解析
- 简单 JSON 输出
- 服务端状态管理
- 多线程连接处理
- SSE 长连接实时推送
- 消息搜索和权限过滤
- 数据文件重写和测试数据清理
- 文件持久化
- 房间隔离和私聊权限过滤
- 前后端联调思路

## 后续演进

- 从 SSE 继续升级到 WebSocket
- 搜索结果跳转到原消息
- 离线消息
- SQLite/MySQL 存储
- 更完整的用户认证和权限体系






