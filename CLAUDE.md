# 智能课程教学平台（智课系统 V2）

## 项目简介
面向教师和学生的智能课程教学平台。一期为 Web 平台：课程建设、章节目录（AI 识别）、PPT+配音连播教学、班级管理、知识库问答、题库与章节练习、作业、考试（组卷/防作弊/批改/统一出分）、学习进度与统计。

来源：https://github.com/yunduomenghuale/zhike

## 技术栈
- 后端：Python + Django 5 + DRF（`backend/`），JWT 认证，默认 **MySQL 8**（`DATABASE_URL=mysql://…`；本地库 `zk`，专用账号 `zk`，E2E 用 `zk_e2e`）。`DATABASE_URL` 可切 SQLite（`sqlite`，零依赖/副本演练）或 Postgres；迁移细节见 `docs/MySQL切换-实施设计与冲突评审.md`
- 前端：Vue 3 + Vite + Element Plus + Pinia（`frontend/`）
- AI：mock / DeepSeek / 通义千问 / 本地模型服务（OpenAI 兼容）/ 系统内置模型（local）等 Provider，**按能力（chat/embed/rerank/tts）分别配置**（管理端 AICapabilityConfig 或 env 派生），TTS 配音（DashScope qwen3-tts-flash）。系统内置模型：向量化内置 BGE-M3、重排序内置 Qwen3-Reranker-0.6B（`apps/ai/local_models.py`，权重在 `backend/data/models/`，ModelScope 惰性下载/`manage.py download_models` 预热/镜像 PRELOAD_MODELS 预置）

## 目录结构
- `backend/apps/`：users / courses / classroom / knowledge / questions / homework / exams / ai / analytics / platform_admin
- `frontend/src/views/`：teacher / student / admin 三端页面
- `docs/需求对照排查.md`：需求 V1.1 对照排查与本期修复记录（重要，持续维护）
- `智能课程教学平台需求规格说明书.docx`：需求基线（V1.1）

## 启动方式
- 后端：`cd backend && venv\Scripts\python.exe manage.py migrate && venv\Scripts\python.exe manage.py runserver 127.0.0.1:8005`
  - 数据库：本地 MySQL `zk`（`DATABASE_URL=mysql://zk:zk123456@127.0.0.1:3306/zk`）；`.env` 不入库，从 `.env.example` 复制后按需填写
  - 改代码/改 `.env` 必须**杀进程完整重启**（autoreloader 子进程会继承旧 `os.environ`；`--noreload` 不热加载）
- 前端：`cd frontend && npm install && npm run dev`（5273）；或仓库根 `node serve-local.js`（serve 构建产物 + 代理 8005，改源码需先 `npm run build`）

## 关键约定
- 统一响应 `{code, message, data}`；视图集继承 `BaseModelViewSet`
- 角色权限：`IsTeacher / IsStudent / IsTeacherOrReadOnly / IsPlatformAdmin`
- 成绩可见性：考试 `score_released`、作业 `correct_status=returned` 后学生才可见分数（序列化器按角色隐藏）
- 学习进度：`VideoWatchProgress`（学生×视频唯一），前端每 10 秒上报，断点续播
- 作业/考试题目均以快照冻结，发布后不可改题
- 注册（2026-09-08 恢复开放）：曾于 2026-08-21 关闭，现恢复原注册功能（教师/学生自助注册，注册即登录）；账号也可由管理员单个创建或 Excel 批量导入（`platform_admin/user_import.py`，初始密码 `Zk+用户名后6位`，导入/管理员重置密码后 `must_change_password=True`，前端 MainLayout 弹窗提示改密可跳过）
- 登录态（2026-08-27）：access 12h / refresh 7d；前端 `api/request.js` 已实现 401 静默续期（单飞并发去重 + 重放原请求，刷新也失败才登出），登录态最长 7 天

## 当前状态（2026-10-30）
- 已完成：组织重构 P0–P5（学籍门控 / 整班毕业 / 权限锚点 `Course.teacher` / 三类批量导入）、**MySQL 迁移（本地 + 生产）**、AI 异步任务（AITask）、QA 质量看板 Phase 1+2、班级学习数据 Excel 导出
- 测试基线：MySQL 与 SQLite 各 **712 例全绿**；专项 `scripts/mysql_upgrade_check.py` 57 项；P1/P4/P5 校验脚本 64/41/39
- 待办见 `docs/阶段计划与进度.md`；QA 看板 Phase 3/4 未做

## 生产部署（2026-10-30 更新：迁至内网机 + MySQL）

### 当前环境
- 服务器：`192.168.3.145`（CentOS 8.3，32 核共用机，跑着 40+ 其他项目的演示容器 —— **只动 `zhike_v2_*` 容器，别碰 `test-mysql80` / `cv_*` 等**）
- 登录：`lymatrix2020`，**密码认证**（原公钥已失效），`sudo` 免密；本机走 paramiko（`PYTHONPATH=D:/tmp/pylibs` + `D:/tmp/ssh_run.py`）。**SFTP 不可用**（put 报 ENOENT）→ 用 `D:/tmp/ssh_push.py` 分块 base64 上传（≤60KB/块，过大服务器断连；Git Bash 会把 `/home/xxx` 实参改写成 Windows 路径，远端路径用环境变量 `REMOTE_PATH` 传）
- 访问：`http://192.168.3.145:8088`（用机器已有的 nginx 1.27.3 镜像直接发布 8088）
- 代码：`/data/zhike-v2/`，**不是 git 仓库**，靠打包上传：`git archive HEAD backend deploy` → 上传 → 解压。Windows 导出为 CRLF（`.sh` 由 `.gitattributes` 强制 LF）
- 华为云 `124.70.107.64` **已弃用**（2026-10-30 确认不再使用），整机备份在 `D://124.70.107.64服务器数据资源//`

### 数据库（2026-10-30 起 MySQL）
- `deploy/.env.production`：`DATABASE_URL=mysql://root:test%402021@192.10.0.3:3306/zk`（密码里的 `@` 编码为 `%40`）
- **`192.10.0.3` 是本机 `test-mysql80` 容器**（MySQL 8.0.22 / utf8mb4_0900_ai_ci / 时区表已灌 1826 条），在 `bnet-test` 网络（192.10.0.0/16）→ compose 里 backend 必须挂 `bnet-test`(external)，否则容器根本连不上（宿主能连、容器跨 bridge 没路由）
- 共享实例 100+ 个库：**只操作 `zk`**；`test-mysql80` 被其他项目共用，**不要 stop/restart**
- SQLite 已冻结：旧库 `data/db.sqlite3` 保留仅作回滚；切换前备份在 `data/backups/`
- 回滚：`.env.production` 把 `DATABASE_URL` 改回 `sqlite` → `docker compose up -d backend`；镜像回滚 `docker tag zhike-v2-backend:p5base zhike-v2-backend:latest` 再重建
- 备份：`backups/backup.sh`（mysqldump 借 `docker run --network bnet-test mysql:8.0`，`MYSQL_PWD` 传密码，`--single-transaction` 不锁表，gzip 约 27MB/份）**每日 03:30** 由 crontab 触发，**保留 14 天**，存 `data/backups/mysql/`；media 走 `rsync -a` 增量（不带 --delete）；日志 `backups/backup.log`；仓库留档 `deploy/backup-mysql.sh`
- 手工恢复：`zcat data/backups/mysql/db-YYYYMMDD.sql.gz | sudo docker exec -i test-mysql80 sh -c 'mysql -uroot -p"test@2021" zk'`

### 构建与发布
- 常规：`cd deploy && docker compose up -d --build backend`
- ⚠️ `requirements.txt` 一改 → `COPY requirements.txt` 层失效 → 重装 torch（209MB，`download.pytorch.org` 国内极慢，实测卡 15 分钟）。应急用 `deploy/Dockerfile.fast`（`FROM zhike-v2-backend:p5base` + mysqlclient + `COPY . /app`，**53 秒**）；但**新增任何依赖都必须回完整 `Dockerfile.backend`**
- `.env.production` 改动：`env_file` 在容器创建时注入，`restart` 不会重读，必须 `up -d --force-recreate backend`
- 生产无 TLS：必须保留 `DJANGO_SECURE_SSL_REDIRECT=False`（否则非 DEBUG 下默认 301 跳 https，API 全废）
- **打包会带上本地 `deploy/.env.production`**（gitignore 但 tar 不忽略）：2026-08-17 曾用本地旧版覆盖服务器配置，把 TTS 与 SSL 修复还原——服务器改过的配置要同步回本地
- 前端 dist：bind 挂载的是目录本身，只能 `rm -rf dist/*` 清内容（删目录会因 inode 变化导致挂载失效、全站 403）；先确认 `dist/assets/` 完整再打包（2026-08-17 曾因残缺 dist 全站 404）
- 移动端 H5：`/m/` 子路径，nginx 挂 `/usr/share/nginx/m`（**不可挂 `html/m`**，2026-08-18 曾致 Web 中断 2 分钟）；`app/` 用 `npm run build:h5`

### 业务约束（容易踩）
- TTS 必须用 **`qwen3-tts-flash`**（DashScope 原生 multimodal-generation 端点 + Cherry 发音人）；`qwen-tts` 2026-10-13 已下线（404），`cosyvoice-v1` 不被该端点接受（400）
- 配音/讲稿都是**分批生成**：`generate-audio`（默认 limit 3）、`generate-script`（默认 limit 6），前端循环调用直到 `done=true`；一次性生成会超 nginx 180s 变 504/499

### 历史（124.70.107.64 时代，已下线）
- 2026-08-24 / 08-27 / 09-02 / 09-08 的几次上线记录见 git log；旧代码备份 `/data/zhike-v2/backend.bak.*`；新机 deploy 备份 `deploy.bak-20261030-1420`

## 注意事项
- **DRF FileField 绝对 URL 依赖 Host 端口**（2026-09-17 修复）：DRF 序列化 FileField（知识库资料 file、作业/提交附件 attachment、课件 file）时会 `request.build_absolute_uri()` 生成绝对 URL，容器 nginx 必须用 `proxy_set_header Host $http_host`（保留端口）；此前用 `$host`（丢端口）导致所有文件链接变成 `http://ip/media/...`（80 端口），而 80 端口是宿主机 nginx/默认站（/media 不存在）→ 404 页来自同机 cv_nginx（1.31.2），极易误判为本系统问题。改配置只需 scp deploy/nginx.conf + `docker compose restart frontend`（scp 覆盖不换 inode，单文件 bind mount 安全）
- PPT 页面渲染管线：Windows 开发机走 PowerPoint COM；Linux 生产走 LibreOffice（trixie 镜像自带 25.x）转 PDF → pypdfium2 出图（150 DPI，纯 pip 依赖，已弃用 pdftoppm/poppler）；老格式 .ppt 先预转 .pptx 再渲染；Windows 中文字体 → 开源字体替换映射见 `deploy/fonts.conf`（挂载为容器 `/etc/fonts/local.conf`）
- 向量检索为全表暴力余弦；**课件 PPT 与教辅资料均已入向量库**（2026-10-14）：`KnowledgeChunk` 片段来源二选一（`material` 或 `ppt`，每页一片段、页码保留），PPT 上传解析成功即入库（`apps/ai/services.py ingest_ppt_pages`，失败静默、QA 有原文拼接兜底）；换向量模型/修复 mock 向量后用「重建向量」刷新（教师端课程级/管理端/`manage.py rebuild_vectors --course|--material|--ppt|--all`，四条出错防线：事前校验失败即止、先算后删事务替换、单项失败可续跑、全链路 `allow_fallback=False`）；DashScope text-embedding-v3 批量上限 10 条/批，provider 层已自动分批
- 能力-服务商白名单（`AICapabilityConfig.CAPABILITY_PROVIDERS`）：对话（chat）= DeepSeek/通义千问/本地模型服务/模拟模式；**向量化与语音合成仅通义千问/本地模型服务**（DeepSeek 无 embed/TTS 接口；模拟模式 64 维假向量会污染真实向量空间）；**向量化/重排序另开放系统内置模型 local**（BGE-M3 / Qwen3-Reranker-0.6B，本机 CPU 推理，无需 Key/接口地址），保存与连接测试接口双重校验

## 安全基线（2026-09-02）
- 登录防爆破：同 用户名+IP 连续失败 5 次锁 15 分钟（`users/views.py` LoginView；计数用 `login_fail` 文件缓存 **跨 worker 共享**，勿改回 locmem——2 worker 下 locmem 会把阈值稀释成约 10 次且不稳定，已实测）；初始密码规则（Zk+学号后6位）为需求约定保留，首登改密维持前端提示可跳过
- media 路径不可预测：PPT 页图目录 `ppt_pages/<sha256(ppt:{id}:{SECRET_KEY})[:16]>`（`ppt_parser.ppt_pages_dirname`，SECRET_KEY 换了旧 URL 即全失效需重跑 obfuscate_media）；课件/资料/作业附件文件名 uuid（各 models.py 的 upload_to callable）；头像/TTS 原本就是 uuid
- 上传白名单：Material（pdf/word/ppt/txt/md，50MB）、HomeworkSubmission 附件（同教师侧，20MB）、课件（ppt/pptx/pdf，100MB）——防 media 同域存储型 XSS
- nginx 兜底：`/media/` 全局 nosniff；html/svg/js 扩展强制 `application/octet-stream` 下载
- 存量迁移命令 `manage.py obfuscate_media`（幂等可重跑）：改 ppt_pages 目录名并重写 parsed_pages/video scripts 引用、附件 uuid 重命名
- 未修 / 待办（2026-10-30 复核）：无 TLS（生产仍明文，仅代码就绪）；Django 5.1.4 落后安全补丁；业务外键全 CASCADE；Django 权限体系零使用（自建 role + 自定义权限类）；向量检索全量读（片段上万需外置向量库）；QA 看板 Phase 3/4
- 已修（原 2026-09-02 中危清单，P5 收口）：JWT 吊销、交卷行锁、全站限流、AI 日配额、Mock 回退显性化、`/api/docs/` 生产关闭；SQLite WAL 问题随切 MySQL 一并消失
