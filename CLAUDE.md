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

## 生产部署（2026-07-29）
- 服务器：华为云 `124.70.107.64`（CentOS 7，root），代码位于 `/data/zhike-v2/`
- 方式：Docker Compose（`deploy/`），`zhike_v2_backend`（gunicorn，容器内 8000）+ `zhike_v2_frontend`（nginx，对外 **8088**）
- 数据：named volume 持久化 SQLite（`zhike_v2_data`）、media、staticfiles；生产配置在 `deploy/.env.production`
- 更新流程：本地 `npm run build` → 打包上传 → `cd /data/zhike-v2/deploy && docker compose up -d --build`
- 前端 dist 更新注意：bind 挂载的是 `frontend/dist` 目录本身，**不能 `rm -rf dist` 再解压**（目录 inode 变化会导致容器内挂载失效、全站 403）；应 `rm -rf dist/*` 只清内容，或替换后 `docker compose restart frontend`
- 服务器同机还有其它生产系统（cv_*、chaoxingai_*、vh-*、宿主机 nginx:80），部署时不得占用 22/80/443/3306/9527/8080/8081

## 注意事项
- PPT 页面渲染管线：Windows 开发机走 PowerPoint COM；Linux 生产走 LibreOffice（trixie 镜像自带 25.x）转 PDF → pypdfium2 出图（150 DPI，纯 pip 依赖，已弃用 pdftoppm/poppler）；老格式 .ppt 先预转 .pptx 再渲染；Windows 中文字体 → 开源字体替换映射见 `deploy/fonts.conf`（挂载为容器 `/etc/fonts/local.conf`）
- 向量检索为全表暴力余弦，embed 失败会静默回退 Mock 向量
