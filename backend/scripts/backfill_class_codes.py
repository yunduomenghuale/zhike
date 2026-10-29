"""补齐历史班级编码（P0 建列时 6 个班留空，导入匹配键缺失）。

背景（方案设计 §223）：`code` 是学生导入的匹配键，P0 只建了列、历史班留空；
"合成编码看起来像真的，会误导；导入前必须补"。本脚本把补齐动作本身变成
可审计、可重跑的：映射写在代码里、默认 dry-run、落库前逐条校验格式与唯一性。

用法：
    cd backend
    ./venv/Scripts/python.exe scripts/backfill_class_codes.py            # 预演，不写库
    ./venv/Scripts/python.exe scripts/backfill_class_codes.py --apply    # 落库

编码规则：`<专业缩写>-<入学年>-<序号/字母>`，与批量导入模板示例（CS-2401）同风格，
满足导入侧的 `^[A-Z0-9-]{3,32}$`。**演示环境占位值**：上线前应由管理员按学籍系统
重新核定（见 docs/阶段计划与进度.md「历史班级编码补齐」一节）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from apps.classroom.models import ClassRoom  # noqa: E402

# 班级 id -> 编码。只列「当前 code 为空」的班；已编码的班一律不碰。
# 注：id 5「P1b冒烟-无数据班」原为 P1b 冒烟遗留空班，2026-10-29 经零关联校验后
# 已删除（见 docs/阶段计划与进度.md §5-A），故不再出现在本映射中。
CODE_MAP: dict[int, str] = {
    1: "NET-2026-01",   # 网络2026届-1班
    2: "SJJG-2026-01",  # 数据结构B班
    3: "JSJ-2026-A",    # 计科2026届-A班
    4: "JSJ-2026-B",    # 计科2026届-B班
    6: "SJJG-XQ-01",    # 数据结构兴趣班
}

CODE_PATTERN = r"^[A-Z0-9-]{3,32}$"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写库（默认只预演）")
    args = parser.parse_args()

    import re

    pattern = re.compile(CODE_PATTERN)
    empty = list(
        ClassRoom.objects.filter(code__isnull=True).order_by("id")
        | ClassRoom.objects.filter(code="").order_by("id")
    )
    taken = {
        c.strip().upper()
        for c in ClassRoom.objects.exclude(code__isnull=True).exclude(code="").values_list("code", flat=True)
    }

    print(f"待补齐班级 {len(empty)} 个，系统已有编码 {len(taken)} 个\n")
    problems: list[str] = []
    proposed: list[tuple[int, str, str]] = []

    for room in empty:
        code = CODE_MAP.get(room.id)
        if not code:
            problems.append(f"班级 {room.id}「{room.name}」没有映射，请先在 CODE_MAP 里补一条")
            continue
        code = code.strip().upper()
        if not pattern.match(code):
            problems.append(f"班级 {room.id}「{room.name}」编码 {code} 不符合 {CODE_PATTERN}")
        if code in taken:
            problems.append(f"班级 {room.id}「{room.name}」编码 {code} 与已有编码冲突")
        proposed.append((room.id, room.name, code))
        taken.add(code)

    for room_id, name, code in proposed:
        print(f"  {room_id:>3}  {name:<16} -> {code}")
    if problems:
        print("\n校验未通过：")
        for item in problems:
            print(f"  !! {item}")
        return 1

    if not args.apply:
        print("\n（dry-run，未写库；加 --apply 落库）")
        return 0

    written = 0
    for room_id, _name, code in proposed:
        room = ClassRoom.objects.get(id=room_id)
        room.code = code
        # 走 save() 而不是 update()：归一逻辑在模型层，不依赖调用方
        room.save(update_fields=["code", "updated_at"])
        written += 1

    # 落库后复核：不允许再有空编码，且大小写归一后仍唯一
    still_empty = (
        ClassRoom.objects.filter(code__isnull=True) | ClassRoom.objects.filter(code="")
    ).count()
    normalized = [
        str(c or "").strip().upper()
        for c in ClassRoom.objects.values_list("code", flat=True)
        if c
    ]
    duplicates = sorted({c for c in normalized if normalized.count(c) > 1})
    print(f"\n已写入 {written} 个编码；剩余空编码 {still_empty} 个；重复编码 {duplicates or '无'}")
    if still_empty or duplicates:
        return 1
    print("补齐完成。建议接着跑学生导入验证匹配（X-32）：小写编码应命中已有班、不新建。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
