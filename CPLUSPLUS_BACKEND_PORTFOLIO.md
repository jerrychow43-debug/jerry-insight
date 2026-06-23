# C++ Linux 后端项目总览

这组项目是围绕 Linux C++ 后端能力逐步搭建的练习作品集。每个项目练一个核心方向，最后组合成一个更完整的小型聊天产品。

## 项目路线

| 项目 | 状态 | 主要能力 |
| --- | --- | --- |
| `cpp_kv_server` | 展示版完成 | TCP/HTTP、KV 存储、持久化、Web UI、压测 |
| `cpp_image_hosting` | 展示版完成 | HTTP 文件上传、静态文件访问、元数据、删除、浏览量 |
| `cpp_minichat` | 接近完成 | HTTP 聊天、SSE 实时推送、房间、私聊、搜索、在线用户、登录接入 |
| `cpp_rpc_lab` | 接近完成 | TCP RPC、注册登录、session token、`whoami`、`logout`、用户服务 |

## 当前组合产品

现在 `cpp_minichat` 和 `cpp_rpc_lab` 已经组合起来：

```text
浏览器
  |
  | HTTP / SSE
  v
cpp_minichat 聊天服务
  |
  | TCP RPC
  v
cpp_rpc_lab 用户服务
```

- `cpp_minichat` 负责聊天页面、HTTP API、SSE 实时推送、消息持久化、房间和私聊权限。
- `cpp_rpc_lab` 负责注册、登录、token 校验和退出登录。

这已经不是单个 toy demo，而是一个“小型多服务 C++ 后端系统”的雏形。

## 一键运行 MiniChat + RPC

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro/cpp_minichat
chmod +x run_all.sh
./run_all.sh
```

然后打开：

```text
http://127.0.0.1:19191/
```

## 能展示的技术点

- Linux socket 编程
- TCP 服务端与客户端
- HTTP 请求解析和响应拼装
- SSE 长连接实时推送
- 多线程连接处理
- 互斥锁保护共享状态
- 简单 RPC 协议设计
- 用户注册、登录和 token 鉴权
- 消息持久化与数据恢复
- 房间隔离和私聊权限过滤
- 前后端联调和浏览器接口设计

## 简历总描述

基于 Linux C++ 实现了一组后端练习项目，包括 KV 存储服务、图床服务、Web 聊天系统和轻量级 RPC 用户服务。其中 MiniChat 接入 RPC 用户服务，支持注册登录、token 校验、SSE 实时聊天、房间隔离、私聊权限过滤、消息搜索和文件持久化，覆盖网络编程、协议解析、并发处理、服务拆分和状态管理等后端核心能力。

## Docker Compose 部署

项目根目录已经提供：

```text
docker-compose.yml
cpp_rpc_lab/Dockerfile
cpp_minichat/Dockerfile
PUBLIC_DEPLOYMENT.md
```

云服务器上可以运行：

```bash
docker compose up -d --build
```

然后访问：

```text
http://服务器公网IP:19191/
```

## 后续路线

1. 在 Ubuntu 中完整编译验证 `cpp_minichat/run_all.sh`。
2. 录制或手动跑一遍最终演示流程。
3. 给 MiniChat 加 SQLite/MySQL 存储。
4. 做公网部署或内网穿透，让不同 WiFi 的朋友也能访问。
5. 可选升级 WebSocket、离线消息、图片发送，把 `cpp_image_hosting` 也接入聊天。
