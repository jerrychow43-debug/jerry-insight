# Mini Image Hosting 项目展示文档

Mini Image Hosting 是一个使用 C++ 实现的轻量级图床系统。它提供浏览器上传图片、服务端保存文件、返回访问链接、历史图片列表、元数据管理、删除图片和访问次数统计等功能。

## 项目目标

这个项目的目标是做一个贴近真实互联网业务的小型后端产品：用户上传图片后，服务端保存图片并返回一个可以直接访问的链接。

相比 MiniKV 偏底层的网络和存储训练，图床项目更偏业务闭环：

- HTTP 请求处理
- 文件上传
- multipart/form-data 解析
- 静态文件访问
- 元数据管理
- Web 管理页面
- 删除和访问统计

## 当前功能

- 浏览器上传图片
- 支持 PNG/JPEG/GIF/WebP
- 文件保存到 `uploads/`
- 返回 `/uploads/<filename>` 访问链接
- Web 页面预览上传结果
- Gallery 展示历史图片
- 元数据保存到 `data/images.tsv`
- 显示文件名、大小、上传时间、访问次数
- 删除图片和对应元数据
- 访问图片时自动增加 views

## 架构图

```text
Browser
  |
  | GET /                 -> upload page
  | POST /upload          -> upload image
  | GET /uploads/<file>   -> view image
  | GET /api/images       -> gallery metadata
  | GET /api/delete       -> delete image
  v
+------------------------------+
| C++ Image Hosting Server     |
|                              |
| HTTP parser                  |
| multipart parser             |
| upload handler               |
| static image handler         |
| metadata manager             |
+---------------+--------------+
                |
        +-------+--------+
        |                |
        v                v
   uploads/         data/images.tsv
   image files      metadata
```

## 目录结构

```text
cpp_image_hosting/
  Makefile
  README.md
  src/
    main.cpp
  uploads/
    uploaded images
  data/
    images.tsv
  docs/
    PROJECT_SHOWCASE.md
```

## HTTP 接口

### 上传图片

```text
POST /upload
Content-Type: multipart/form-data
```

返回示例：

```json
{
  "ok": true,
  "url": "/uploads/1782061863751748.png",
  "size": 98301
}
```

### 查看图片

```text
GET /uploads/<filename>
```

访问图片时会自动增加 `views`。

### 图片列表

```text
GET /api/images
```

返回示例：

```json
{
  "ok": true,
  "images": [
    {
      "name": "1782061863751748.png",
      "url": "/uploads/1782061863751748.png",
      "size": 98301,
      "content_type": "image/png",
      "uploaded_at": "1782061863",
      "views": 2
    }
  ]
}
```

### 删除图片

```text
GET /api/delete?name=<filename>
```

返回示例：

```json
{
  "ok": true
}
```

## 元数据格式

`data/images.tsv` 使用 TSV 存储，每行一张图片：

```text
name    url    size    content_type    uploaded_at    views
```

例如：

```text
1782061863751748.png    /uploads/1782061863751748.png    98301    image/png    1782061863    2
```

## 编译运行

```bash
cd /mnt/c/Users/Jerry/Desktop/AIstudy/Jerry-Insight-Pro/cpp_image_hosting
make clean
make
./image_hosting 19090
```

浏览器访问：

```text
http://127.0.0.1:19090/
```

## 技术点说明

### 1. HTTP 服务端

项目直接使用 Linux socket 实现简单 HTTP 服务。服务端接收请求后，根据 method 和 path 分发到不同处理函数。

### 2. multipart/form-data 解析

浏览器上传图片时使用 `multipart/form-data`。服务端根据 boundary 切分请求体，从中提取图片二进制数据。

### 3. 静态图片访问

上传后的图片保存在 `uploads/`，访问 `/uploads/<filename>` 时服务端读取文件并返回对应 Content-Type。

### 4. 元数据管理

图片文件本身只保存二进制内容，展示列表需要额外元数据。项目使用 `data/images.tsv` 保存文件名、URL、大小、类型、上传时间和访问次数。

### 5. 访问统计

每次访问 `/uploads/<filename>`，服务端会更新该图片的 `views`，然后写回元数据文件。

## 当前限制

- 当前是单线程 HTTP 服务，适合学习和展示，不适合高并发生产。
- multipart 解析是教学版，只覆盖浏览器常见上传格式。
- 图片类型主要依赖 Content-Type 和扩展名判断，还没有做 magic bytes 校验。
- 缩略图和原图访问共用同一个接口，所以 gallery 加载也会增加 views。

## 后续优化

- 改成 epoll 或线程池模型
- 增加图片 magic bytes 校验
- 增加短链接 `/s/<code>`
- 缩略图单独生成，避免 gallery 加载计入原图 views
- 元数据切换到 SQLite 或 MySQL
- 增加上传和访问压测
- 增加 Dockerfile

## 简历描述示例

Mini Image Hosting：基于 C++ Linux socket 实现的轻量级图床系统，支持浏览器图片上传、multipart/form-data 解析、静态图片访问、元数据持久化、图片删除、访问次数统计和 Web Gallery 展示。项目用于实践 HTTP 协议处理、文件上传、元数据管理和后端产品闭环设计。
