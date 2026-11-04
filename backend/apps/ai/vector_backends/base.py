"""向量检索后端的公共契约。

为什么抽这一层：检索的**过滤语义**是本系统最容易被改坏的部分——章节候选池、
学生可见性（按来源分别判定）、当前启用课件、讲稿回滚开关，任何一项在换后端时
丢掉都会变成「学生查到不该看的内容」或「章节提问答不上来」。因此过滤条件先
收敛成一个不可变的 ``ChunkFilter``（唯一事实源），两个后端各自把它翻译成自己
的查询语言；新增后端只需实现 ``VectorBackend`` 三个方法。

JSON 后端 = 现状（MySQL ``KnowledgeChunk.embedding`` 列 + 内存暴力余弦），
Qdrant 后端 = 同一份向量的外置索引。两者读的是同一批向量，因此结果可比、
可回滚、可零重算切换。
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（维度不符/空向量返回 0.0——静默沉底而非报错）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@dataclass(frozen=True)
class ChunkFilter:
    """一次检索的过滤语义（两套后端必须等价实现）。

    字段与 ``KnowledgeChunk`` 上的检索条件一一对应：

    - course_id：课程边界（永不为空）；
    - catalog_id：章节候选池。非空时 = 挂该章节的片段 + 未挂章节的通用资料
      片段（catalog 为空的 material，如教材电子版/考纲，2026-10-21 起纳入）；
    - student_access：学生视角可见性，按来源分别判定（资料 qa_open + 班级可见；
      课件当前版本 + 章节已发布；讲稿视频已发布 + 章节已发布）；
    - classroom_ids：学生在读班级集合（仅影响资料片段的定向可见性）；
    - include_script：讲稿是否参与检索（``AI_QA_DISABLE_SCRIPT_SOURCE``
      一键退回开关）。
    """

    course_id: int
    catalog_id: int | None = None
    student_access: bool = False
    classroom_ids: tuple[int, ...] = ()
    include_script: bool = True

    @classmethod
    def build(
        cls,
        course_id: int,
        *,
        catalog_id=None,
        student_access: bool = False,
        classroom_ids=None,
    ) -> "ChunkFilter":
        """从检索入参 + settings 组装过滤条件（调用方统一走这里，不手搓）。"""
        from django.conf import settings

        ids: list[int] = []
        for raw in classroom_ids or []:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value:
                ids.append(value)
        return cls(
            course_id=int(course_id),
            catalog_id=int(catalog_id) if catalog_id else None,
            student_access=bool(student_access),
            classroom_ids=tuple(sorted(set(ids))),
            include_script=not bool(getattr(settings, "AI_QA_DISABLE_SCRIPT_SOURCE", False)),
        )

    def describe(self) -> dict:
        """可读描述（打点/比对报告用）。"""
        return {
            "course_id": self.course_id,
            "catalog_id": self.catalog_id,
            "student_access": self.student_access,
            "classroom_ids": list(self.classroom_ids),
            "include_script": self.include_script,
        }


class VectorBackend:
    """向量后端接口：检索 + 写入 + 删除 + 健康探查。

    返回值统一为 ``[(KnowledgeChunk, score), ...]``（按相似度降序）——调用方
    （``services._search_relevant_chunks``）需要 chunk 的 content 与来源关系
    做重排、引用展示，所以后端必须回吐真实模型对象，不能只给 id。
    """

    name = ""

    # ---------------------------------------------------------------- 读
    def search(self, flt: ChunkFilter, query_vec: list[float], top_k: int = 5):
        raise NotImplementedError

    # ---------------------------------------------------------------- 写
    def upsert(self, chunks) -> int:
        """把片段写入后端（幂等，按 chunk_id）。返回写入条数。"""
        raise NotImplementedError

    def delete(self, ids) -> None:
        """按 chunk_id 删除（不存在的 id 静默忽略）。"""
        raise NotImplementedError

    # ---------------------------------------------------------------- 运维
    def ensure_ready(self) -> None:
        """确保后端可用（建集合等）；不可用时抛异常。"""

    def count(self) -> int | None:
        return None

    def health(self) -> tuple[bool, str]:
        return True, ""
