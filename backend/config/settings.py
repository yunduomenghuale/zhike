"""Django settings for 智能课程教学平台 (config project)."""
from datetime import timedelta
from django.core.exceptions import ImproperlyConfigured
from pathlib import Path

from dotenv import load_dotenv
import os

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
# 数据库：起步 SQLite；DATABASE_URL 指向 postgres 时切换
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite")
if DATABASE_URL.startswith("postgres"):
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
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

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

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.ai.authentication.AiCallJWTAuthentication",
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

# 系统内置本地模型的权重目录：生产容器内 /app/data 是 bind mount（见 docker-compose），
# 故默认落点随之持久化、重建容器不丢；本地开发即 backend/data/models。
# 下载源为 ModelScope（国内可达）；首次使用惰性下载，也可 manage.py download_models
# 预热，或镜像构建时 PRELOAD_MODELS=true 预置（见 deploy/Dockerfile.backend）。
AI_MODELS_DIR = os.getenv("AI_MODELS_DIR", str(BASE_DIR / "data" / "models"))
