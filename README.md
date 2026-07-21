# 智能课程教学平台

面向教师和学生的智能课程教学平台。一期为 **Web 端**（前后端分离），深度结合大模型完成
课程目录识别、PPT 讲解稿 / AI 配音教学视频、知识库 RAG 问答、自动出题、作业/考试等能力。

> 需求详见 [`智能课程教学平台需求规格说明书.docx`](./智能课程教学平台需求规格说明书.docx)。

## 技术选型

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | **Python 3.13 + Django 5 + Django REST Framework** | 生态成熟、Admin 开箱即用，适合快速搭业务后台 |
| 认证 | **JWT**（djangorestframework-simplejwt） | 前后端分离无状态鉴权 |
| API 文档 | **drf-spectacular**（OpenAPI / Swagger UI） | `/api/docs/` |
| 前端 | **Vue 3 + Vite + Element Plus + Pinia + Vue Router** | 国内后台管理主流组合 |
| 数据库 | **SQLite（起步）** | 模型层用 `BaseModel` 抽象，可平滑迁移 PostgreSQL |
| 向量检索 | 起步用**表存 embedding + 暴力余弦**，抽象成 `VectorStore` 接口 | 后续可换 pgvector / Milvus / Qdrant |
| 大模型 | **国内大模型**（通义 / 智谱 / 百度），封装为可切换 `AIProvider` | 支持 `mock` 模式先跑通业务流 |

## 目录结构

```
智能课程教学平台/
├── backend/                 # Django 后端
│   ├── config/              # 项目配置（settings / urls / wsgi / asgi）
│   ├── apps/
│   │   ├── common/          # 公共基类：BaseModel、统一响应、分页
│   │   ├── users/           # 用户与鉴权（教师/学生/管理员）
│   │   ├── courses/         # 课程、目录、PPT、教学视频
│   │   ├── classroom/       # 班级、班级学生、邀请码
│   │   ├── knowledge/       # 教辅资料、知识库片段、问答记录
│   │   ├── questions/       # 题库、答题记录
│   │   ├── homework/        # 作业、作业提交
│   │   ├── exams/           # 试卷、考试、答卷、操作日志
│   │   ├── ai/              # AI Provider 抽象（LLM / Embedding / TTS）
│   │   └── platform_admin/  # 平台管理端（概览、用户、教学监管）
│   ├── manage.py
│   └── requirements.txt
├── frontend/                # Vue 3 前端
│   └── src/
│       ├── api/             # axios 封装与各模块接口
│       ├── layouts/         # 主框架布局
│       ├── router/          # 路由
│       ├── store/           # Pinia 状态
│       └── views/           # 页面（teacher/ student/）
└── README.md
```

## 快速开始

### 后端

```bash
cd backend
py -3.13 -m venv .venv
.venv\Scripts\activate           # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env           # 按需填写大模型 API Key，默认 AI_PROVIDER=mock
python manage.py migrate
python manage.py createsuperuser # 创建平台超级管理员，同时可登录 Django Admin
python manage.py runserver 127.0.0.1:8005
```

- API 根路径：`http://127.0.0.1:8005/api/`
- API 文档：`http://127.0.0.1:8005/api/docs/`
- Django Admin：`http://127.0.0.1:8005/admin/`
- 平台管理端：超级管理员登录前端后，可通过左侧导航进入管理概览、用户管理和教学监管

### 前端

```bash
cd frontend
npm install
npm run dev
```

- 开发地址：`http://127.0.0.1:5273/`
- 通过 Vite 代理将 `/api` 转发到后端 `http://127.0.0.1:8005`

## AI Provider 说明

所有大模型能力通过 `apps/ai` 统一封装，三类能力：

- `chat` — 文本生成（目录识别、讲解稿、出题、RAG 回答、批改）
- `embed` — 文本向量化（知识库入库与检索）
- `tts` — 文本转语音（AI 配音）

通过环境变量 `AI_PROVIDER` 选择实现（`mock` / `zhipu` / `tongyi` / `baidu`）。
默认 `mock`，不需要任何 Key 即可跑通业务流程；接入真实模型时切换 Provider 并填入对应 Key。

## 开发阶段（对齐需求文档）

- **一期**：课程 / 目录 / PPT 视频 / 班级 / 知识库问答 / 题库 / 作业（人工批改）/ 考试（客观题自动评分 + 基础防作弊）
- **二期**：作业与主观题 AI 自动批改、学习预警增强、H5 / 小程序多端扩展
