from django.db import models


class BaseModel(models.Model):
    """所有业务模型的抽象基类，统一携带创建/更新时间。

    数据层与具体数据库无关，起步用 SQLite，可平滑迁移到 PostgreSQL。
    """

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-id"]
