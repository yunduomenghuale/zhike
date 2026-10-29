"""历史班级编码补齐后的匹配验收（X-32：编码大小写归一）。

用真实的管理员导入「预览」接口验证：Excel 里写**小写**班级编码，必须命中
已有班级（状态 ok、目标班名正确），且不能进「待建班级」清单；真正不存在
的编码才该出现在待建清单里。只调预览、不提交，不写任何业务数据。

    cd backend && ./venv/Scripts/python.exe scripts/class_code_match_check.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from apps.classroom.models import ClassRoom  # noqa: E402

BASE = "http://127.0.0.1:8005"
ADMIN = ("admin", "A0987654")
STUDENT_HEADERS = ["学号", "姓名", "班级编码", "班级名称", "入学年"]

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  | {detail}" if detail else ""))
    return bool(ok)


def http(method: str, path: str, token: str | None = None, fields: dict | None = None):
    """ multipart/form-data 上传（预览接口只收 xlsx）。"""
    boundary = "----zhikecheck" + os.urandom(4).hex()
    body = bytearray()
    for key, value in (fields or {}).items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    for key, filename, blob, ctype in (fields or {}).get("_files", []):
        body += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; "
            f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'
        ).encode()
        body += blob
        body += b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + path,
        data=bytes(body),
        method=method,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def login(username: str, password: str) -> str:
    req = urllib.request.Request(
        BASE + "/api/auth/login/",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read())
    return payload["data"]["token"]["access"]


def main() -> int:
    from openpyxl import Workbook

    empty = (ClassRoom.objects.filter(code__isnull=True) | ClassRoom.objects.filter(code="")).count()
    check("系统中不再有空编码班级", empty == 0, f"剩余 {empty} 个")
    target = ClassRoom.objects.get(name="网络2026届-1班")
    check("目标班级编码已就位", bool(target.code), target.code or "")

    token = login(*ADMIN)

    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "code_match.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.append(STUDENT_HEADERS)
        # 小写编码：必须命中已有班（X-32）
        ws.append(["CODECASE01", "大小写甲", target.code.lower(), "网络2026届-1班", 2026])
        # 大写编码：同样命中已有班
        ws.append(["CODECASE02", "大小写乙", target.code.upper(), "网络2026届-1班", 2026])
        # 带空格的编码：归一后也应命中
        ws.append(["CODECASE03", "大小写丙", f"  {target.code.lower()}  ", "网络2026届-1班", 2026])
        # 真正不存在的编码：应该进待建清单
        ws.append(["CODECASE04", "待建丁", "zz-2099-99", "验收新建班", 2099])
        wb.save(path)
        blob = path.read_bytes()

        status, payload = http(
            "POST", "/api/admin-panel/imports/preview/", token,
            {"kind": "student", "create_missing_classes": "true",
             "_files": [("file", "code_match.xlsx", blob,
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")]},
        )

    if not check("预览接口可用", status == 200 and payload.get("code") == 0,
                 f"status={status} {payload.get('message')}"):
        return 1

    rows = payload.get("data", {}).get("rows") or []
    by_username = {r.get("username"): r for r in rows}
    pending = payload.get("data", {}).get("pending_classes") or []
    pending_codes = {str(p.get("code") or "").upper() for p in pending}

    for username in ("CODECASE01", "CODECASE02", "CODECASE03"):
        row = by_username.get(username) or {}
        # 预览行的字段是 row_status / target_class_name / target_class_id（见 imports.annotate_rows）
        check(f"{username}（{row.get('class_code') or '?'}）命中已有班级",
              row.get("row_status") == "ok" and row.get("target_class_name") == "网络2026届-1班"
              and row.get("target_class_id") == target.id,
              json.dumps({k: row.get(k) for k in
                          ("row_status", "class_code", "target_class_name", "target_class_id")},
                         ensure_ascii=False))
    check("小写/带空格编码没有生成待建班级",
          "ZZ-2099-99" in pending_codes and target.code.upper() not in pending_codes,
          f"待建清单：{sorted(pending_codes)}")
    check("待建清单里只有 1 个新编码", len(pending_codes) == 1, f"{sorted(pending_codes)}")

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n=== 结果：{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
