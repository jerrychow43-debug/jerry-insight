# MiniChat 公网访问部署说明

这个文档说明如何让别人不在同一个 WiFi 也能访问 MiniChat。

## 当前状态

本地现在已经是两个服务：

```text
浏览器
  |
  | HTTP / SSE
  v
cpp_minichat 聊天服务，默认端口 19191
  |
  | TCP RPC
  v
cpp_rpc_lab 用户服务，默认端口 18888
```

本地访问：

```text
http://127.0.0.1:19191/
```

同 WiFi 手机访问时，用电脑局域网 IP。不同 WiFi 想访问，就必须让 `19191` 端口能被公网访问。

## 方案一：云服务器部署

这是最像正式产品的方式。

### 1. 准备服务器

需要一台 Linux 云服务器，系统用 Ubuntu 即可。服务器需要开放入站端口：

```text
19191/tcp
```

如果以后加 HTTPS，可以再开放：

```text
80/tcp
443/tcp
```

### 2. 安装 Docker

在服务器上安装 Docker 和 Docker Compose 插件。不同云厂商系统镜像略有差异，核心目标是让下面命令可用：

```bash
docker --version
docker compose version
```

### 3. 上传项目

把这个仓库放到服务器，例如：

```bash
cd ~
git clone <你的仓库地址> Jerry-Insight-Pro
cd Jerry-Insight-Pro
```

如果暂时没有 GitHub 仓库，也可以先用压缩包或 `scp` 上传。

### 4. 启动服务

在项目根目录运行：

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
docker compose logs -f
```

### 5. 访问

浏览器打开：

```text
http://服务器公网IP:19191/
```

朋友不需要和你同一个 WiFi，只要能访问这个公网 IP 即可。

## 方案二：内网穿透

这是最快让外地朋友临时访问的方式。

特点：

- 不一定需要买服务器
- 你的电脑必须一直开着
- MiniChat 和 RPC 服务仍然跑在你本机
- 隧道工具会给你一个公网 URL

流程大概是：

1. 本地启动 MiniChat：

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro/cpp_minichat
./run_all.sh
```

2. 用内网穿透工具把本机 `19191` 暴露出去。
3. 把工具生成的公网 URL 发给朋友。

这种适合临时演示，不适合作为长期正式服务。

## 方案三：家里路由器端口转发

这条路线不太推荐新手直接用。

它需要：

- 家里宽带有公网 IPv4，或者能用 IPv6
- 路由器配置端口转发
- Windows 防火墙放行
- 处理动态 IP

优点是不用云服务器；缺点是网络环境复杂，安全风险也更高。

## 推荐路线

短期演示：

```text
内网穿透
```

正式一点给朋友长期用：

```text
云服务器 + Docker Compose
```

当前已经补好了 Docker 部署文件：

```text
docker-compose.yml
cpp_rpc_lab/Dockerfile
cpp_minichat/Dockerfile
```

所以后面上服务器时，核心命令就是：

```bash
docker compose up -d --build
```

## 注意事项

当前项目仍然是学习展示版，不是生产安全版：

- 密码还没有做哈希存储
- 还没有 HTTPS
- 没有限流和验证码
- 没有数据库备份策略
- 消息和用户数据只是简单持久化

如果真的长期给很多人用，下一步应该先做：

1. 密码哈希
2. SQLite/MySQL
3. HTTPS 反向代理
4. Docker 部署验证
5. 日志和备份
