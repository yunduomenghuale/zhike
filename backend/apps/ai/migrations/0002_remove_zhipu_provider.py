from django.db import migrations, models


def _reset_zhipu_to_mock(apps, schema_editor):
    """删除智谱 Provider 前的数据兜底：历史 zhipu 配置行重置为模拟模式。"""
    AIConfiguration = apps.get_model("ai", "AIConfiguration")
    AIConfiguration.objects.filter(provider="zhipu").update(
        provider="mock",
        enabled=False,
        base_url="",
        chat_model="",
        embed_model="",
        tts_model="",
    )


class Migration(migrations.Migration):

    dependencies = [("ai", "0001_initial")]

    operations = [
        migrations.RunPython(_reset_zhipu_to_mock, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="aiconfiguration",
            name="provider",
            field=models.CharField(
                choices=[
                    ("mock", "模拟模式"),
                    ("deepseek", "DeepSeek"),
                    ("tongyi", "通义千问"),
                    ("openai", "OpenAI 兼容接口"),
                ],
                default="mock",
                max_length=20,
                verbose_name="服务商",
            ),
        ),
    ]
