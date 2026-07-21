from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class AIConfiguration(BaseModel):
    """平台级大模型配置。密钥使用项目 SECRET_KEY 派生密钥加密保存。"""

    class Provider(models.TextChoices):
        MOCK = "mock", "模拟模式"
        DEEPSEEK = "deepseek", "DeepSeek"
        TONGYI = "tongyi", "通义千问"
        ZHIPU = "zhipu", "智谱 GLM"
        OPENAI = "openai", "OpenAI 兼容接口"

    class TestStatus(models.TextChoices):
        UNTESTED = "untested", "未测试"
        SUCCESS = "success", "连接成功"
        FAILED = "failed", "连接失败"

    provider = models.CharField("服务商", max_length=20, choices=Provider.choices, default=Provider.MOCK)
    enabled = models.BooleanField("启用配置", default=False)
    base_url = models.URLField("接口地址", max_length=500, blank=True)
    chat_model = models.CharField("对话模型", max_length=120, blank=True)
    embed_model = models.CharField("向量模型", max_length=120, blank=True)
    tts_model = models.CharField("语音模型", max_length=120, blank=True)
    api_key_ciphertext = models.TextField("加密 API Key", blank=True)
    last_test_status = models.CharField(
        "测试状态", max_length=16, choices=TestStatus.choices, default=TestStatus.UNTESTED
    )
    last_test_message = models.CharField("测试结果", max_length=500, blank=True)
    last_tested_at = models.DateTimeField("测试时间", null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_configuration_updates",
        verbose_name="最后修改人",
    )

    class Meta:
        verbose_name = "大模型配置"
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
        return f"{self.get_provider_display()} ({'启用' if self.enabled else '停用'})"
