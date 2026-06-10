Linux / 网络协议面试速记本

一、Linux 权限

1. chmod 是什么？
chmod 用来修改文件或目录的权限。

例子：
chmod 755 file

意思：
把 file 的权限改成 755。

755 拆开看：
7 = 文件所有者权限：读 + 写 + 执行
5 = 同组用户权限：读 + 执行
5 = 其他用户权限：读 + 执行

读 = 4
写 = 2
执行 = 1
所以 7 = 4 + 2 + 1，5 = 4 + 1。

常见用途：
让一个脚本或程序拥有可执行权限。

例子：
chmod +x script.sh

意思：
给 script.sh 增加执行权限。加完后可以这样运行：
./script.sh

面试说：
chmod 用来改文件权限，755 表示所有者可读写执行，其他用户可读和执行；chmod +x 是给脚本加执行权限。

二、环境变量

1. export

例子：
export PATH=/usr/local/bin:$PATH

意思：
设置环境变量 PATH，并让当前 shell 及它启动的子进程都能使用。

PATH 是什么：
系统查找命令的路径列表。你输入 python、ls、uvicorn 这类命令时，系统会去 PATH 里的目录找对应程序。

面试说：
export 用来设置环境变量，让子进程也能读取。比如部署服务时经常用环境变量保存 API Key、端口等配置。

2. /etc/profile 和 ~/.bashrc

/etc/profile：
全局配置，影响所有用户。

~/.bashrc：
当前用户的 bash 配置，通常影响当前用户的交互式终端。

面试说：
所有用户都需要的环境变量可以放 /etc/profile；只给当前用户用的配置可以放 ~/.bashrc。

三、查看文件

1. cat file

意思：
一次性把 file 文件内容输出到屏幕。

适合：
小文件。

2. more file

意思：
分页查看文件内容，一页一页往下看。

适合：
比较长的文件。

3. less file

意思：
分页查看文件，比 more 更灵活，可以上下翻。

4. tail file

意思：
查看文件最后几行。

5. tail -f app.log

意思：
实时查看 app.log 最新追加的内容。

适合：
看程序运行日志。

面试说：
cat 适合看小文件，more/less 适合分页看大文件，tail -f 常用来实时看日志。

四、磁盘和目录大小

1. df -h

意思：
查看磁盘分区使用情况。

-h：
用人能看懂的单位显示，比如 G、M。

常见输出：
哪个分区用了多少，还剩多少。

2. du -sh *

意思：
查看当前目录下每个文件或子目录占用多大空间。

du：
查看文件/目录占用空间。

-s：
汇总显示，不展开每个子文件。

-h：
用 G、M 这类可读单位显示。

面试说：
如果磁盘满了，我先用 df -h 看哪个分区满，再用 du -sh * 找大目录。

五、进程

1. ps -ef

意思：
查看当前系统进程列表。

常用于：
查某个服务是否在运行。

2. top

意思：
实时查看 CPU、内存和进程占用。

3. kill PID

意思：
结束某个进程。

PID：
进程 ID。

例子：
kill 1234

意思：
结束进程号为 1234 的进程。

面试说：
ps 用来看进程，top 用来看资源占用，kill 用来结束指定进程。

六、删除文件

1. rm file

意思：
删除文件。

2. rm -r dir

意思：
递归删除目录 dir。

3. rm -rf dir

意思：
强制递归删除目录 dir，不提示确认。

注意：
rm -rf 很危险，面试里可以说实际操作前要确认路径。

4. rm -rf /tmp/*

意思：
删除 /tmp 目录下的所有内容，但保留 /tmp 目录本身。

面试说：
删除目录用 rm -r，强制删除用 rm -rf，但生产环境要非常小心，先确认路径。

七、脚本开头

1. #!/bin/sh

意思：
告诉系统这个脚本用 /bin/sh 来解释执行。

2. #!/bin/bash

意思：
告诉系统这个脚本用 bash 来解释执行。

这行叫：
shebang。

面试说：
Linux 脚本常用 #!/bin/sh 或 #!/bin/bash 开头，用来指定脚本解释器。

八、命令连接符

1. cmd1 && cmd2

意思：
cmd1 执行成功后，才执行 cmd2。

例子：
mkdir test && cd test

意思：
创建 test 目录成功后，再进入 test 目录。

2. cmd1 || cmd2

意思：
cmd1 执行失败后，才执行 cmd2。

3. cmd1 ; cmd2

意思：
不管 cmd1 成功还是失败，都会执行 cmd2。

面试说：
&& 表示前一个成功才执行后一个；|| 表示前一个失败才执行后一个；; 表示顺序执行，不管成功失败。

九、输入输出重定向

1. > file

意思：
把输出写入 file，覆盖原内容。

例子：
echo hello > a.txt

意思：
把 hello 写入 a.txt，如果原来有内容会被覆盖。

2. >> file

意思：
把输出追加到 file 后面。

3. 2> error.log

意思：
把错误输出写入 error.log。

4. 2>&1

意思：
把标准错误输出合并到标准输出。

5. 1>&2

意思：
把标准输出重定向到标准错误输出。

面试说：
Linux 里 1 表示标准输出，2 表示标准错误。重定向可以把输出写到文件或合并输出流。

十、复制文件

1. cp f1.txt f2.txt

意思：
把 f1.txt 复制成 f2.txt。

面试说：
cp 用于复制文件或目录。

十一、大小写转换

1. tr a-z A-Z

意思：
把输入流中的小写字母转换成大写字母。

例子：
echo hello | tr a-z A-Z

输出：
HELLO

面试说：
tr 可以对字符流做替换或转换，比如小写转大写。

十二、tar 压缩和解压

1. tar -xzvf filename.tgz

意思：
解压 filename.tgz 文件。

参数解释：
x = extract，解压
z = gzip，表示 gzip 格式
v = verbose，显示过程
f = file，后面跟文件名

2. tar -czvf filename.tgz dir

意思：
把 dir 目录压缩成 filename.tgz。

c = create，创建压缩包。

面试说：
tar -xzvf 用来解压 tgz 文件，tar -czvf 用来创建 tgz 压缩包。

十三、校验文件

1. md5sum file

意思：
计算 file 的 MD5 校验值。

用途：
判断文件是否被篡改或传输是否完整。

面试说：
md5sum 可以查看文件校验码，用于校验文件完整性。

十四、网络命令

1. ping IP或域名

意思：
测试网络是否基本连通。

例子：
ping baidu.com

如果有回复：
说明网络基本可达。

2. curl URL

意思：
请求一个 HTTP 接口或网页。

例子：
curl https://jerry-insight.onrender.com/api/health

意思：
请求后端健康检查接口。

3. ss -lntp

意思：
查看当前监听的 TCP 端口和对应进程。

参数：
l = listening，只看监听端口
n = 数字显示端口，不解析成服务名
t = TCP
p = 显示进程

4. netstat -tulnp

意思：
查看端口监听情况。

面试说：
ping 用来测网络连通，curl 用来测接口，ss 或 netstat 用来看端口是否监听。

十五、iptables

iptables 是什么：
Linux 下常见的防火墙工具，用来配置 TCP/IP 包过滤规则。

面试说：
iptables 可以控制哪些数据包允许通过，哪些要丢弃，常用于防火墙和网络访问控制。

十六、vi / vim

1. :q
退出。

2. :w
保存。

3. :wq
保存并退出。

4. :q!
不保存，强制退出。

面试说：
vi 里 :q! 是不保存强制退出。

十七、查看动态库

1. ldd 程序名

意思：
查看一个程序依赖了哪些动态库。

面试说：
ldd 可以查看程序运行依赖的共享库。

十八、定时任务 crontab

格式：
分 时 日 月 周 命令

例子：
0 13,20 * * 1,2,3,4,5 mybackup

意思：
周一到周五，每天 13 点和 20 点执行 mybackup。

解释：
0 = 第 0 分钟
13,20 = 13 点和 20 点
* = 每天
* = 每月
1,2,3,4,5 = 周一到周五

十九、挂载 / 卸载

1. mount

意思：
挂载文件系统。

2. umount

意思：
卸载文件系统。

注意：
是 umount，不是 unmount。

3. mount -a

意思：
挂载 /etc/fstab 中定义的所有文件系统。

面试说：
mount 用来挂载，umount 用来卸载，mount -a 会按照 /etc/fstab 批量挂载。

二十、网络协议重点

1. TCP / UDP

TCP：
面向连接，可靠传输，有确认、重传、顺序控制。
适合 HTTP、文件传输。

UDP：
无连接，不保证可靠，但速度快。
适合直播、游戏、语音。

2. TCP 三次握手

客户端发 SYN。
服务端回 SYN + ACK。
客户端回 ACK。

作用：
确认双方收发能力正常，建立连接。

3. TCP 四次挥手

一方发 FIN。
另一方回 ACK。
另一方再发 FIN。
一方回 ACK。

原因：
TCP 是全双工，两个方向都要分别关闭。

4. HTTP / HTTPS

HTTP：
明文传输。

HTTPS：
HTTP + TLS 加密。
作用是加密、防篡改、身份认证。

5. GET / POST

GET：
一般用于获取数据，参数常在 URL。

POST：
一般用于提交数据，参数在请求体。

6. 常见状态码

200：成功
301 / 302：重定向
400：请求参数错误
401：未认证
403：无权限
404：资源不存在
500：服务端错误
502：网关错误
504：网关超时

7. DNS

DNS 是什么：
把域名解析成 IP 地址。

例子：
访问 www.baidu.com 前，浏览器要先通过 DNS 找到它对应的服务器 IP。

8. FTP

FTP 是文件传输协议，用于客户端和服务器之间上传、下载文件。

9. IP / 子网掩码 / 网关

IP：
主机地址。

子网掩码：
判断哪些 IP 属于同一网段。

网关：
访问其他网段时经过的出口。

10. 路由

路由决定数据包下一跳往哪里走。

默认路由：
没有更具体路由时走的出口。

二十一、SQL 基础

1. MySQL 分页

每页 10 条，查第 5 页：
SELECT * FROM table_name LIMIT 40, 10;

意思：
跳过前 40 条，取 10 条。

为什么是 40：
(5 - 1) * 10 = 40

2. 查询每门课都大于 80 分的学生

表字段：
name, kecheng, fenshu

SQL：
SELECT name
FROM table_name
GROUP BY name
HAVING MIN(fenshu) > 80;

意思：
按学生分组，如果这个学生最低分都大于 80，就说明每门课都大于 80。

二十二、排查题

1. 网站打不开怎么排查？

思路：
1. 本机网络是否正常
2. DNS 是否解析
3. ping 目标 IP 是否通
4. 端口是否开放
5. 服务是否启动
6. 防火墙 / 安全组
7. 查看服务日志
8. 看 HTTP 状态码

2. 服务器磁盘满了怎么办？

命令：
df -h
du -sh *

思路：
先用 df -h 看哪个分区满，再用 du -sh * 找大目录。重点看日志、缓存、临时文件，删除前确认是否可删。

3. 大日志统计出现最多的 Top 10 IP

思路：
不能一次性读入内存。
一行一行流式读取，解析 IP，用字典计数。
如果 IP 太多，按 hash 分片成多个小文件，分别统计 Top 10，最后合并。

4. 端口不通怎么排查？

思路：
1. 服务是否启动
2. 是否监听正确端口
3. 是否监听 0.0.0.0，而不是只监听 127.0.0.1
4. 防火墙 / 安全组是否放行
5. 客户端网络是否正常

二十三、结合我的经历怎么说

Linux 经验：
我有基础 Linux 操作经验，主要来自毕业设计的树莓派平台。树莓派跑的是 Raspberry Pi OS / Debian 系 Linux，我通过 SSH 登录，在终端运行 Python 脚本做数据采集和算法测试。Agent 项目部署 FastAPI 后端时，也接触过端口、环境变量和服务启动命令。运维经验不算深，但基础命令和排查思路我正在补。

网络协议：
我了解 TCP/IP、HTTP、DNS、端口、路由这些基础概念。项目部署时也接触过 HTTP API、端口监听、CORS、健康检查等。通信网络软件方向我还需要继续深入，但我愿意从基础测试、日志分析和协议学习开始。

二十四、Java 只看一点

1. == 和 equals
==：
基本类型比较值；对象比较引用地址。

equals：
通常用于比较对象内容。

2. HashMap 同 key
map.put("name", null);
map.put("name", "Jack");
map.get("name");

结果：
Jack

原因：
同一个 key 后写入的 value 会覆盖前面的 value。

3. 构造方法
构造方法名和类名相同。
构造方法没有返回值，不能写 void。
一个类可以有多个构造方法。

4. List 常见实现
ArrayList
LinkedList
Vector

5. Map 常见实现
HashMap
TreeMap

二十五、最后背诵版

我这场主要准备 Linux 基础命令、网络协议和排查思路。Linux 方面我重点掌握 chmod、export、cat、more、tail、df、du、ps、top、rm、tar、md5sum、ping、curl、ss、iptables、vi 等命令。网络方面我重点掌握 TCP/UDP、三次握手、HTTP/HTTPS、DNS、IP、子网掩码、网关和路由。

我的实际 Linux 经验主要来自毕业设计的树莓派嵌入式 Linux，通过 SSH 登录 Raspberry Pi OS，在终端运行 Python 脚本做数据采集和算法测试。Agent 项目部署时也接触过 FastAPI 服务启动、端口、环境变量和健康检查。
