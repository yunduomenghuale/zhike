#!/usr/bin/env python
"""Stage 3 端到端数据准备（本地 5273 / 8092 通用）。

真实账号登录后用真实 HTTP 建自定义实验、上传单 HTML、发布、排课、学生 start，
并跑在线调试 dry-run 的三种模拟报文。产物写入 --out（默认 D:/tmp/stage3-setup.json），
供 stage3-grade-verify.js / stage3-grade-verify.py 消费。

用法：
  python test/e2e/stage3-grade-setup.py
  BASE=http://192.168.3.145:8092 TEACHER=test_admin STUDENT=B2204011 \
    COURSE_ID=1 CATALOG_ID=1 CLASSROOM_ID=1 python test/e2e/stage3-grade-setup.py
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path

import requests

BASE = os.getenv("BASE", "http://127.0.0.1:5273")
TEACHER = (os.getenv("TEACHER", "t101"), os.getenv("TEACHER_PASS", "Test123456!"))
STUDENT = (os.getenv("STUDENT", "20249999"), os.getenv("STUDENT_PASS", "Test123456!"))
COURSE_ID = int(os.getenv("COURSE_ID", "5"))
CATALOG_ID = int(os.getenv("CATALOG_ID", "5"))
CLASSROOM_ID = int(os.getenv("CLASSROOM_ID", "1"))
PAGE = Path(__file__).with_name("fixtures").joinpath("stage3-page.html")

S = requests.Session()
S.trust_env = False  # 不走系统代理，等价 curl --noproxy '*'


def call(method, path, token=None, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = "Bearer " + token
    r = S.request(method, BASE + path, headers=headers, timeout=30, **kwargs)
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:300]}
    return r.status_code, body, r


def need(cond, msg, body=None):
    if not cond:
        raise RuntimeError(f"{msg} | {json.dumps(body, ensure_ascii=False)[:500]}")


def login(username, password):
    code, body, _ = call("POST", "/api/auth/login/", json={"username": username, "password": password})
    need(code == 200 and body.get("code") == 0, f"登录失败 {username}", body)
    return body["data"]["token"]["access"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.getenv("OUT", "D:/tmp/stage3-setup.json"))
    args = ap.parse_args()

    t_token = login(*TEACHER)
    s_token = login(*STUDENT)
    print(f"login OK: teacher={TEACHER[0]} student={STUDENT[0]}")
    # 唯一名称：重复跑 setup 时浏览器按名称定位行/卡片，绝不能误命中上一次的草稿
    lab_title = "Stage3 成绩上报端到端实验-" + datetime.now().strftime("%Y%m%d%H%M%S")

    code, body, _ = call("POST", "/api/labs/", t_token, json={
        "page_source": "custom", "course": COURSE_ID, "catalog": CATALOG_ID,
        "title": lab_title, "total_score": "100", "pass_score": "60",
    })
    need(code in (200, 201) and body.get("code") == 0, "创建自定义实验失败", body)
    lab_id = body["data"]["id"]
    print(f"create lab OK: id={lab_id}")

    html = PAGE.read_bytes()
    code, body, _ = call("POST", f"/api/labs/{lab_id}/page/", t_token,
                         files={"file": ("stage3-page.html", html, "text/html")})
    need(code in (200, 201) and body.get("code") == 0, "上传页面失败", body)
    need(body["data"].get("hits") == [], "S8 静态扫描不应命中", body)
    print(f"upload page OK: {len(html)} bytes, scan hits=0")

    # 在线调试 dry-run：满分 / 零分 / 部分分 + 一条越界失败报文，均不得产生真实提交
    debug = []
    for score in ("100", "0", "86.5", "101"):
        code, body, _ = call("POST", f"/api/labs/{lab_id}/grade-debug/", t_token,
                             json={"total_score": score, "elapsed_seconds": 742})
        need(code == 200, f"grade-debug {score} HTTP 异常", body)
        d = body["data"]
        debug.append({"score": score, "passed": d["passed"], "dry_run": d["dry_run"],
                      "checks": d["checks"], "preview": d["preview"]})
        need(d["passed"] == (score != "101"), f"grade-debug {score} 判定异常", body)
        need(d["dry_run"] is True, "dry-run 标记缺失", body)
    print("grade-debug OK: 100/0/86.5 通过，101 未通过，均为 dry_run")

    code, body, _ = call("POST", "/api/lab-schedules/", t_token,
                         json={"lab": lab_id, "classroom": CLASSROOM_ID})
    need(code in (200, 201), "排课失败", body)
    code, body, _ = call("POST", f"/api/labs/{lab_id}/publish/", t_token, json={})
    need(code in (200, 201) and body.get("code") == 0, "发布失败", body)
    print("schedule + publish OK")

    code, body, _ = call("GET", f"/api/labs/{lab_id}/page/preview/", t_token)
    need(code == 200, "预览链接生成失败", body)
    preview_url = body["data"]["url"]

    code, body, _ = call("POST", "/api/lab-submissions/start/", s_token, json={"lab": lab_id})
    need(code in (200, 201) and body.get("code") == 0, "学生 start 失败", body)
    d = body["data"]
    out = {
        "base": BASE, "lab_id": lab_id, "lab_title": lab_title,
        "submission_id": d["submission"]["id"],
        "attempt_token": d["attempt_token"], "page_url": d["page_url"],
        "preview_url": preview_url, "teacher_token": t_token, "student_token": s_token,
        "course_id": COURSE_ID, "catalog_id": CATALOG_ID, "classroom_id": CLASSROOM_ID,
        "teacher": TEACHER[0], "teacher_pass": TEACHER[1],
        "student": STUDENT[0], "student_pass": STUDENT[1],
        "grade_debug": debug,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"student start OK: sub_id={out['submission_id']} token={out['attempt_token'][:12]}...")
    print("preview_url=" + preview_url)
    print("page_url=" + d["page_url"])
    print("out=" + args.out)


if __name__ == "__main__":
    main()
