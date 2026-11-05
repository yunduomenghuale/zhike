#!/usr/bin/env python
"""Stage 3 端到端后置核对（本地 5273 / 8092 通用）。

在真实浏览器完成上报之后，用真实账号 HTTP + ORM 核对：
入库字段与 S1/S5 语义、票据一次性、章节学情 C17、班级导出 C18、报告双分支。

用法：./backend/venv/Scripts/python.exe test/e2e/stage3-grade-verify.py [setupJson]
"""
import hashlib
import io
import json
import os
from pathlib import Path
import sys

import requests

SETUP_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else os.getenv("SETUP", "D:/tmp/stage3-setup.json"))
setup = json.loads(SETUP_PATH.read_text(encoding="utf-8"))
BASE = os.getenv("BASE", setup["base"])
BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
django.setup()

from django.conf import settings  # noqa: E402
from apps.analytics.services import build_chapter_profile  # noqa: E402
from apps.courses.models import Catalog  # noqa: E402
from apps.labs.models import LabAttemptToken, LabReport, LabSubmission  # noqa: E402
from apps.users.models import User  # noqa: E402

S = requests.Session()
S.trust_env = False
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + " | " + name + (" | " + str(detail)[:260] if detail != "" else ""))


def call(method, path, token, **kwargs):
    return S.request(method, BASE + path, headers={"Authorization": "Bearer " + token},
                     timeout=60, **kwargs)


def main():
    sid = setup["submission_id"]
    t_token, s_token = setup["teacher_token"], setup["student_token"]
    sub = LabSubmission.objects.select_related("lab", "student", "schedule").get(pk=sid)
    ticket = LabAttemptToken.objects.filter(submission=sub).first()

    print("===== 一、入库记录（真实库 zk） =====")
    print(json.dumps({
        "submission_id": sub.id, "lab_id": sub.lab_id, "lab_title": sub.lab.title,
        "student": sub.student.username, "status": sub.status,
        "total_score": str(sub.total_score), "grading_source": sub.grading_source,
        "elapsed_seconds": sub.elapsed_seconds,
        "started_at": sub.started_at.isoformat() if sub.started_at else None,
        "submitted_at": sub.submitted_at.isoformat() if sub.submitted_at else None,
        "graded_at": sub.graded_at.isoformat() if sub.graded_at else None,
        "abnormal": sub.abnormal, "passed_steps": sub.passed_steps, "total_steps": sub.total_steps,
        "score_breakdown": sub.score_breakdown,
        "grade_raw": sub.grade_raw,
        "grade_raw_digest": sub.grade_raw_digest,
        "ticket_consumed": ticket.consumed if ticket else None,
    }, ensure_ascii=False, indent=2))

    delta = int((sub.submitted_at - sub.started_at).total_seconds())
    check("S1 落库用时 == submitted_at - started_at", sub.elapsed_seconds == delta,
          f"{sub.elapsed_seconds} vs {delta}")
    check("S1 客户端谎报用时只进 grade_raw", sub.elapsed_seconds != sub.grade_raw["request"].get("elapsed_seconds", -1),
          f"client={sub.grade_raw['request'].get('elapsed_seconds')}")
    check("C23 submitted_at 由服务端生成", sub.submitted_at.year > 2020 and sub.graded_at == sub.submitted_at)
    check("成绩来源 external + 总分 100", sub.grading_source == "external" and float(sub.total_score) == 100.0)
    check("步骤指标保持 0（C17 统计分支依据）", sub.passed_steps == 0 and sub.total_steps == 0)
    check("score_breakdown 只有 total/source/elapsed",
          set(sub.score_breakdown) == {"total", "source", "elapsed_seconds"}
          and sub.score_breakdown["source"] == "external", sub.score_breakdown)
    digest = hashlib.sha256(json.dumps(sub.grade_raw, sort_keys=True, ensure_ascii=False,
                                       default=str).encode("utf-8")).hexdigest()
    check("grade_raw_digest 可复核", sub.grade_raw_digest == digest)
    check("S2 票据已消费且不可重放", ticket is not None and ticket.consumed is True)
    check("S5 满分极短用时 abnormal=True", sub.abnormal is True,
          sub.grade_raw.get("server", {}).get("abnormal_reason", ""))

    print("===== 二、C8 grade_raw 角色裁剪（真实 HTTP） =====")
    tea = call("GET", f"/api/lab-submissions/{sid}/", t_token).json()
    stu = call("GET", f"/api/lab-submissions/{sid}/", s_token).json()
    check("教师可见原文", tea["data"]["grade_raw"]["request"]["total_score"] == 100)
    check("学生端 grade_raw 为 None", stu["data"]["grade_raw"] is None)

    print("===== 三、C17 章节学情（真实数据调 build_chapter_profile） =====")
    catalog = Catalog.objects.get(pk=setup["catalog_id"])
    profile = build_chapter_profile(sub.student, catalog, for_student=True)
    entry = next((x for x in profile["labs"] if x["title"] == setup["lab_title"]), None)
    print(json.dumps(entry, ensure_ascii=False))
    check("章节画像含该自定义实验", entry is not None)
    if entry:
        check("章节画像步骤指标为 None（不被 0 拉低）",
              entry["passed_steps"] is None and entry["total_steps"] is None)
        check("章节画像标注「不适用」并保留总分/用时",
              "不适用" in (entry["step_metrics"] or "") and entry["total_score"] == 100.0
              and entry["elapsed_seconds"] == sub.elapsed_seconds)

    print("===== 四、C18 班级导出（真实 HTTP xlsx） =====")
    r = call("GET", f"/api/analytics/class/{setup['classroom_id']}/export/",
             t_token, params={"course": setup["course_id"], "sheets": "lab"})
    check("导出接口 200", r.status_code == 200, r.status_code)
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["实验明细"]
    headers = [ws.cell(row=2, column=c).value for c in range(1, ws.max_column + 1)]
    row = None
    for rr in range(3, ws.max_row + 1):
        if ws.cell(row=rr, column=3).value == setup["lab_title"]:
            row = {headers[c - 1]: ws.cell(row=rr, column=c).value for c in range(1, ws.max_column + 1)}
            break
    print(json.dumps(row, ensure_ascii=False))
    check("Sheet4 含该实验行", row is not None)
    if row:
        check("Sheet4 总分 100 + 用时非空", float(row["总分"]) == 100.0 and row["用时(分钟)"] is not None)
        for col in ("基础分", "操作准确性", "完成效率", "完成度", "通过步骤", "总步骤"):
            check(f"Sheet4 {col} = 不适用", row[col] == "不适用", row[col])
    out_xlsx = Path("D:/tmp/stage3-export.xlsx")
    out_xlsx.write_bytes(r.content)
    print("xlsx -> " + str(out_xlsx))

    print("===== 五、报告双分支（真实生成并打开 docx/pdf） =====")
    call("POST", f"/api/lab-submissions/{sid}/conclusion/", s_token,
         json={"conclusion": "完成自定义实验，验证了总分上报与服务端用时计算。"})
    rr = call("POST", f"/api/lab-submissions/{sid}/generate-report/", s_token)
    check("报告生成接口 200", rr.status_code == 200 and rr.json().get("code") == 0, rr.text[:200])
    report = LabReport.objects.filter(submission=sub).first()
    check("LabReport 落库", report is not None)
    if report:
        from docx import Document

        doc = Document(report.file_docx.path)
        text = "\n".join(p.text for p in doc.paragraphs)
        check("DOCX 评分明细 = 总分 + 用时，不含四项基准分",
              "总分：100" in text and "用时：" in text and "基础分" not in text, text[-260:])
        check("DOCX 步骤清单标注「不适用」", "不适用" in text)
        import pypdf

        pdf = pypdf.PdfReader(report.file_pdf.path)
        pdf_text = "".join(p.extract_text() or "" for p in pdf.pages)
        check("PDF 同样只有总分、无基准分", "总分" in pdf_text and "基础分" not in pdf_text, pdf_text[-200:])

    bad = [n for n, ok in RESULTS if not ok]
    print(f"\n===== 汇总 =====\n总计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(bad)} 项，失败 {len(bad)} 项")
    if bad:
        for n in bad:
            print("失败: " + n)
        sys.exit(1)
    print("ALL_PASS")


if __name__ == "__main__":
    main()
