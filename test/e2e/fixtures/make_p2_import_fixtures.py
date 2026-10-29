"""生成 P2 导入 E2E 用的 xlsx 夹具（表头与系统模板一致，含 * 标记）。

用法：
    python make_p2_import_fixtures.py <TAG> <输出目录>

产出：
    classes.xlsx        24 正常 + 2 重复编码 + 1 缺名称（一次导入让班级总数跨过单页 20，顺带验证分页）
    teachers.xlsx       2 位教师
    students_auto.xlsx  3 名学生，班级编码是系统里没有的（待建班）
"""
import sys
from pathlib import Path

from openpyxl import Workbook

CLASS_HEADERS = ["班级编码 *", "班级名称 *", "入学年 *", "学制 *", "状态"]
TEACHER_HEADERS = ["工号", "姓名"]
STUDENT_HEADERS = ["学号", "姓名", "班级编码", "班级名称", "入学年"]


def write(path: Path, headers: list, rows: list) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


def main() -> int:
    tag = sys.argv[1]
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)

    classes = [[f"{tag}-{i:02d}", f"E2E计算机{2400 + i}班", 2026, 3, ""] for i in range(1, 25)]
    classes.append([f"{tag}-01", "重复编码班", 2026, 3, ""])
    classes.append([f"{tag}-02".lower(), "大小写重复班", 2026, 3, ""])
    classes.append([f"{tag}-99", "", 2026, 3, ""])
    write(out / "classes.xlsx", CLASS_HEADERS, classes)

    teachers = [[f"T{tag}1", "E2E教师甲"], [f"T{tag}2", "E2E教师乙"]]
    write(out / "teachers.xlsx", TEACHER_HEADERS, teachers)

    students = [[f"{tag}01", "界面甲", f"{tag}-51", "E2E新建班", 2026],
                [f"{tag}02", "界面乙", f"{tag}-51", "E2E新建班", 2026],
                [f"{tag}03", "界面丙", f"{tag}-51", "E2E新建班", 2026]]
    write(out / "students_auto.xlsx", STUDENT_HEADERS, students)

    print(f"fixtures ready in {out} (tag={tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
