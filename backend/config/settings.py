"""Django settings for 智能课程教学平台 (config project)."""
from datetime import timedelta
from django.core.exceptions import ImproperlyConfigured
from pathlib import Path

from dotenv import load_dotenv
import os
import sys

BASE_DIR = Path(__file__).resolve().parent.parent

# 加载 .env（若存在）
load_dotenv(BASE_DIR / ".env")


def env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-dev-key-change-me"
    else:
        raise ImproperlyConfigured("生产环境必须设置 DJANGO_SECRET_KEY")
if not DEBUG and SECRET_KEY in {"change-me-in-production", "django-insecure-dev-key-change-me"}:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY 仍是示例值，请设置强随机密钥")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost" if DEBUG else "")
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("生产环境必须设置 DJANGO_ALLOWED_HOSTS")
if DEBUG and "testserver" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("testserver")  # 便于运行测试与 DRF APIClient

# OpenAPI 文档（/api/schema/ /api/docs/）开关：默认跟随 DEBUG——开发开放、生产关闭
# （P5-A3：生产关闭避免接口结构暴露）；如需在生产临时开放，显式设 DJANGO_ENABLE_API_DOCS=true
API_DOCS_ENABLED = env_bool("DJANGO_ENABLE_API_DOCS", DEBUG)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 第三方
    "rest_framework",
    "rest_framework_simplejwt",
    # JWT 吊销黑名单（P5-A2）：登出/停用后 refresh 不可再换新 access
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    # 业务 app
    "apps.common",
    "apps.users",
    "apps.courses",
    "apps.classroom",
    "apps.knowledge",
    "apps.questions",
    "apps.homework",
    "apps.exams",
    "apps.labs",
    "apps.ai",
    "apps.analytics",
    "apps.platform_admin",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.ai.middleware.AiCallUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# 登录失败计数必须跨 gunicorn worker 共享（locmem 各 worker 独立会把锁定阈值稀释一倍且不稳定），
# 用文件缓存实现共享，无需引入外部服务
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    },
    "login_fail": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / "login_fail_cache",
    },
    # 督管概览重聚合的短 TTL 缓存（trends/alerts）：文件缓存跨 gunicorn worker 一致，
    # 避免每 worker 各算一遍；容器重建即失效，无持久化需求
    "oversight": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / "oversight_cache",
    },
}

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# 数据库：由 DATABASE_URL 决定后端
#   mysql://user:pass@host:3306/dbname    → MySQL 8（当前主线，utf8mb4）
#   postgres://user:pass@host:5432/dbname → PostgreSQL（历史分支，保留）
#   其它/缺省                              → SQLite（零依赖起步、E2E 隔离库、迁移演练副本）
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite")
if DATABASE_URL.startswith(("mysql://", "mysql2://")):
    from urllib.parse import unquote, urlparse

    parsed = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": parsed.path.lstrip("/"),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "127.0.0.1",
            "PORT": parsed.port or 3306,
            # 2 worker × 2 thread：长连接省握手，健康检查防 wait_timeout 掐断
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "charset": "utf8mb4",
                # 不显式给 init_command 时 Django 会按自己的默认 SET sql_mode；
                # 这里钉死严格模式 + 零日期保护，防止服务器侧配置漂移导致静默截断。
                # 有意不含 ONLY_FULL_GROUP_BY：项目有 values().annotate() 组合查询，
                # 保留它会在个别报表接口抛 1055（取舍见 docs/MySQL切换-实施设计与冲突评审.md C-12）
                "init_command": (
                    "SET sql_mode='STRICT_TRANS_TABLES,NO_ZERO_DATE,"
                    "NO_ENGINE_SUBSTITUTION'"
                ),
            },
            # 测试库同字符集/排序规则，避免 CI 与本地行为不一致
            "TEST": {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_0900_ai_ci"},
        }
    }
elif DATABASE_URL.startswith("postgres"):
    # 形如 postgres://user:pass@host:5432/dbname
    from urllib.parse import urlparse

    parsed = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username,
            "PASSWORD": parsed.password,
            "HOST": parsed.hostname,
            "PORT": parsed.port or 5432,
        }
    }
else:
    # SQLITE_PATH 允许把库指向副本，供迁移演练 / E2E 隔离库使用，避免手工改代码。
    # 相对路径按 BASE_DIR 解析；留空则用默认 db.sqlite3。
    _sqlite_name = os.environ.get("SQLITE_PATH") or ""
    if _sqlite_name:
        _sqlite_file = Path(_sqlite_name)
        if not _sqlite_file.is_absolute():
            _sqlite_file = Path(BASE_DIR) / _sqlite_file
    else:
        _sqlite_file = Path(BASE_DIR) / "db.sqlite3"
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(_sqlite_file),
        }
    }

# 测试运行关闭持久连接：测试全程单连接、且常被 TestCase 的 atomic 包裹，
# 任何 close_old_connections() 都会作用到这条连接上，长跑（>CONN_MAX_AGE）时
# 会因"到期"被关掉。置 0 让 close_at 为空，消除这一类假失败。
# （另一条关闭路径是 autocommit 与配置不一致，由 tests_ai_task._InlineThread 处理）
if "test" in sys.argv:
    DATABASES["default"]["CONN_MAX_AGE"] = 0

# 条件唯一约束在 MySQL 上 Django 无法创建（models.W036）。本项目已用
# 「生成列 + 普通唯一索引」等价补齐，见 apps/common/mysql_partial_unique.py
# 与 classroom/0008、courses/0014、knowledge/0012、ai/0017 四个迁移。
# 这里显式静音，避免每次 migrate/check 都刷 7 条警告掩盖真正的问题。
SILENCED_SYSTEM_CHECKS = ["models.W036"]

# ---------------------------------------------------------------------------
# 用户模型与鉴权
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# 管理端限流档位（platform_admin/throttles.py 按请求方法分档，仅管理端生效，不动全局节流）
# admin_read 常规读 / admin_write 干预写 / admin_export 导出 / admin_heavy 重建·测试·导入
ADMIN_THROTTLE_RATES = {
    "admin_read": "120/min",
    "admin_write": "30/min",
    "admin_export": "10/min",
    "admin_heavy": "5/min",
}

# 测试运行（manage.py test）默认关闭限流：throttle 计数存 LocMem 会跨用例累积，
# 干扰既有用例；限流行为由 platform_admin/tests.AdminThrottleTests 专项覆盖。
if "test" in sys.argv:
    ADMIN_THROTTLE_RATES = {scope: None for scope in ADMIN_THROTTLE_RATES}

# 教师端 AI 重操作限流档位（questions/throttles.py 按 action 分档，仅题库
# 导入/AI 生题生效，不动全局节流）
# teacher_ai_generate AI 生题提交（后台 LLM 逐组生成）/ teacher_ai_import 文档导入解析
TEACHER_AI_THROTTLE_RATES = {
    "teacher_ai_generate": "5/min",
    "teacher_ai_import": "10/min",
}

# 测试运行同样关闭教师端 AI 限流（行为由 questions 测试专项用 override_settings 覆盖验证）
if "test" in sys.argv:
    TEACHER_AI_THROTTLE_RATES = {scope: None for scope in TEACHER_AI_THROTTLE_RATES}

# 教师端班级学习数据 Excel 导出限流（analytics/throttles.py）
TEACHER_EXPORT_THROTTLE_RATES = {
    "teacher_export": "10/min",
}

# 测试运行同样关闭导出限流
if "test" in sys.argv:
    TEACHER_EXPORT_THROTTLE_RATES = {scope: None for scope in TEACHER_EXPORT_THROTTLE_RATES}

# ---------------------------------------------------------------------------
# 全站基线限流（P5-C9）：匿名 / 登录 / 登录用户 / AI 问答 分级。
# 计数走默认 LocMem 缓存——多 worker 部署下各进程独立计数（偏宽松，不放大风险）；
# 切 Redis 缓存后自动共享（vectorstore 同款替换位思路）。
# 测试运行关闭全局与专项限流（LocMem 跨用例累积），限流行为由各测试用
# override_settings 专项覆盖。
# ---------------------------------------------------------------------------
GLOBAL_THROTTLE_CLASSES = [
    "apps.common.throttles.GlobalAnonThrottle",
    "apps.common.throttles.GlobalUserThrottle",
]
GLOBAL_THROTTLE_RATES = {
    "anon": "120/min",     # 匿名：登录页/公开探测，正常浏览远低于此
    "user": "1200/min",    # 登录用户：视频 10s 心跳约 6/min，留足余量
    "login": "30/min",     # 登录端点按 IP 从严（另有失败锁定兜底）
    "ai_ask": "60/min",    # AI 问答从严（成本入口；用户级日配额是第二道闸）
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        # 可吊销 JWT（P5-A2）：在 AI 埋点认证之上校验 tokens_invalid_before 作废线
        "apps.users.authentication.RevocableJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.common.response.custom_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": GLOBAL_THROTTLE_CLASSES,
    "DEFAULT_THROTTLE_RATES": {
        **GLOBAL_THROTTLE_RATES,
        "admin_read": "120/min",
        "admin_write": "30/min",
        "admin_export": "10/min",
        "admin_heavy": "5/min",
        "teacher_ai_generate": "5/min",
        "teacher_ai_import": "10/min",
        "teacher_export": "10/min",
    },
}

# 测试运行（manage.py test）默认关闭限流：throttle 计数存 LocMem 会跨用例累积，
# 干扰既有用例；限流行为由各 app 测试专项（override_settings）覆盖。
# 自研 ScopedSettingThrottle 读到 rate=None 直接放行，无需摘类。
if "test" in sys.argv:
    ADMIN_THROTTLE_RATES = {scope: None for scope in ADMIN_THROTTLE_RATES}
    GLOBAL_THROTTLE_RATES = {scope: None for scope in GLOBAL_THROTTLE_RATES}
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
        scope: None for scope in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    }

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "智能课程教学平台 API",
    "DESCRIPTION": "教师端与学生端功能接口",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {
        "CourseStatusEnum": [("active", "启用"), ("inactive", "停用"), ("archived", "归档")],
        "ClassRoomStatusEnum": [("open", "开课中"), ("closed", "已结课")],
        "QuestionStatusEnum": [
            ("draft", "草稿"), ("pending", "待审核"),
            ("published", "已发布"), ("disabled", "停用"),
        ],
        "HomeworkStatusEnum": [("draft", "草稿"), ("published", "已发布"), ("closed", "已截止")],
        "ExamStatusEnum": [("draft", "草稿"), ("published", "已发布"), ("finished", "已结束")],
        "ExamSubmissionStatusEnum": [
            ("not_started", "未开始"), ("in_progress", "考试中"),
            ("submitted", "已提交"), ("timeout", "超时交卷"), ("absent", "缺考"),
        ],
    },
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://127.0.0.1:5273,http://localhost:5273,http://127.0.0.1:5173,http://localhost:5173",
)

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# ---------------------------------------------------------------------------
# 国际化
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# 静态与媒体
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# 课程扩展资源预置静态页根目录（思维导图/交互演示，只读资产）。
# 解析顺序：env RESOURCES_ROOT 覆盖 → 容器内 /app/resources（生产 bind mount）→
# 本地开发回退仓库 deploy/resources。入口页与资产均经签名 URL 门控后由 Django 读出，
# nginx 不再公开 /resources/，避免绕过发布状态直接访问。
RESOURCES_ROOT = os.getenv("RESOURCES_ROOT") or (
    BASE_DIR / "resources" if (BASE_DIR / "resources").is_dir() else BASE_DIR.parent / "deploy" / "resources"
)

# 虚拟实验静态页根目录（deploy/labs，只读资产）。
# 解析顺序同 RESOURCES_ROOT：env LABS_ROOT → 容器 /app/labs（生产 bind mount）→ 本地 deploy/labs。
# 页面与资产均经签名门控（labs/gate.py）由 Django 读出，nginx 不再公开 /labs/ 直链。
LABS_ROOT = os.getenv("LABS_ROOT") or (
    BASE_DIR / "labs" if (BASE_DIR / "labs").is_dir() else BASE_DIR.parent / "deploy" / "labs"
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# 大模型配置（供 apps.ai 读取）
# ---------------------------------------------------------------------------
# 旧版全局配置：AI_PROVIDER + AI_SETTINGS 按服务商提供一套凭证，
# 由工厂按能力（chat/embed/tts）派生（chat→chat_model，embed→embed_model，tts→tts_model）。
AI_PROVIDER = os.getenv("AI_PROVIDER", "mock")
AI_SETTINGS = {
    "deepseek": {
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "chat_model": os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat"),
        "embed_model": os.getenv("DEEPSEEK_EMBED_MODEL", ""),  # DeepSeek 无嵌入接口 -> 回退 mock
    },
    # 任意 OpenAI 兼容端点（本地 vLLM / 第三方）
    "openai": {
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("OPENAI_BASE_URL", ""),
        "chat_model": os.getenv("OPENAI_CHAT_MODEL", ""),
        "embed_model": os.getenv("OPENAI_EMBED_MODEL", ""),
    },
    "tongyi": {
        "api_key": os.getenv("TONGYI_API_KEY", ""),
        "base_url": os.getenv("TONGYI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "chat_model": os.getenv("TONGYI_CHAT_MODEL", "qwen-plus"),
        "embed_model": os.getenv("TONGYI_EMBED_MODEL", ""),
        "rerank_model": os.getenv("TONGYI_RERANK_MODEL", "gte-rerank-v2"),
        "tts_model": os.getenv("TONGYI_TTS_MODEL", ""),
    },
    # 系统内置本地模型：无需 API Key/接口地址，权重在系统内推理（见 apps/ai/local_models.py）
    "local": {
        "embed_model": os.getenv("LOCAL_EMBED_MODEL", "BAAI/bge-m3"),
        "rerank_model": os.getenv("LOCAL_RERANK_MODEL", "Qwen/Qwen3-Reranker-0.6B"),
    },
}
# 按能力的环境变量覆盖（可选）：AI_CHAT_PROVIDER / AI_CHAT_API_KEY / AI_CHAT_BASE_URL / AI_CHAT_MODEL
# 等，未设置的字段回退到 AI_PROVIDER + AI_SETTINGS 的对应项。
AI_CAPABILITY_ENV = {
    "chat": {
        "provider": os.getenv("AI_CHAT_PROVIDER", ""),
        "api_key": os.getenv("AI_CHAT_API_KEY", ""),
        "base_url": os.getenv("AI_CHAT_BASE_URL", ""),
        "model": os.getenv("AI_CHAT_MODEL", ""),
    },
    "embed": {
        "provider": os.getenv("AI_EMBED_PROVIDER", ""),
        "api_key": os.getenv("AI_EMBED_API_KEY", ""),
        "base_url": os.getenv("AI_EMBED_BASE_URL", ""),
        "model": os.getenv("AI_EMBED_MODEL", ""),
    },
    "rerank": {
        "provider": os.getenv("AI_RERANK_PROVIDER", ""),
        "api_key": os.getenv("AI_RERANK_API_KEY", ""),
        "base_url": os.getenv("AI_RERANK_BASE_URL", ""),
        "model": os.getenv("AI_RERANK_MODEL", ""),
    },
    "tts": {
        "provider": os.getenv("AI_TTS_PROVIDER", ""),
        "api_key": os.getenv("AI_TTS_API_KEY", ""),
        "base_url": os.getenv("AI_TTS_BASE_URL", ""),
        "model": os.getenv("AI_TTS_MODEL", ""),
    },
}


def _ai_env_int(name: str, default: int) -> int:
    """读取 AI 超时类环境变量：空值/非法值回退默认，避免启动崩溃。"""
    try:
        return int(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default


def _ai_env_float(name: str, default: float) -> float:
    """读取 AI 浮点类环境变量（阈值）：空值/非法值回退默认。"""
    try:
        return float(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default


# AI 调用超时（秒）与默认发音人：
# - 本地模型（vLLM / Ollama / localai 等）推理慢，讲稿分批与 TTS 合成超时必须
#   可调大，否则请求超时后讲稿整批落本地兜底文案、配音页记 audio_error；
# - AI_TTS_VOICE 是 DashScope 音色名（如 Cherry）；接本地 TTS 时改为服务端的
#   发音人/说话人 ID（本地服务自行解释该值）。
AI_SCRIPT_TIMEOUT = _ai_env_int("AI_SCRIPT_TIMEOUT", 45)
AI_TTS_TIMEOUT = _ai_env_int("AI_TTS_TIMEOUT", 120)
AI_TTS_VOICE = os.getenv("AI_TTS_VOICE") or "Cherry"
# AI 学情分析/章节总结超时（秒）：分析类调用输入长（约 6k tokens）、输出长，
# 且跑在后台线程不占请求周期，超时口径比讲稿宽松——本地模型推理慢时调大。
AI_ANALYTICS_TIMEOUT = _ai_env_int("AI_ANALYTICS_TIMEOUT", 120)
# 讲稿批内小块页数：每批（batch_size*2 页）再按此切成小块并发调用，每个小块
# 完成即落库（as_completed 增量保存）——前端轮询因此在请求进行中就能看到页数
# 推进，不会「卡住一批、响应后跳一大截」。调大减少调用次数但进度粒度变粗。
AI_SCRIPT_CHUNK_PAGES = _ai_env_int("AI_SCRIPT_CHUNK_PAGES", 3)

# AI 日配额全局默认（P5-B6）：0 = 不限（开发/测试默认）；生产由管理端在
# AI 配置页设置全局默认与用户级覆盖（AIQuotaPolicy），此处仅作兜底。
AI_DAILY_CHAT_QUOTA = _ai_env_int("AI_DAILY_CHAT_QUOTA", 0)

# AI 调用流水（埋点见 apps/ai/calllog.py，管理端统计追溯用）：
# - AI_CALL_LOG_RETENTION_DAYS：流水保留天数，清理命令 cleanup_ai_call_logs 按此删除；
# - AI_CALL_LOG_SAMPLE：高频场景采样率 {"场景名": 0~1}，未列出的场景全记；
#   失败调用不受采样影响（排障需要），本地模型/Mock 调用同样入账。
AI_CALL_LOG_RETENTION_DAYS = _ai_env_int("AI_CALL_LOG_RETENTION_DAYS", 90)
AI_CALL_LOG_SAMPLE = {}

# RAG 检索编排参数（向量召回 -> 重排序 -> 阈值过滤，见 apps/ai/services.py）：
# - AI_RERANK_RECALL：重排前的向量召回候选数。向量检索是纯余弦相似度，关键词面
#   重合但语义不相关的片段也会拿高分（实测「Java 程序设计考核方式」一问，噪声页
#   与目标页分数带重叠 0.54~0.76，top_k=5 硬取必混入噪声），故多召回再精排；
# - AI_RERANK_THRESHOLD：显式优先级最高的相关性阈值（None=按模型解析）。不同重排
#   模型的分数尺度差异极大，单一绝对值必然误杀——gte-rerank-v2 相关片段仅
#   0.09~0.9、无关 ~0.006；qwen3-rerank 相关 0.87+、无关 ~0.09。曾按 qwen3 量级
#   统一取 0.3，结果 gte-rerank 下「考核方式」目标页只有 0.288 被过滤、参考来源
#   全空（2026-10-15 实测复现），故改为按模型名子串匹配分模型阈值；
# - AI_RERANK_KEEP_RATIO：相对截断比例，保留分数 >= max(阈值, 最高分*比例) 的片段。
#   最高分与次高分存在 2 倍以上落差时，低分段多为同课程弱相关噪声（关键词面重合），
#   截断避免「乱引用」；置 0 退回纯阈值过滤。
#   未配置重排能力或调用失败时，检索编排自动回退纯向量 top_k（原有行为）。
AI_RERANK_RECALL = _ai_env_int("AI_RERANK_RECALL", 15)


def _ai_env_float_or_none(name: str):
    """读取浮点环境变量：未设置/空值返回 None（调用方按需回退），非法值也返回 None。"""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


AI_RERANK_THRESHOLD = _ai_env_float_or_none("AI_RERANK_THRESHOLD")
AI_RERANK_THRESHOLD_DEFAULT = 0.3
# 按重排模型名（provider.rerank_model）子串匹配，键越长越优先；未命中回退默认值。
AI_RERANK_MODEL_THRESHOLDS = {
    "gte-rerank": 0.05,  # DashScope gte-rerank-v2/v1：相关 0.09+、无关 ~0.006
    "qwen3-rerank": 0.3,  # DashScope qwen3-rerank：相关 0.87+、无关 ~0.09
    "qwen3-reranker": 0.3,  # 系统内置本地 Qwen3-Reranker-0.6B：与 qwen3-rerank 同量级
    "bge-reranker": 0.3,  # 本地/OpenAI 兼容 bge-rerank 系列（0~1 相关性）
}
AI_RERANK_KEEP_RATIO = _ai_env_float("AI_RERANK_KEEP_RATIO", 0.5)

# 问答上下文预算（token 维度，估算器 est_tokens 见 apps/ai/services.py）：
# - AI_CHAT_CONTEXT_WINDOW：chat 模型上下文窗口，所有预算的基准。历史预算 =
#   窗口 − RAG − 输出预留 − system/模板(≈600) − 安全余量(≈512)，窗口配小（如本地
#   8k 模型）时历史自动收紧，避免一追问就触发上下文超限降级；
# - AI_QA_RAG_TOKEN_BUDGET：检索资料注入预算。片段按相关度整取（在片段边界
#   截断，不再出现 6000 字符硬切砍断句子的情形），超预算的低排名片段整段舍弃；
# - AI_QA_OUTPUT_RESERVE：为模型回答预留的输出空间（max_tokens 量级）。
AI_CHAT_CONTEXT_WINDOW = _ai_env_int("AI_CHAT_CONTEXT_WINDOW", 32768)
AI_QA_RAG_TOKEN_BUDGET = _ai_env_int("AI_QA_RAG_TOKEN_BUDGET", 3000)
AI_QA_OUTPUT_RESERVE = _ai_env_int("AI_QA_OUTPUT_RESERVE", 2048)
# 课程级问答（未指定章节）的检索放宽：整体性问题（如「这门课主要讲哪些内容」）需要
# 跨章细节，但单纯加 top_k 不解决漏章——向量相关性向概述章集中，多取的仍是同一章
# 片段；且注入受 token 预算约束、预算不变加条数等于没加。故条数与预算同比例放宽，
# 跨章覆盖面由课程大纲注入保证（_gather_course_context 第 0 步），两者互补：
# 大纲保「每章都提到」，条数/预算保「每章有细节」。
AI_QA_COURSE_TOP_K = _ai_env_int("AI_QA_COURSE_TOP_K", 8)  # 课程级检索条数（章节内仍 5）
AI_QA_COURSE_BUDGET_RATIO = _ai_env_float("AI_QA_COURSE_BUDGET_RATIO", 1.5)  # 课程级预算倍率
# 讲稿入检索体系的回滚开关：置 1 后讲稿片段不参与向量检索（QA 侧退回
# 原文限量兜底）——检索结果分布异常时一键退回，无需回滚代码与数据。
AI_QA_DISABLE_SCRIPT_SOURCE = os.getenv("AI_QA_DISABLE_SCRIPT_SOURCE", "").lower() in ("1", "true", "yes", "on")

# 系统内置本地模型的权重目录：生产容器内 /app/data 是 bind mount（见 docker-compose），
# 故默认落点随之持久化、重建容器不丢；本地开发即 backend/data/models。
# 下载源为 ModelScope（国内可达）；首次使用惰性下载，也可 manage.py download_models
# 预热，或镜像构建时 PRELOAD_MODELS=true 预置（见 deploy/Dockerfile.backend）。
AI_MODELS_DIR = os.getenv("AI_MODELS_DIR", str(BASE_DIR / "data" / "models"))
