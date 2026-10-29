"""学期文本与 Term 的互转。

过渡期兼容：前端/导入模板在一段时间内仍会传 "2026秋" 这类自由文本，
这里统一负责解析成 Term，避免每个入口各写一份正则。
解析不出就返回 None —— 课程允许 term 为空，由管理端标「学期待归属」补齐，
绝不静默造一个猜出来的学期。
"""

from __future__ import annotations

import re

from .models import Term

SEASON_LABEL = {Term.Season.SPRING: "春", Term.Season.AUTUMN: "秋"}


def parse_term_text(text: str):
    """解析成 (year, season)；无法解析返回 None。"""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    raw = raw.translate(str.maketrans("０１２３４５６７８９－—～", "0123456789---"))
    year_match = re.search(r"(20\d{2})", raw)
    if not year_match:
        return None
    year = int(year_match.group(1))
    season = None
    if re.search(r"秋|下", raw):
        season = Term.Season.AUTUMN
    elif re.search(r"春|上", raw):
        season = Term.Season.SPRING
    if season is None:
        tail = re.search(r"[-_](\d)\s*$", raw)
        if tail:
            season = Term.Season.AUTUMN if tail.group(1) == "1" else Term.Season.SPRING
    if season is None:
        return None
    return year, season


def term_display_name(year: int, season: str) -> str:
    return f"{year}{SEASON_LABEL.get(season, '')}"


def ensure_term(text: str):
    """按文本取或建 Term。解析不出返回 None（调用方保留原文到 term_text）。"""
    parsed = parse_term_text(text)
    if not parsed:
        return None
    year, season = parsed
    term, _ = Term.objects.get_or_create(
        year=year,
        season=season,
        defaults={"name": term_display_name(year, season)},
    )
    return term


def current_term():
    return Term.objects.filter(is_current=True).first()
