# Linux / 网络命令缩写全称速记

适合面试前快速背。重点不是死记每个英文，而是知道命令名字大概从哪里来，这样看到命令更容易想起作用。

## 一、Linux 常用命令

| 命令 | 全称 / 来源 | 中文意思 | 怎么记 |
|---|---|---|---|
| `ls` | list | 列出文件 | list 文件列表 |
| `cd` | change directory | 切换目录 | change 到另一个 directory |
| `pwd` | print working directory | 显示当前目录 | print 当前 working directory |
| `cp` | copy | 复制 | copy 文件 |
| `mv` | move | 移动 / 重命名 | move 文件，也能改名 |
| `rm` | remove | 删除 | remove 文件 |
| `mkdir` | make directory | 创建文件夹 | make 一个 directory |
| `rmdir` | remove directory | 删除空文件夹 | remove directory |
| `cat` | concatenate | 拼接 / 显示文件内容 | 原意是拼接文件，常用来看文件 |
| `more` | more pages | 分页查看 | 一页一页看更多内容 |
| `less` | less is more | 更好用的分页查看 | 比 `more` 更灵活 |
| `head` | head | 看文件开头 | head 是头部 |
| `tail` | tail | 看文件末尾 | tail 是尾部 |
| `grep` | global regular expression print | 按规则搜索文本 | 用正则把匹配行打印出来 |
| `find` | find | 查找文件 | find 文件 |
| `chmod` | change mode | 修改权限 | mode 指权限模式 |
| `chown` | change owner | 修改文件所有者 | owner 是所有者 |
| `ps` | process status | 查看进程状态 | process 是进程，status 是状态 |
| `top` | top processes | 动态查看进程资源 | 看最占资源的进程 |
| `kill` | kill process | 结束进程 | 发送信号结束进程 |
| `df` | disk free | 查看磁盘剩余空间 | free 表示剩余 |
| `du` | disk usage | 查看磁盘占用 | usage 表示使用量 |
| `tar` | tape archive | 打包 / 解包 | 历史上和磁带归档有关，现在常用来打包 |
| `ssh` | secure shell | 安全远程登录 | 远程登录 Linux 常用 |
| `scp` | secure copy | 安全远程复制 | 基于 SSH 复制文件 |
| `su` | substitute user / switch user | 切换用户 | 切换到另一个用户 |
| `sudo` | superuser do | 用管理员权限执行 | 让普通用户临时用管理员权限执行 |
| `env` | environment | 查看环境变量 | environment 是环境 |
| `export` | export variable | 导出环境变量 | 让变量对子进程可见 |
| `cron` | chronos / time | 定时任务服务 | 和时间有关 |
| `crontab` | cron table | 定时任务表 | cron 的任务表 |
| `mount` | mount filesystem | 挂载文件系统 | 把磁盘/设备挂到目录上 |
| `umount` | unmount | 卸载挂载 | 注意命令是 `umount`，不是 `unmount` |
| `ln` | link | 创建链接 | link 文件 |
| `vi` | visual editor | 文本编辑器 | Linux 常见编辑器 |
| `vim` | vi improved | 增强版 vi | improved 是增强 |
| `ldd` | list dynamic dependencies | 查看动态库依赖 | 看程序依赖哪些动态库 |
| `md5sum` | MD5 checksum | 计算 MD5 校验值 | sum 是校验和 |

## 二、常见参数缩写

| 参数 | 全称 / 来源 | 常见意思 | 例子 |
|---|---|---|---|
| `-a` | all | 显示全部 | `ls -a` 显示隐藏文件 |
| `-l` | long | 显示详细信息 | `ls -l` 显示权限、大小、时间 |
| `-h` | human-readable | 人类可读单位 | `df -h` 显示 GB/MB |
| `-r` / `-R` | recursive | 递归处理目录 | `cp -r dir1 dir2` 复制目录 |
| `-f` | force / follow | 强制 / 跟踪 | `rm -f` 强制删除，`tail -f` 持续看日志 |
| `-s` | summarize | 汇总 | `du -sh *` 显示每个文件/目录总大小 |
| `-v` | verbose | 显示详细过程 | `tar -xzvf file.tar.gz` 显示解压过程 |
| `-x` | extract | 解包 | `tar -x` 解压归档 |
| `-z` | gzip | 用 gzip 解压/压缩 | `tar -z` 处理 `.gz` |
| `-c` | create | 创建 | `tar -c` 创建归档 |
| `-p` | process / port | 显示进程或端口信息 | `ss -lntp` 显示监听端口对应进程 |
| `-n` | numeric | 数字形式显示 | `ss -n` 不把 IP/端口解析成名字 |
| `-t` | tcp | 只看 TCP | `ss -t` |
| `-u` | udp | 只看 UDP | `ss -u` |

## 三、网络相关缩写

| 命令 / 名词 | 全称 | 中文意思 | 怎么记 |
|---|---|---|---|
| `ping` | packet internet groper | 测试网络连通性 | 看对方主机能不能通 |
| `curl` | client URL | 请求 URL / 测接口 | 命令行访问网页或接口 |
| `wget` | web get | 下载网络资源 | get 网络文件 |
| `ss` | socket statistics | 查看 socket / 端口 | 比 `netstat` 更新 |
| `netstat` | network statistics | 查看网络连接状态 | network status/statistics |
| `ip` | internet protocol | 查看 / 配置网络 | 现代 Linux 常用网络命令 |
| `ifconfig` | interface configuration | 查看 / 配置网卡 | interface 是网络接口 |
| `DNS` | Domain Name System | 域名系统 | 把域名解析成 IP |
| `IP` | Internet Protocol | 网际协议 | 网络地址协议 |
| `TCP` | Transmission Control Protocol | 传输控制协议 | 可靠传输，有连接 |
| `UDP` | User Datagram Protocol | 用户数据报协议 | 不保证可靠，更快 |
| `HTTP` | HyperText Transfer Protocol | 超文本传输协议 | 浏览器访问网页常用 |
| `HTTPS` | HTTP Secure | 加密版 HTTP | HTTP + TLS/SSL |
| `FTP` | File Transfer Protocol | 文件传输协议 | 用来传文件 |
| `SSH` | Secure Shell | 安全远程登录协议 | 登录远程 Linux |

## 四、最该优先背的

```text
ls = list
cd = change directory
pwd = print working directory
cp = copy
mv = move
rm = remove
chmod = change mode
ps = process status
df = disk free
du = disk usage
ssh = secure shell
scp = secure copy
sudo = superuser do
grep = global regular expression print
```

## 五、面试回答模板

如果面试官问“这些 Linux 命令你了解吗”，可以这样说：

> 了解一些基础命令。很多 Linux 命令本身就是英文缩写，比如 `ls` 是 list，用来列文件；`cd` 是 change directory，用来切换目录；`chmod` 是 change mode，用来改权限；`df` 是 disk free，看磁盘剩余空间；`du` 是 disk usage，看目录占用空间。知道这些缩写来源后，命令的作用会比较好记。

