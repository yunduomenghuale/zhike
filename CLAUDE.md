# 智能课程教学平台（智课系统 V2）

## 项目简介
面向教师和学生的智能课程教学平台。一期为 Web 平台：课程建设、章节目录（AI 识别）、PPT+配音连播教学、班级管理、知识库问答、题库与章节练习、作业、考试（组卷/防作弊/批改/统一出分）、学习进度与统计。

来源：https://github.com/yunduomenghuale/zhike

## 技术栈
- 后端：Python + Django 5 + DRF（`backend/`），JWT 认证，默认 SQLite（`DATABASE_URL` 可切 Postgres）
- 前端：Vue 3 + Vite + Element Plus + Pinia（`frontend/`）
- AI：mock / openai 兼容 / 智谱等 Provider，TTS 配音（DashScope）

## 目录结构
- `backend/apps/`：users / courses / classroom / knowledge / questions / homework / exams / ai / analytics / platform_admin
- `frontend/src/views/`：teacher / student / admin 三端页面
- `docs/需求对照排查.md`：需求 V1.1 对照排查与本期修复记录（重要，持续维护）
- `智能课程教学平台需求规格说明书.docx`：需求基线（V1.1）

## 启动方式
- 后端：`cd backend && venv\Scripts\python.exe manage.py migrate && manage.py runserver 127.0.0.1:8005`（venv 已建；`.env` 已随仓库提供，AI_PROVIDER=mock）
- 前端：`cd frontend && npm install && npm run dev`（默认 5273 端口）

## 关键约定
- 统一响应 `{code, message, data}`；视图集继承 `BaseModelViewSet`
- 角色权限：`IsTeacher / IsStudent / IsTeacherOrReadOnly / IsPlatformAdmin`
- 成绩可见性：考试 `score_released`、作业 `correct_status=returned` 后学生才可见分数（序列化器按角色隐藏）
- 学习进度：`VideoWatchProgress`（学生×视频唯一），前端每 10 秒上报，断点续播
- 作业/考试题目均以快照冻结，发布后不可改题

## 当前状态（2026-07-28）
- 已完成：学习进度记录/断点续播、章节练习 UI、考试主观题批改、统一出分、作业成绩发布
- 待办见 `docs/需求对照排查.md` 第六节（P2/P3）
- 无自动化测试；AI 生成、PPT 解析为同步执行（待异步化）

## 生产部署（2026-08-17 更新）
- 服务器：华为云 `124.70.107.64`（CentOS 7，root），代码位于 `/data/zhike-v2/`
- 方式：Docker Compose（`deploy/`），`zhike_v2_backend`（gunicorn，容器内 8000，**不发布宿主端口**）+ `zhike_v2_frontend`（nginx，对外 **8088**，华为云安全组已放行；主线曾改 5273 但安全组未放行该端口，2026-08-17 实测外部不可达后回退 8088）
- 数据：**bind mount 到数据盘项目目录**（`/data/zhike-v2/{data,media,staticfiles}` → 容器 `/app/{data,media,staticfiles}`），不再使用根盘 named volume；生产配置在 `deploy/.env.production`（gitignore，仅存于服务器）
- 更新流程：本地 `npm run build`（**先确认 `dist/assets/` 产物完整再打包**，2026-08-17 曾因本地上传残缺的 dist 导致全站 404）→ 打包上传 → `cd /data/zhike-v2/deploy && docker compose up -d --build`
- 前端 dist 更新注意：bind 挂载的是 `frontend/dist` 目录本身，**不能 `rm -rf dist` 再解压**（目录 inode 变化会导致容器内挂载失效、全站 403）；应 `rm -rf dist/*` 只清内容，或替换后 `docker compose restart frontend`
- `.env.production` 改动注意：`env_file` 在容器创建时注入，`docker compose restart` **不会**重读，需 `docker compose up -d --force-recreate backend`
- 生产无 TLS：`deploy/.env.production` 必须含 `DJANGO_SECURE_SSL_REDIRECT=False`（主线 settings 在非 DEBUG 下默认 301 跳转 https，前端 nginx 仅 80 端口，不开会导致 API 全部 301 不可用）
- **打包部署会携带本地 `deploy/.env.production`**（gitignore 但本地磁盘存在，tar 不忽略）：2026-08-17 曾因本地旧版（cosyvoice-v1、无 SSL 行）上传覆盖服务器修正版，导致 TTS 与 SSL 修复被还原。服务器改过的配置必须同步回本地，当前本地已是正确版本（qwen-tts + SSL=False）
- TTS 模型：必须用 `qwen-tts`（DashScope 原生 multimodal-generation 端点 + Cherry 发音人）；`cosyvoice-v1` 不被该端点接受（400 InvalidParameter），如需 cosyvoice 要走 WebSocket（未实现）
- AI 配音为**分段生成**（2026-08-17）：`POST /catalogs/{id}/generate-audio/` 带 `limit`（默认 3），每页合成后即时落库，前端循环调用直至 `done=true`，按钮实时显示 `配音 x/y`；此前 18 页同步合成超 nginx 180s 导致 504 无反馈
- 讲解稿同为**分批生成**（2026-08-18）：`POST /catalogs/{id}/generate-script/` 带 `limit`（默认 6），每批一次 AI 调用、批后落库，前端循环调用显示 `讲稿 x/y`；此前 44 页一次性生成（含 retries=3 重试）超 180s 被 499。换新版本 PPT 或 `force=true` 自动重置讲稿重新生成
- 同机系统（2026-08-17 清理后）：仅 **cv_\***（校园车辆，8080/8081/3308 均绑 127.0.0.1，线上运行勿动）与本系统；virtual-human、chaoxingai 已停止清理（容器/镜像/孤立卷已删，项目数据目录保留在 /data/Virtual-Human、/data/AIzhike）
- 端口占用（2026-08-17 外网实测+全端口抽样）：对外可达 22 sshd / 80 宿主机 nginx / 8088 本系统前端；**安全组放行且空闲可用：443、9527、21、1433、3389、8082、8084**（8080/8081 放行但被 cv 绑 127.0.0.1 占用勿用）；全端口间隔抽样证实**无整段开放**，放行均为上述离散端口；未放行：5273、8005、3306、3307、3308、6380 等
- 旧代码备份：`/data/zhike-v2/backend.bak.20260817`（可回滚，确认稳定后可删）

## 注意事项
- PPT 页面渲染管线：Windows 开发机走 PowerPoint COM；Linux 生产走 LibreOffice（trixie 镜像自带 25.x）转 PDF → pypdfium2 出图（150 DPI，纯 pip 依赖，已弃用 pdftoppm/poppler）；老格式 .ppt 先预转 .pptx 再渲染；Windows 中文字体 → 开源字体替换映射见 `deploy/fonts.conf`（挂载为容器 `/etc/fonts/local.conf`）
- 向量检索为全表暴力余弦，embed 失败会静默回退 Mock 向量
