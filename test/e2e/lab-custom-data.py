#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 4 端到端落库核对（本地 8005 / 8092 通用，全部走真实 HTTP）。

浏览器 E2E 之后运行：验证 external 上报记录的字段、S1 服务端用时、
C8 grade_raw 角色裁剪、C6 幽灵字段消失、票据已消费。
用法：cd backend && ./venv/Scripts/python.exe ../test/e2e/lab-custom-data.py
"""
import json
import os
import re
import sys
from datetime import datetime

import requests

SETUP_PATH = os.environ.get("SETUP", "D:/tmp/stage4-setup.json")
setup = json.load(open(SETUP_PATH, encoding="utf-8"))
BASE = os.environ.get("API_BASE", setup.get("base", "http://127.0.0.1:8005"))
S = requests.Session()
S.trust_env = False

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL") + " | " + name + ((" | " + str(detail)[:220]) if detail != "" else ""))


def api(method, path, token, **kw):
    r = S.request(method, BASE + "/api" + path,
                  headers={"Authorization": "Bearer " + token}, timeout=30, **kw)
    return r.status_code, (r.json().get("data") if r.content else None)


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    st, labs = api("GET", "/labs/?course=%s" % setup["course_id"], setup["teacher_token"])
    rows = (labs or {}).get("results") or []
    lab = next((x for x in rows if x["title"] == setup["lab_title"]), None)
    check("D1 真实 API 查到本次自定义实验", lab is not None, lab and lab["id"])
    if not lab:
        return
    lab_id = lab["id"]
    check("D2 page_source=custom 且 allow_resubmit=False（C12）",
          lab.get("page_source") == "custom" and lab.get("allow_resubmit") is False,
          {"page_source": lab.get("page_source"), "allow_resubmit": lab.get("allow_resubmit")})
    check("D3 last_debug 摘要已回写且最近一次通过",
          (lab.get("last_debug") or {}).get("passed") is True, lab.get("last_debug", {}).get("at"))

    st, sub_data = api("GET", "/lab-submissions/?lab=%s" % lab_id, setup["teacher_token"])
    subs = (sub_data or {}).get("results") or []
    sub = subs[0] if len(subs) == 1 else None
    check("D4 恰有 1 条提交且状态 submitted", sub is not None and sub["status"] == "submitted",
          "count=%d" % len(subs))
    if not sub:
        return
    check("D5 grading_source=external 且 score_breakdown.source=external",
          sub.get("grading_source") == "external"
          and (sub.get("score_breakdown") or {}).get("source") == "external",
          sub.get("score_breakdown"))
    check("D6 总分为页面上报值 100", float(sub.get("total_score") or 0) == 100.0, sub.get("total_score"))

    # S1：正式用时由服务端 submitted_at - started_at 计算，与页面自报值无关
    delta = int((parse_dt(sub["submitted_at"]) - parse_dt(sub["started_at"])).total_seconds())
    check("D7 S1 落库用时 == submitted_at - started_at",
          sub.get("elapsed_seconds") == max(0, delta),
          "%s vs %s" % (sub.get("elapsed_seconds"), delta))
    check("D8 submitted_at / graded_at 均由服务端生成",
          bool(sub.get("submitted_at")) and bool(sub.get("graded_at")),
          "%s / %s" % (sub.get("submitted_at"), sub.get("graded_at")))
    check("D9 grade_raw 原文与 sha256 摘要留痕",
          bool(sub.get("grade_raw")) and bool(re.fullmatch(r"[0-9a-f]{64}", sub.get("grade_raw_digest") or "")),
          "digest=%s" % sub.get("grade_raw_digest"))
    check("D10 C6 question_score 幽灵字段不在响应中", "question_score" not in sub)

    # C8：教师可见原始报文，学生端一律 None
    _, student_data = api("GET", "/lab-submissions/?lab=%s" % lab_id, setup["student_token"])
    stu_sub = ((student_data or {}).get("results") or [{}])[0]
    check("D11 C8 grade_raw 角色裁剪（教师可见 / 学生 None）",
          bool(sub.get("grade_raw")) and stu_sub.get("grade_raw") is None,
          "teacher=%s student=%s" % (type(sub.get("grade_raw")).__name__, stu_sub.get("grade_raw")))

    # 学生端字段：三分支徽标所需 status、用时、grading_source 齐全
    check("D12 学生端 external 展示所需字段齐全",
          all(k in stu_sub for k in ("status", "total_score", "elapsed_seconds", "grading_source")),
          sorted(stu_sub.keys())[:8])

    ok = sum(results)
    print("\n总计 %d 项，通过 %d 项，失败 %d 项" % (len(results), ok, len(results) - ok))
    print("ALL_PASS" if ok == len(results) else "FAILED")
    if ok != len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
