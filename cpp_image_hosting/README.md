# Mini Image Hosting

项目展示文档：[docs/PROJECT_SHOWCASE.md](docs/PROJECT_SHOWCASE.md)

这是 MiniKV 之后的第二个项目：图床系统。

图床系统的目标是：上传一张图片，服务端保存文件并返回一个可访问链接。这个项目比 MiniKV 更贴近真实互联网业务，重点练习 HTTP 文件上传、静态文件访问、元数据管理、删除管理、访问统计和页面展示。

## 功能列表

- 浏览器打开上传页面
- 选择图片并上传
- 服务端保存到 `uploads/`
- 返回图片访问链接
- 浏览器可以打开图片链接
- Gallery 展示历史图片
- 元数据保存到 `data/images.tsv`
- 显示文件名、大小、上传时间、访问次数
- 删除图片和对应元数据
- 访问图片时自动统计 views

## 编译运行

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro/cpp_image_hosting
make clean
make
./image_hosting 19090
```

浏览器打开：

```text
http://127.0.0.1:19090/
```

## HTTP API

```text
GET  /
POST /upload
GET  /uploads/<filename>
GET  /api/images
GET  /api/delete?name=<filename>
```

## 当前能力

- C++ HTTP 服务端
- 浏览器上传图片
- `multipart/form-data` 解析
- 图片保存到 `uploads/`
- 通过 `/uploads/<filename>` 访问图片
- `/api/images` 返回历史图片列表
- 页面展示已上传图片 gallery
- 上传元数据保存到 `data/images.tsv`
- 支持删除图片和对应元数据
- 访问图片时自动统计访问次数 views

## 后续演进

- 图片 magic bytes 校验
- 短链接 `/s/<code>`
- 缩略图生成
- 元数据切换到 SQLite 或 MySQL
- 上传和访问压测
- Dockerfile

## 和 MiniKV 的区别

MiniKV 偏底层：网络、epoll、存储、持久化。

图床偏产品业务：上传、保存、访问、页面、文件管理。
