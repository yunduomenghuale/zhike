"""P0 L2 真实接口验证（直接打本地 8005，不经过前端）。"""

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8005"
PASS, FAIL = [], []

# 本机环境带系统代理，直连 127.0.0.1 必须显式绕过，否则会 502
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def req(method, path, token=None, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with _OPENER.open(r) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:200]}


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  OK   " if cond else "  FAIL ") + name + (("  → " + str(extra)) if extra else ""))


def items(payload):
    """列表接口兼容「裸数组」「分页对象 results」「管理端 items」三种形态。"""
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("results", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return data


def login(username, password):
    st, data = req("POST", "/api/auth/login/", body={"username": username, "password": password})
    assert st == 200, (st, data)
    return data["data"]["token"]["access"]


print("[1] 登录")
t_token = login("t101", "pass1234")
a_token = login("admin", "A0987654")
check("教师 t101 登录", bool(t_token))
check("管理员 admin 登录", bool(a_token))

print("[2] 班级接口：新状态枚举与新增字段")
st, data = req("GET", "/api/classes/", t_token)
rows = items(data)
check("GET /api/classes/ 200", st == 200, st)
check("班级数 = 6", len(rows) == 6, len(rows))
check("全部 status=active", all(r["status"] == "active" for r in rows), {r["status"] for r in rows})
check("status_display 为在读", all(r["status_display"] == "在读" for r in rows), {r["status_display"] for r in rows})
check("返回 code 字段（历史班为空）", "code" in rows[0], rows[0].get("code"))
check("返回 graduate_year 计算值", any(r["graduate_year"] for r in rows),
      [(r["name"], r["graduate_year"]) for r in rows])
check("建班人 teacher_name 可读", rows[0]["teacher_name"] == "张老师", rows[0]["teacher_name"])

print("[3] 课程接口：term 仍以文本返回（前端零改动）")
st, data = req("GET", "/api/courses/", t_token)
courses = items(data)
check("GET /api/courses/ 200", st == 200, st)
by_id = {c["id"]: c for c in courses}
check("计算机网络 term 文本 = 2026秋", by_id[5]["term"] == "2026秋", by_id[5]["term"])
check("计算机网络 term_id = 1", by_id[5]["term_id"] == 1, by_id[5]["term_id"])
check("数据结构B term 为空", by_id[6]["term"] == "" and by_id[6]["term_id"] is None,
      (by_id[6]["term"], by_id[6]["term_id"]))

print("[4] 学期筛选（FK 改造后 filterset 兼容文本）")
st, data = req("GET", "/api/courses/?term=2026", t_token)
check("?term=2026 返回 2 门", st == 200 and len(items(data)) == 2,
      st if st != 200 else [c["name"] for c in items(data)])
st, data = req("GET", "/api/courses/?term_id=1", t_token)
check("?term_id=1 返回 2 门", st == 200 and len(items(data)) == 2, st)

print("[5] 单班规则：把已在 A 班的学生加进 B 班必须被拒")
members = items(req("GET", "/api/class-students/?classroom=3", t_token)[1])
existing = members[0]["username"]
st, data = req("POST", "/api/classes/1/add-student/", t_token, {"username": existing})
check("跨班添加返回 409", st == 409, (st, data.get("message")))
check("错误信息含当前班级", "已在" in (data.get("message") or ""), data.get("message"))

print("[6] 回归：统计接口与导出接口")
st, data = req("GET", "/api/analytics/class/1/?course=5", t_token)
check("班级统计 200", st == 200, st)
# 导出返回二进制 xlsx，单独走不解析 JSON 的分支
_exp = urllib.request.Request(BASE + "/api/analytics/class/1/export/?course=5&sheets=overview")
_exp.add_header("Authorization", "Bearer " + t_token)
with _OPENER.open(_exp) as resp:
    _body = resp.read()
    _ctype = resp.headers.get("Content-Type", "")
check("班级导出 200 且为 xlsx",
      resp.status == 200 and len(_body) > 5000 and "spreadsheet" in _ctype,
      f"{resp.status} {_ctype} {len(_body)}B")

print("[7] 回归：作业 / 考试 / 学生端课程列表")
st, data = req("GET", "/api/homeworks/?classroom=1", t_token)
check("作业列表 200", st == 200, st)
st, data = req("GET", "/api/exams/?classroom=1", t_token)
check("考试列表 200", st == 200, st)
s_token = login("20249999", "pass1234")
st, data = req("GET", "/api/classes/", s_token)
check("学生班级列表 200", st == 200, st)
check("学生只见 1 个班（转班后）", len(items(data)) == 1,
      [(c["name"], c["status"]) for c in items(data)])

print("[8] 管理端：班级/课程监管字段")
st, data = req("GET", "/api/admin-panel/classes/?page=1&page_size=20", a_token)
check("管理端班级列表 200", st == 200, st)
st, data = req("GET", "/api/admin-panel/courses/?page=1&page_size=20", a_token)
check("管理端课程列表 200", st == 200, st)
if st == 200:
    course_rows = items(data)
    check("管理端课程 term 为文本", all(isinstance(c.get("term"), str) for c in course_rows),
          [c.get("term") for c in course_rows][:3])

print()
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：", FAIL)
    raise SystemExit(1)
