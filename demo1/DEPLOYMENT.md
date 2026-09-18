# 计算机网络课程辅助教学平台 - 部署操作文档

> **平台名称**：网络学习小伴侣  
> **所属单位**：洛阳理工学院计算机学院  
> **配套教材**：谢希仁《计算机网络教程》（第7版微课版）ISBN: 9787115676825  
> **文档版本**：v1.1（新增HTTPS配置）  
> **更新日期**：2026-09-05  

---

## 目录

1. [系统概述](#1-系统概述)
2. [环境要求](#2-环境要求)
3. [Windows 部署](#3-windows-部署)
4. [Linux 部署](#4-linux-部署)
5. [配置说明](#5-配置说明)
6. [部署验证](#6-部署验证)
7. [日常运维](#7-日常运维)
8. [故障排查](#8-故障排查)
9. [附录](#9-附录)

---

## 1. 系统概述

### 1.1 架构

```
用户浏览器 ──→ nginx (8090) ──→ Node.js (8081)
                 │                   │
                 ├─ 静态文件          ├─ 用户管理API
                 ├─ HTML/CSS/JS       ├─ 知识库API
                 └─ 图片/字体等       ├─ 习题API
                                     └─ 学习统计API
```

- **前端**：原生 HTML/CSS/JavaScript，无框架依赖
- **后端**：原生 Node.js（`http` 模块），无框架
- **反向代理**：nginx，端口 8090 → 静态文件 + `/api/` 代理到 8081
- **数据存储**：JSON 文件本地存储，无需数据库
- **进程守护**：watchdog.js（崩溃自动重启，10秒健康检查）

### 1.2 核心功能模块

| 模块 | 说明 |
|------|------|
| 数字人在线课堂 | 首页 index.html |
| 专题学习模块 | 各章节学习内容 |
| 虚拟仿真实验 | labs/ 目录下实验六/七 |
| 作业习题 | quiz.html + 习题API |
| 学习小伴侣 | AI聊天问答 chat-agent.js |
| 思维导图 | demos/Mind-Map.html + mindmap/ 分章节 |
| 用户管理 | admin.html / teacher.html |
| 首次登录强制改密 | force-change-password.html |

### 1.3 默认账号

| 角色 | 用户名 | 初始密码 | 说明 |
|------|--------|----------|------|
| 管理员 | admin | admin123 | 不受首次登录改密限制 |
| 教师 | teacher | teacher123 | 首次登录需改密 |
| 学生 | 学号 | 学号 | 由教师创建，首次登录需改密 |

---

## 2. 环境要求

### 2.1 软件依赖

| 软件 | 最低版本 | 推荐版本 | 说明 |
|------|----------|----------|------|
| Node.js | v16.0 | v18.x LTS 或 v20.x LTS | 后端运行环境 |
| nginx | 1.18 | 1.24+ | 反向代理与静态文件服务 |
| npm | 8.0+ | 随 Node.js 自带 | 包管理 |

### 2.2 Node.js 依赖包

```
pdf-parse@^1.1.1
```

> 仅一个第三方依赖，其余均使用 Node.js 内置模块。

### 2.3 硬件建议

| 资源 | 最低配置 | 推荐配置 |
|------|----------|----------|
| CPU | 2核 | 4核 |
| 内存 | 2GB | 4GB |
| 磁盘 | 5GB | 20GB（含知识库数据） |
| 网络 | 100Mbps | 1Gbps |

### 2.4 端口规划

| 端口 | 用途 | 进程 |
|------|------|------|
| 8081 | Node.js 后端API | node server.js |
| 8090 | nginx 对外服务 | nginx |
| 80（可选） | 生产环境HTTP | nginx（可改为80） |

---

## 3. Windows 部署

### 3.1 安装 Node.js

1. 访问 [https://nodejs.org/](https://nodejs.org/) 下载 **LTS 版本**（v18.x 或 v20.x）
2. 运行安装程序，选择默认选项即可
3. 验证安装：

```cmd
node --version
npm --version
```

### 3.2 安装 nginx

1. 访问 [https://nginx.org/en/download.html](https://nginx.org/en/download.html) 下载 **Stable version**
2. 解压到 `C:\nginx`（推荐此路径，配置文件已适配）
3. 验证安装：

```cmd
cd C:\nginx
nginx -v
```

### 3.3 部署应用文件

1. 将项目所有文件复制到 `C:\nginx\demo1\` 目录下

   目录结构应如下：
   ```
   C:\nginx\
   ├── conf\
   │   └── nginx.conf          ← nginx配置文件
   ├── demo1\                   ← 应用根目录
   │   ├── server.js            ← 后端入口
   │   ├── watchdog.js          ← 进程守护
   │   ├── config.js            ← 服务器配置
   │   ├── package.json
   │   ├── index.html           ← 首页
   │   ├── login.html
   │   ├── admin.html
   │   ├── teacher.html
   │   ├── quiz.html
   │   ├── force-change-password.html
   │   ├── user-center.html
   │   ├── api-client.js
   │   ├── auth-check.js
   │   ├── utils.js
   │   ├── chat-agent.js
   │   ├── chat-knowledge.js
   │   ├── user-api-router.js
   │   ├── user-data-store.js
   │   ├── quiz-api-router.js
   │   ├── kb-api-router.js
   │   ├── kb-data-store.js
   │   ├── kb-updater.js
   │   ├── start-server.bat     ← 启动脚本
   │   ├── demos\
   │   │   └── Mind-Map.html
   │   ├── mindmap\             ← 免登录思维导图
   │   ├── labs\                ← 虚拟仿真实验
   │   ├── image\               ← 图片资源
   │   ├── common\              ← 公共资源
   │   ├── user-data\           ← 用户数据（JSON）
   │   │   ├── users.json
   │   │   ├── students.json
   │   │   ├── teachers.json
   │   │   ├── classes.json
   │   │   └── ...
   │   ├── kb-data\             ← 知识库数据
   │   └── node_modules\        ← 依赖包
   ├── logs\
   └── temp\
   ```

2. 安装 Node.js 依赖：

```cmd
cd C:\nginx\demo1
npm install
```

### 3.4 配置 nginx

1. 将项目中的 `nginx.conf` 复制到 `C:\nginx\conf\nginx.conf`（如已存在则覆盖）
2. 或手动编辑 `C:\nginx\conf\nginx.conf`，关键配置如下：

```nginx
http {
    server {
        listen       8090;
        server_name  127.0.0.1;

        root C:/nginx/demo1;
        index index.html;
        charset utf-8;

        # API代理到Node.js
        location ^~ /api/ {
            proxy_pass http://127.0.0.1:8081/api/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_read_timeout 300s;
            proxy_send_timeout 300s;
            client_max_body_size 200m;
        }

        # 静态文件
        location / {
            try_files $uri $uri/ =404;
        }

        # HTML不缓存
        location ~* \.html$ {
            add_header Cache-Control "no-cache, no-store, must-revalidate";
        }

        # CSS/JS不缓存
        location ~* \.(css|js)$ {
            add_header Cache-Control "no-cache, no-store, must-revalidate";
        }

        # 图片/字体缓存1小时
        location ~* \.(jpg|jpeg|png|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 1h;
            add_header Cache-Control "public";
        }
    }
}
```

3. 验证配置：

```cmd
cd C:\nginx
nginx -t
```

### 3.5 启动服务

#### 方式一：使用启动脚本（推荐）

```cmd
cd C:\nginx\demo1
start-server.bat
```

脚本会自动：
- 停止旧的 Node.js 进程
- 通过 watchdog.js 启动服务器（崩溃自动重启）
- 前台运行，按 `Ctrl+C` 停止

#### 方式二：手动启动

1. 启动 nginx：

```cmd
cd C:\nginx
start nginx
```

2. 启动 Node.js 后端：

```cmd
cd C:\nginx\demo1
node watchdog.js
```

#### 方式三：后台启动（无窗口）

```cmd
cd C:\nginx\demo1
cscript //nologo start-hidden.vbs
```

### 3.6 设置开机自启（可选）

1. 按 `Win + R`，输入 `shell:startup` 打开启动文件夹
2. 创建快捷方式指向 `C:\nginx\demo1\start-server.bat`
3. 将 nginx 启动也加入启动文件夹（创建 `start-nginx.bat`）：

```bat
@echo off
cd /d C:\nginx
start nginx
```

### 3.7 防火墙配置

```cmd
netsh advfirewall firewall add rule name="网络学习小伴侣-8090" dir=in action=allow protocol=TCP localport=8090
```

---

## 4. Linux 部署

### 4.1 安装 Node.js

#### Ubuntu/Debian

```bash
# 安装NodeSource仓库
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -

# 安装Node.js
sudo apt-get install -y nodejs

# 验证
node --version
npm --version
```

#### CentOS/RHEL/Rocky Linux

```bash
# 安装NodeSource仓库
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -

# 安装Node.js
sudo yum install -y nodejs

# 验证
node --version
npm --version
```

### 4.2 安装 nginx

#### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install -y nginx
```

#### CentOS/RHEL/Rocky Linux

```bash
sudo yum install -y nginx
```

### 4.3 部署应用文件

1. 创建应用目录：

```bash
sudo mkdir -p /opt/network-companion
```

2. 将项目所有文件复制到 `/opt/network-companion/` 目录下

   目录结构应如下：
   ```
   /opt/network-companion/
   ├── server.js
   ├── watchdog.js
   ├── config.js
   ├── package.json
   ├── index.html
   ├── login.html
   ├── admin.html
   ├── teacher.html
   ├── quiz.html
   ├── force-change-password.html
   ├── user-center.html
   ├── api-client.js
   ├── auth-check.js
   ├── utils.js
   ├── chat-agent.js
   ├── chat-knowledge.js
   ├── user-api-router.js
   ├── user-data-store.js
   ├── quiz-api-router.js
   ├── kb-api-router.js
   ├── kb-data-store.js
   ├── kb-updater.js
   ├── demos/
   ├── mindmap/
   ├── labs/
   ├── image/
   ├── common/
   ├── user-data/
   └── kb-data/
   ```

3. 安装依赖：

```bash
cd /opt/network-companion
sudo npm install
```

4. 设置目录权限（假设以 `www-data` 用户运行）：

```bash
sudo chown -R www-data:www-data /opt/network-companion
sudo chmod -R 755 /opt/network-companion
```

### 4.4 配置 nginx

1. 创建 nginx 配置文件：

```bash
sudo nano /etc/nginx/conf.d/network-companion.conf
```

2. 写入以下配置：

```nginx
server {
    listen       8090;
    server_name  _;

    root /opt/network-companion;
    index index.html;
    charset utf-8;

    # API代理到Node.js
    location ^~ /api/ {
        proxy_pass http://127.0.0.1:8081/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        client_max_body_size 200m;
    }

    # 静态文件
    location / {
        try_files $uri $uri/ =404;
    }

    # HTML不缓存
    location ~* \.html$ {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    # CSS/JS不缓存
    location ~* \.(css|js)$ {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    # 图片/字体缓存1小时
    location ~* \.(jpg|jpeg|png|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1h;
        add_header Cache-Control "public";
    }

    # Excel文件MIME类型
    location ~* \.(xlsx|xls)$ {
        add_header Content-Type "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    }
}
```

3. 验证配置并重启 nginx：

```bash
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx
```

### 4.5 配置 systemd 服务（推荐）

1. 创建 systemd 服务文件：

```bash
sudo nano /etc/systemd/system/network-companion.service
```

2. 写入以下内容：

```ini
[Unit]
Description=Network Companion - 计算机网络辅助教学平台
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/network-companion
ExecStart=/usr/bin/node /opt/network-companion/watchdog.js
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal
SyslogIdentifier=network-companion

# 环境变量
Environment=NODE_ENV=production

# 资源限制
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

3. 启动并设置开机自启：

```bash
sudo systemctl daemon-reload
sudo systemctl start network-companion
sudo systemctl enable network-companion
```

4. 查看运行状态：

```bash
sudo systemctl status network-companion
```

### 4.6 防火墙配置

#### Ubuntu/Debian (ufw)

```bash
sudo ufw allow 8090/tcp
sudo ufw reload
```

#### CentOS/RHEL (firewalld)

```bash
sudo firewall-cmd --permanent --add-port=8090/tcp
sudo firewall-cmd --reload
```

### 4.7 SELinux 配置（CentOS/RHEL）

如系统启用 SELinux，需允许 nginx 代理到 8081 端口：

```bash
sudo setsebool -P httpd_can_network_connect 1
sudo semanage port -a -t http_port_t -p tcp 8081
```

---

## 5. 配置说明

### 5.1 后端配置 (config.js)

```javascript
var SiteConfig = {
    SITE_NAME: '网络学习小伴侣',
    SITE_SUBTITLE: '洛阳理工学院计算机学院',
    HOST: '127.0.0.1',        // 后端监听地址
    PORT: 8081,                // 后端监听端口
    getBaseUrl: function() {
        return 'http://' + this.HOST + (this.PORT === 80 ? '' : ':' + this.PORT);
    }
};
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| HOST | 127.0.0.1 | 后端监听地址，生产环境保持 127.0.0.1（仅nginx访问） |
| PORT | 8081 | 后端监听端口，如修改需同步更新 nginx 配置 |

### 5.2 nginx 配置项说明

| 配置项 | 说明 |
|--------|------|
| listen 8090 | 对外服务端口，可改为 80（生产环境） |
| root | 静态文件根目录 |
| proxy_pass | API代理目标（Node.js后端） |
| Cache-Control | HTML/CSS/JS 不缓存，图片缓存1小时 |
| client_max_body_size | 上传文件大小限制 200MB |

### 5.3 watchdog 配置 (watchdog.js)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| MAX_RESTARTS | 50 | 最大重启次数 |
| RESTART_DELAY | 2000ms | 重启延迟 |
| HEALTH_CHECK_INTERVAL | 10000ms | 健康检查间隔 |

### 5.4 修改对外端口

如需将对外端口从 8090 改为 80：

**nginx 配置**（修改 listen）：
```nginx
listen 80;    # 原为 8090
```

---

## 6. 部署验证

### 6.1 基础验证

部署完成后，执行以下验证步骤：

#### Windows

```cmd
:: 1. 检查Node.js后端
curl http://127.0.0.1:8081/api/knowledge

:: 2. 检查nginx代理
curl http://127.0.0.1:8090/api/knowledge

:: 3. 检查首页
curl http://127.0.0.1:8090/

:: 4. 检查登录页面
curl http://127.0.0.1:8090/login.html
```

#### Linux

```bash
# 1. 检查Node.js后端
curl http://127.0.0.1:8081/api/knowledge

# 2. 检查nginx代理
curl http://127.0.0.1:8090/api/knowledge

# 3. 检查首页
curl http://127.0.0.1:8090/

# 4. 检查登录页面
curl http://127.0.0.1:8090/login.html
```

### 6.2 功能验证

1. **浏览器访问** `http://<服务器IP>:8090`
2. **管理员登录**：用户名 `admin`，密码 `admin123`
3. **教师登录**：首次登录跳转强制改密页面
4. **学生登录**：首次登录跳转强制改密页面
5. **知识库**：登录后在聊天框输入问题验证
6. **思维导图**：访问 `http://<服务器IP>:8090/demos/Mind-Map.html`
7. **实验页面**：访问 `http://<服务器IP>:8090/labs/comprehensive-lab.html`

### 6.3 运行自动化测试

```bash
cd /opt/network-companion   # Linux
# 或
cd C:\nginx\demo1            # Windows

node full-system-test.js
```

预期输出：`ALL PASS`（86项测试全部通过）

---

## 7. 日常运维

### 7.1 启停服务

#### Windows

```cmd
:: 启动
cd C:\nginx\demo1
start-server.bat

:: 停止
taskkill /f /im node.exe
cd C:\nginx
nginx -s stop

:: 重启nginx
cd C:\nginx
nginx -s reload
```

#### Linux

```bash
# 启动
sudo systemctl start network-companion
sudo systemctl start nginx

# 停止
sudo systemctl stop network-companion
sudo systemctl stop nginx

# 重启
sudo systemctl restart network-companion
sudo systemctl reload nginx

# 查看状态
sudo systemctl status network-companion
sudo systemctl status nginx
```

### 7.2 查看日志

#### Windows

```
# 后端日志
C:\nginx\demo1\server-watchdog.log

# nginx日志
C:\nginx\logs\access.log
C:\nginx\logs\error.log
```

#### Linux

```bash
# 后端日志（systemd journal）
sudo journalctl -u network-companion -f

# 查看最近100行
sudo journalctl -u network-companion -n 100

# nginx日志
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### 7.3 数据备份

#### 需备份的目录

```
user-data/     ← 用户数据（账号、学生、教师、班级等）
kb-data/       ← 知识库数据
```

#### Windows 备份示例

```cmd
:: 创建带日期的备份
set BACKUP_DIR=C:\backup\%date:~0,4%%date:~5,2%%date:~8,2%
mkdir %BACKUP_DIR%
xcopy C:\nginx\demo1\user-data %BACKUP_DIR%\user-data\ /E /I
xcopy C:\nginx\demo1\kb-data %BACKUP_DIR%\kb-data\ /E /I
```

#### Linux 备份示例

```bash
BACKUP_DIR=/opt/backup/$(date +%Y%m%d)
sudo mkdir -p $BACKUP_DIR
sudo cp -r /opt/network-companion/user-data $BACKUP_DIR/
sudo cp -r /opt/network-companion/kb-data $BACKUP_DIR/
```

#### 自动备份（Linux crontab）

```bash
# 每天凌晨3点自动备份
sudo crontab -e
# 添加：
0 3 * * * tar -czf /opt/backup/companion-$(date +\%Y\%m\%d).tar.gz /opt/network-companion/user-data /opt/network-companion/kb-data
```

### 7.4 更新应用

1. 备份当前数据（见 7.3）
2. 替换应用文件（保留 `user-data/` 和 `kb-data/` 目录）
3. 重启服务：

```bash
# Linux
sudo systemctl restart network-companion

# Windows
taskkill /f /im node.exe
cd C:\nginx\demo1
node watchdog.js
```

---

## 8. 故障排查

### 8.1 页面无法访问（8090端口）

| 排查项 | 命令 |
|--------|------|
| nginx是否运行 | Windows: `tasklist /fi "imagename eq nginx.exe"`<br>Linux: `sudo systemctl status nginx` |
| 端口是否监听 | Windows: `netstat -an /findstr 8090`<br>Linux: `ss -tlnp /grep 8090` |
| 防火墙是否放行 | Windows: `netsh advfirewall firewall show rule name="网络学习小伴侣-8090"`<br>Linux: `sudo ufw status` |
| nginx配置是否正确 | `nginx -t` |

### 8.2 API返回500/502错误

| 排查项 | 命令 |
|--------|------|
| Node.js是否运行 | Windows: `tasklist /fi "imagename eq node.exe"`<br>Linux: `sudo systemctl status network-companion` |
| 后端端口是否监听 | Windows: `netstat -an /findstr 8081`<br>Linux: `ss -tlnp /grep 8081` |
| 后端日志 | Windows: 查看 `server-watchdog.log`<br>Linux: `sudo journalctl -u network-companion -n 50` |
| 直接访问后端 | `curl http://127.0.0.1:8081/api/knowledge` |

### 8.3 登录失败

| 现象 | 排查 |
|------|------|
| 用户不存在 | 检查 `user-data/users.json` 中是否有对应用户 |
| 密码错误 | 确认初始密码（admin=admin123, teacher=teacher123, 学生=学号） |
| 首次登录跳转改密页 | 正常行为，修改密码后即可正常进入 |
| 修改密码后仍跳转改密页 | 检查 `users.json` 中该用户 `firstLogin` 是否为 `false` |

### 8.4 知识库无响应

| 排查项 | 命令 |
|--------|------|
| 知识库API | `curl http://127.0.0.1:8090/api/knowledge` |
| 知识库数据文件 | 确认 `kb-data/` 目录非空 |
| 前端知识库JS | 确认 `chat-knowledge.js` 文件存在且完整 |

### 8.5 nginx 配置修改不生效

```
# 重新加载配置
nginx -s reload

# 如果不生效，完全重启
nginx -s stop
nginx
```

> **注意**：Windows下 nginx 需在 `C:\nginx` 目录运行，且需要 `-p` 参数指定前缀路径。

### 8.6 Node.js 内存溢出

```bash
# 增加Node.js内存限制
# Linux: 修改 systemd 服务文件
Environment=NODE_OPTIONS=--max-old-space-size=4096

# Windows: 修改 watchdog.js 中的 spawn
serverProcess = spawn('node', ['--max-old-space-size=4096', SERVER_FILE], { ... });
```

---

## 9. 附录

### 9.1 完整端口清单

| 端口 | 协议 | 用途 | 方向 |
|------|------|------|------|
| 8081 | HTTP | Node.js 后端 | 内部（仅127.0.0.1） |
| 8090 | HTTP | nginx 对外服务 | 入站（对用户开放） |
| 80 | HTTP | nginx 对外服务（可选） | 入站（对用户开放） |
| 443 | HTTPS | nginx HTTPS（可选） | 入站（对用户开放） |

### 9.2 关键文件清单

| 文件 | 说明 | 重要级别 |
|------|------|----------|
| server.js | 后端入口 | 核心 |
| watchdog.js | 进程守护 | 核心 |
| config.js | 后端配置 | 核心 |
| user-api-router.js | 用户管理API | 核心 |
| user-data-store.js | 用户数据存储 | 核心 |
| quiz-api-router.js | 习题API | 核心 |
| kb-api-router.js | 知识库API | 核心 |
| api-client.js | 前端API请求工具 | 核心 |
| auth-check.js | 前端认证守卫 | 核心 |
| user-data/users.json | 用户账号数据 | 数据 |
| user-data/students.json | 学生数据 | 数据 |
| user-data/teachers.json | 教师数据 | 数据 |
| kb-data/ | 知识库数据 | 数据 |

### 9.3 安全建议

1. **修改默认密码**：部署后立即修改 admin 和 teacher 的初始密码
2. **限制访问**：生产环境通过防火墙限制 8081 端口仅允许 127.0.0.1 访问
3. **启用 HTTPS**：生产环境建议配置 SSL 证书
4. **定期备份**：至少每日备份 `user-data/` 和 `kb-data/` 目录
5. **日志监控**：定期检查 nginx 和 Node.js 日志
6. **系统更新**：保持 Node.js 和 nginx 版本更新

### 9.4 HTTPS 配置（已启用）

系统已启用 HTTPS，使用自签名证书。架构如下：

```
用户浏览器 ──→ https://<IP>:8443 (HTTPS) ──→ nginx ──→ Node.js (8081)
                http://<IP>:8090 (HTTP) ──→ 301重定向 ──→ https://<IP>:8443
```

#### 端口说明

| 端口 | 协议 | 用途 |
|------|------|------|
| 8443 | HTTPS | 对外服务（主要访问入口） |
| 8090 | HTTP | 自动重定向到 8443 |
| 8081 | HTTP | Node.js 后端（仅内部） |

#### SSL证书位置

- **Windows**：`C:\nginx\ssl\server.crt` + `C:\nginx\ssl\server.key`
- **Linux**：`/etc/nginx/ssl/server.crt` + `/etc/nginx/ssl/server.key`

#### 生成自签名证书

**Windows（PowerShell + Node.js）**：

```bash
# 使用Node.js生成（推荐）
node -e "
const crypto=require('crypto');const fs=require('fs');
const {publicKey:pub,privateKey:priv}=crypto.generateKeyPairSync('rsa',{modulusLength:2048});
const pubDer=pub.export({type:'spki',format:'der'});
const privDer=priv.export({type:'pkcs1',format:'der'});
// ... 生成自签名证书并保存为PEM
"
```

**Linux（OpenSSL）**：

```bash
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/server.key \
  -out /etc/nginx/ssl/server.crt \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
sudo chmod 600 /etc/nginx/ssl/server.key
```

#### nginx HTTPS 配置

```nginx
http {
    # HTTP -> HTTPS 重定向
    server {
        listen       8090;
        server_name  _;
        return 301 https://$host:8443$request_uri;
    }

    # HTTPS 服务
    server {
        listen       8443 ssl;
        server_name  _;

        ssl_certificate      C:/nginx/ssl/server.crt;       # Windows
        # ssl_certificate     /etc/nginx/ssl/server.crt;     # Linux
        ssl_certificate_key  C:/nginx/ssl/server.key;       # Windows
        # ssl_certificate_key /etc/nginx/ssl/server.key;     # Linux
        ssl_protocols        TLSv1.2 TLSv1.3;
        ssl_ciphers          HIGH:!aNULL:!MD5;
        ssl_session_cache    shared:SSL:10m;
        ssl_session_timeout  10m;

        root C:/nginx/demo1;        # Windows
        # root /opt/network-companion;  # Linux
        index index.html;
        charset utf-8;

        location ^~ /api/ {
            proxy_pass http://127.0.0.1:8081/api/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 300s;
            client_max_body_size 200m;
        }

        location / {
            try_files $uri $uri/ =404;
        }

        location ~* \.html$ {
            add_header Cache-Control "no-cache, no-store, must-revalidate";
        }

        location ~* \.(css|js)$ {
            add_header Cache-Control "no-cache, no-store, must-revalidate";
        }

        location ~* \.(jpg|jpeg|png|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 1h;
            add_header Cache-Control "public";
        }
    }
}
```

#### 浏览器访问

- 访问 `https://<服务器IP>:8443`
- 首次访问浏览器会提示"不安全"（自签名证书），点击"高级"→"继续访问"即可
- Chrome 可在地址栏输入 `thisisunsafe` 快速跳过警告
- 也可将 `server.crt` 导入到浏览器/系统的"受信任的根证书颁发机构"消除警告

#### 导入证书到受信任根（消除浏览器警告）

**Windows**：

```cmd
certutil -addstore -f "Root" C:\nginx\ssl\server.crt
```

**Linux**：

```bash
sudo cp /etc/nginx/ssl/server.crt /usr/local/share/ca-certificates/network-companion.crt
sudo update-ca-certificates
```

#### 使用 Let's Encrypt 免费证书（需域名+公网）

```bash
# 安装 certbot
sudo apt-get install -y certbot python3-certbot-nginx

# 申请证书（需80端口可用）
sudo certbot --nginx -d your-domain.com

# 自动续期（certbot默认已配置）
sudo systemctl status certbot.timer
```

### 9.5 快速部署检查清单

- [ ] Node.js 已安装（v18+）
- [ ] nginx 已安装
- [ ] 应用文件已部署到目标目录
- [ ] `npm install` 已执行
- [ ] nginx 配置已更新（root 路径、proxy_pass 正确）
- [ ] nginx 配置验证通过（`nginx -t`）
- [ ] Node.js 后端已启动（watchdog.js）
- [ ] nginx 已启动
- [ ] 防火墙已放行 8443 端口（HTTPS）
- [ ] 浏览器可访问 `https://<IP>:8443`
- [ ] HTTP 8090 自动重定向到 HTTPS 8443
- [ ] 管理员可登录（admin/admin123）
- [ ] 教师首次登录跳转改密页
- [ ] 学生首次登录跳转改密页
- [ ] 知识库API正常返回数据
- [ ] 思维导图页面可访问
- [ ] 实验页面可访问

---

> **文档结束**  
> 如有疑问，请联系系统管理员。