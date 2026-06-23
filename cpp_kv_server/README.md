# C++ KV Server

项目展示文档：[docs/PROJECT_SHOWCASE.md](docs/PROJECT_SHOWCASE.md)

这是一个轻量级 C++ KV 存储服务端。当前版本使用 Linux TCP socket + epoll，可以同时处理多个客户端连接，并使用 AOF 追加日志把数据持久化到本地文件。

## 编译

```bash
make
```

## 启动

```bash
./kv_server 6379
```

默认会把写命令追加保存到 `data/kv.aof`。也可以指定 AOF 文件：

```bash
./kv_server 6379 data/kv.aof
```

## 测试

另开一个 Ubuntu 终端：

```bash
nc 127.0.0.1 6379
```

然后输入：

```text
set name Jerry
get name
del name
get name
help
exit
```

预期效果：

```text
OK
Jerry
OK
(nil)
```

## 持久化验证

1. 启动服务端。
2. 用客户端执行 `set name Jerry`。
3. 按 `Ctrl+C` 关闭服务端。
4. 重新启动服务端。
5. 再执行 `get name`，应返回 `Jerry`。


## 压测

先启动服务端：

```bash
./kv_server 6379
```

另开一个 Ubuntu 终端执行：

```bash
python3 tools/bench.py -n 10000
```

输出会包含 `set` 和 `get` 的耗时与 QPS。


## Web 管理页

启动服务端后，在浏览器打开：

```text
http://127.0.0.1:6379/
```

页面支持 `Set`、`Get`、`Delete`、刷新 key 列表。

## HTTP API

```text
GET /api/set?key=name&value=Jerry
GET /api/get?key=name
GET /api/del?key=name
GET /api/keys
GET /api/flushall
```
## 当前支持的命令

- `set key value`
- `get key`
- `del key`
- `keys`
- `help`
- `exit` / `quit`

## 当前能力

- TCP 服务端监听端口
- epoll 事件循环
- 多客户端连接
- 文本命令协议
- 内存 `unordered_map` 存储
- AOF 追加日志持久化，默认保存到 `data/kv.aof`
- Python 压测脚本 `tools/bench.py`
- HTTP API 和内置 Web 管理页

后续会继续增加：日志、AOF 压缩和更完整的项目展示文档。






