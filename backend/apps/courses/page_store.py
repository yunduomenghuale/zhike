"""video.scripts 页级合并的唯一写入口（评审 C2）。

队列化后 worker 会持续几分钟反复回写 scripts，教师同时在界面上点「重新生成第 N 页」
或手改文本——两边各持一份快照、整数组回写的后写者必然吃掉先写者。收敛方案：

- **短事务 + 行锁**：select_for_update 锁住 TeachingVideo 行 → refresh → 页级
  合并 → save → 提交。锁只包 DB 读写（毫秒级），**事务内绝不调 AI**（C2 纪律）；
- **按来源区分覆盖**：worker 自动分批只填空页（DB 已有非空值的页永不覆盖，
  天然尊重教师手改）；教师显式「重生成/手改/重配音」传 overwrite_pages 强制覆盖；
- **不要跨批次持有 video 实例**：每次合并都经本模块重取（merge_pages 内部完成）。

覆盖矩阵（评审 C2）：

| 来源 | 目标页已有值 | 行为 |
|---|---|---|
| worker 自动分批（讲稿/配音） | 有 script / audio_url | 跳过 |
| worker 自动分批 | 空 | 写入 |
| 教师点「重新生成本页 / 手改 / 重配音」 | 有值 | 覆盖（overwrite_pages={page}） |

patch 中值为 None 表示删除该键（如清除 audio_error / 失效的 audio_url）；
overwrite_pages 中的页即使值为 None 也生效（教师显式操作优先于一切）。
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

# 受"已有非空值不覆盖"保护的键；其余键（audio_error 等）按补丁直接写入
_PROTECTED = ("script", "audio_url")


def _as_page_no(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def merge_pages(
    video_id: int,
    updates: dict[int, dict],
    *,
    overwrite_pages=(),
) -> list[dict]:
    """页级合并写 video.scripts，返回合并后的最新 scripts（DB 状态）。

    只做 DB 合并，绝不调 AI——调用方负责在事务外先拿到 AI 结果。

    updates: {page: {key: value, ...}}；value 为 None 表示删除该键。
    overwrite_pages: 强制覆盖的页集合（教师显式操作）。
    """
    from .models import TeachingVideo

    overwrite = {_as_page_no(p) for p in overwrite_pages}
    with transaction.atomic():
        video = TeachingVideo.objects.select_for_update().get(id=video_id)
        scripts = [dict(item) for item in (video.scripts or [])]
        index = {_as_page_no(item.get("page")): item for item in scripts}

        for page, patch in (updates or {}).items():
            pg = _as_page_no(page)
            item = index.get(pg)
            if item is None:
                item = {"page": pg}
                scripts.append(item)
                index[pg] = item
            for key, value in (patch or {}).items():
                if key in _PROTECTED and pg not in overwrite:
                    # 已有非空值 → 尊重教师手改，worker 不覆盖
                    if str(item.get(key) or "").strip():
                        continue
                if value is None:
                    item.pop(key, None)
                else:
                    item[key] = value

        scripts.sort(key=lambda item: _as_page_no(item.get("page")))
        video.scripts = scripts
        video.save(update_fields=["scripts", "updated_at"])
    return scripts


def count_filled(scripts: list[dict]) -> tuple[int, int]:
    """(非空 script 页数, 总页数)。"""
    items = scripts or []
    filled = sum(1 for item in items if str(item.get("script") or "").strip())
    return filled, len(items)


def count_audio(scripts: list[dict]) -> tuple[int, int]:
    """(有 audio_url 页数, 非空 script 页数)。"""
    items = scripts or []
    audio = sum(1 for item in items if str(item.get("audio_url") or "").strip())
    scripts_n = sum(1 for item in items if str(item.get("script") or "").strip())
    return audio, scripts_n


def touch_video_state(video_id: int, **fields) -> None:
    """video 行级字段（gen_status/is_published/audio_url 等）的独立短事务更新。

    与 scripts 数组合并分离开：状态字段不含教师并发编辑的页内容，
    用条件更新避免互相覆盖（updated_at 一并刷新）。
    """
    from .models import TeachingVideo

    fields.setdefault("updated_at", timezone.now())
    TeachingVideo.objects.filter(id=video_id).update(**fields)
