# cpp_rpc_lab

cpp_rpc_lab 是第四个 C++ Linux 后端练习项目：一个轻量级 RPC 实验室。

它不是给浏览器直接访问的页面，而是模拟后端服务之间的调用：客户端发送一条 RPC 请求，服务端执行对应方法并返回结果。

## 目前实现

- TCP RPC 服务端
- TCP RPC 客户端
- 多线程处理多个客户端连接
- 用户注册：`register`
- 用户登录：`login`
- 用户查询：`get_user`
- 登录态查询：`whoami <token>`
- 退出登录：`logout <token>`
- 健康检查：`ping`
- 用户数据持久化到 `data/users.tsv`

## 编译运行

第一个终端启动服务端：

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro/cpp_rpc_lab
make clean
make
./rpc_server 18888
```

第二个终端调用客户端：

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro/cpp_rpc_lab
./rpc_client ping
./rpc_client register jerry 123456 Jerry
./rpc_client login jerry 123456
./rpc_client get_user jerry
./rpc_client whoami <login 返回的 token>
./rpc_client logout <login 返回的 token>
```

也可以进入交互模式：

```bash
./rpc_client
```

然后输入：

```text
ping
register tom 123456 Tom
login tom 123456
get_user tom
whoami <login 返回的 token>
logout <login 返回的 token>
quit
```

## RPC 协议

当前版本用简单文本协议，方便理解：

请求：

```text
method arg1 arg2 arg3\n
```

响应：

```text
OK result\n
ERR reason\n
```

示例：

```text
register jerry 123456 Jerry
OK registered jerry

login jerry 123456
OK login jerry Jerry token tok_jerry_xxx
```

## 和聊天项目的关系

当前状态：已被 MiniChat 接入，作为注册、登录、token 校验和退出登录的用户服务。

这个项目可以作为 MiniChat 的“用户服务”：

- MiniChat 负责聊天页面和消息
- cpp_rpc_lab 负责注册、登录、查询用户
- MiniChat 后端通过 RPC 调用用户服务
- MiniChat 登录后保存 token，再用 `whoami` 验证当前用户

这就是后端服务拆分的雏形。

## 能不能让聊天项目不用同一个 WiFi？

RPC 本身不能解决公网访问问题。要让朋友不在同一个 WiFi 也能用 MiniChat，需要：

- 把 MiniChat 部署到公网云服务器，或者
- 使用内网穿透工具，把本机端口暴露到公网

RPC 解决的是“后端内部服务怎么互相调用”，公网访问解决的是“用户怎么从外网连到你的服务”。它们是两件事，但最后可以组合成一个完整产品。

## 后续演进

- 接入 MiniChat 做登录服务
- 加异步 RPC 客户端
- 加请求 ID 和超时
- 加 JSON 协议
- 加服务配置文件
- 接入 MiniChat 做登录服务
- 部署到云服务器

