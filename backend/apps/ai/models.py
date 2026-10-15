from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class AICapabilityConfig(BaseModel):
    """按能力（对话 / 向量 / 重排序 / 语音）的平台级大模型配置。

    每项能力独立选择服务商、接口与凭证，可混搭（如对话用 DeepSeek、
    向量与语音用通义千问）。密钥使用项目 SECRET_KEY 派生密钥加密保存。
    """

    class Capability(models.TextChoices):
        CHAT = "chat", "对话生成"
        EMBED = "embed", "向量化"
        RERANK = "rerank", "重排序"
        TTS = "tts", "语音合成"

    class Provider(models.TextChoices):
        DEEPSEEK = "deepseek", "DeepSeek"
        TONGYI = "tongyi", "通义千问"
        OPENAI = "openai", "本地模型服务"
        LOCAL = "local", "系统内置模型"
        MOCK = "mock", "模拟模式"

    # 各能力可选的服务商白名单：
    # - DeepSeek 无 embedding / TTS 接口；
    # - 模拟模式（Mock）不产生真实向量/音频，且 64 维假向量会污染真实向量空间，
    #   向量化与语音合成仅开放通义千问与本地模型服务（OpenAI 兼容）；
    # - 系统内置模型（local）：向量化内置 BGE-M3、重排序内置 Qwen3-Reranker-0.6B，
    #   权重系统内推理（apps/ai/local_models.py），无需 Key/接口地址；
    #   对话与语音暂无内置实现，不开放；
    # - 重排序开放通义千问（DashScope 原生 rerank 端点）与系统内置模型
    #   （OpenAI 兼容生态无统一 /rerank 规范，compatible-mode 实测 404；
    #   Mock 无法对真实向量候选打分，开放无意义）；
    # - 对话（chat）保留模拟模式，便于无 Key 环境下演示流程。
    # 序列化层与管理端测试接口均按此校验，防止 API 层绕过前端下拉限制。
    CAPABILITY_PROVIDERS = {
        "chat": ("deepseek", "tongyi", "openai", "mock"),
        "embed": ("tongyi", "openai", "local"),
        "rerank": ("tongyi", "local"),
        "tts": ("tongyi", "openai"),
    }

    class TestStatus(models.TextChoices):
        UNTESTED = "untested", "未测试"
        SUCCESS = "success", "连接成功"
        FAILED = "failed", "连接失败"

    capability = models.CharField(
        "能力", max_length=16, choices=Capability.choices, unique=True
    )
    provider = models.CharField(
        "服务商", max_length=20, choices=Provider.choices, default=Provider.MOCK
    )
    enabled = models.BooleanField("启用配置", default=False)
    base_url = models.URLField("接口地址", max_length=500, blank=True)
    model_name = models.CharField("模型名称", max_length=120, blank=True)
    timeout = models.PositiveIntegerField(
        "超时(秒)", null=True, blank=True,
        help_text="单次请求超时；留空按环境变量/默认值。本地模型推理慢建议调大(讲稿120+/语音180+)",
    )
    voice = models.CharField(
        "发音人", max_length=64, blank=True, default="",
        help_text="TTS 发音人/说话人ID；留空按 AI_TTS_VOICE 或 Cherry。仅语音合成有效",
    )
    api_key_ciphertext = models.TextField("加密 API Key", blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_capability_config_updates",
        verbose_name="最后修改人",
    )

    class Meta:
        verbose_name = "大模型能力配置"
        verbose_name_plural = verbose_name

    def set_api_key(self, value: str):
        from .secrets import encrypt_secret

        self.api_key_ciphertext = encrypt_secret(value) if value else ""

    def get_api_key(self) -> str:
        from .secrets import decrypt_secret

        return decrypt_secret(self.api_key_ciphertext) if self.api_key_ciphertext else ""

    @property
    def api_key_configured(self):
        return bool(self.api_key_ciphertext)

    def __str__(self):
        return f"{self.get_capability_display()} · {self.get_provider_display()} ({'启用' if self.enabled else '停用'})"


class AITestRecord(BaseModel):
    """能力连接测试记录（每项能力保留最新一次）。

    仅作测试历史展示，不参与 runtime 解析——环境变量模式下也能记录测试结果，
    且不会因为写入记录而改变实际生效的配置。
    """

    capability = models.CharField(
        "能力", max_length=16, choices=AICapabilityConfig.Capability.choices, unique=True
    )
    provider = models.CharField("测试时服务商", max_length=20, blank=True)
    status = models.CharField(
        "测试状态",
        max_length=16,
        choices=AICapabilityConfig.TestStatus.choices,
        default=AICapabilityConfig.TestStatus.UNTESTED,
    )
    message = models.CharField("测试结果", max_length=500, blank=True)
    tested_at = models.DateTimeField("测试时间", null=True, blank=True)
    tested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_test_records",
        verbose_name="测试人",
    )

    class Meta:
        verbose_name = "连接测试记录"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.capability} · {self.get_status_display()}"
