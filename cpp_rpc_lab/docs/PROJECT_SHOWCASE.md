# cpp_rpc_lab 项目展示说明

## 一句话介绍

cpp_rpc_lab 是一个 C++ 实现的轻量级 RPC 实验项目，用 TCP socket 模拟后端服务之间的远程方法调用，并且已经接入 MiniChat 作为用户服务。

## 已完成能力

- 服务端监听 TCP 端口
- 客户端发起 RPC 请求
- 多线程处理多个客户端
- `register` 用户注册
- `login` 用户登录
- `get_user` 查询用户
- `login` 返回 session token
- `whoami` 验证登录态
- `logout` 注销登录态
- `ping` 健康检查
- 用户数据持久化

## 演示步骤

1. 启动服务端：

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro/cpp_rpc_lab
make clean
make
./rpc_server 18888
```

2. 新开一个终端，调用客户端：

```bash
./rpc_client ping
./rpc_client register jerry 123456 Jerry
./rpc_client login jerry 123456
./rpc_client get_user jerry
./rpc_client whoami <login 返回的 token>
./rpc_client logout <login 返回的 token>
```

3. 预期结果：

```text
OK pong
OK registered jerry
OK login jerry Jerry token tok_jerry_xxx
OK user jerry Jerry
OK me jerry Jerry
OK logout
```

## 可以重点讲什么

### 1. 什么是 RPC

RPC 可以理解成“远程函数调用”。本来函数在本机进程里调用，现在变成客户端通过网络发请求，让另一个服务端进程执行函数并返回结果。

### 2. 为什么后端要 RPC

真实项目里，一个后端系统通常会拆成多个服务：

- 用户服务
- 消息服务
- 文件服务
- 支付服务

它们之间需要互相调用，RPC 就是常见通信方式之一。

### 3. 这个项目和 MiniChat 怎么结合

MiniChat 已经接入这个 RPC 用户服务：

- 用户注册登录由 cpp_rpc_lab 负责
- MiniChat 收到登录请求后，通过 RPC 调用用户服务
- 登录成功后保存 token，后续聊天接口用 `whoami` 校验登录态

这样 MiniChat 就从单体项目开始往多服务架构升级。

## 简历写法参考

C++ RPC Lab：基于 Linux socket 实现轻量级 RPC 服务，支持客户端/服务端通信、多线程连接处理、用户注册登录查询、session token 鉴权和文件持久化。通过自定义文本协议模拟后端内部服务调用，为聊天系统拆分用户服务提供基础。

