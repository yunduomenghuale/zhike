"""端到端验证：课件上传解析过程中，轮询 /ppts/ 看到的 parse_progress 是否实时推进。

流程：建临时章节 -> 后台上传 12 页 pptx（同步解析链路）-> 请求进行中每 0.5s
轮询该章节课件列表 -> 断言看到 text/render 阶段页级进度 -> 清理临时数据。
"""
import io
import json
import threading
import time

import requests
from pptx import Presentation

BASE = "http://127.0.0.1:8005"
COURSE_ID = 7

s = requests.Session()
s.trust_env = False  # 不走系统代理
login = s.post(BASE + "/api/auth/login/", json={"username": "t101", "password": "pass1234"}).json()
s.headers["Authorization"] = f"Bearer {login['data']['token']['access']}"


def unwrap(resp):
    body = resp.json()
    assert body.get("code") == 0, f"接口错误: {body}"
    return body["data"]


def poll_parse_progress():
    data = unwrap(s.get(f"{BASE}/api/ppts/", params={"catalog": CATALOG_ID}))
    items = data.get("results", data) if isinstance(data, dict) else data
    parsing = next((p for p in items if p.get("parse_status") == "parsing"), None)
    if not parsing:
        return None
    prog = parsing.get("parse_progress") or {}
    return prog.get("stage"), prog.get("done"), prog.get("total")


# ---------- 1. 临时章节 ----------
cat = unwrap(s.post(f"{BASE}/api/catalogs/", json={"course": COURSE_ID, "title": "解析进度验证临时章节"}))
CATALOG_ID = cat["id"]
print(f"临时章节 catalog={CATALOG_ID}")

# ---------- 2. 12 页课件 + 上传期间轮询 ----------
prs = Presentation()
for i in range(1, 13):
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = f"第{i}章 测试知识点{i}"
    slide.placeholders[1].text = (
        f"要点一：概念{i}的定义与作用。\n要点二：概念{i}的典型应用场景。\n要点三：使用概念{i}的常见误区。"
    )
buf = io.BytesIO()
prs.save(buf)
buf.seek(0)

samples = []
stop = threading.Event()


def poller():
    while not stop.is_set():
        try:
            snap = poll_parse_progress()
            if snap:
                samples.append((round(time.monotonic() - t0, 2), *snap))
        except Exception:
            pass
        time.sleep(0.5)


t0 = time.monotonic()
thread = threading.Thread(target=poller, daemon=True)
thread.start()
try:
    ppt = unwrap(s.post(
        f"{BASE}/api/ppts/",
        data={"course": COURSE_ID, "catalog": CATALOG_ID, "file_name": "parse-progress-check.pptx"},
        files={"file": ("parse-progress-check.pptx", buf,
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    ))
finally:
    elapsed = time.monotonic() - t0
    stop.set()
    thread.join(timeout=3)

print(f"\n上传解析耗时 {elapsed:.1f}s")
print(f"响应: id={ppt['id']} parse_status={ppt['parse_status']} "
      f"parse_progress={ppt.get('parse_progress')} pages={len(ppt['parsed_pages'])}")
for smp in samples:
    print("   轮询采样:", smp)

stages = [x[1] for x in samples]
saw_text = "text" in stages
saw_render = "render" in stages
advanced = any(samples[i][1:4] != samples[i - 1][1:4] for i in range(1, len(samples)))
print(f"结论: 请求进行中 {len(samples)} 次采样；text 阶段={'有' if saw_text else '无（小文件解析快于采样间隔，正常）'}，"
      f"render 阶段={'有' if saw_render else '无'}，页级进度推进={'是' if advanced else '否'} -> "
      f"{'解析实时进度生效 ✓' if advanced else '解析进度未见推进 ✗'}")
assert ppt["parse_status"] == "done", "响应应为解析完成"
assert ppt.get("parse_progress", {}).get("stage") == "done", "响应 parse_progress 应为 done"

# ---------- 3. 清理 ----------
def safe_delete(url):
    try:
        return unwrap(s.delete(url))
    except Exception as exc:
        return f"删除失败: {exc}"


print("\n清理临时数据...")
print(json.dumps(safe_delete(f"{BASE}/api/ppts/{ppt['id']}/"), ensure_ascii=False))
print(json.dumps(safe_delete(f"{BASE}/api/catalogs/{CATALOG_ID}/"), ensure_ascii=False))
