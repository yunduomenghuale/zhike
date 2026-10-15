"""端到端验证：讲稿/配音生成请求进行中，轮询 /videos/ 看到的进度是否实时推进。

流程：建临时章节 -> 上传 6 页 pptx -> 讲稿生成（批内轮询）-> 配音生成（批内轮询）
-> Django shell 清理临时数据。不影响现有章节。
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


def progress():
    data = unwrap(s.get(f"{BASE}/api/videos/", params={"catalog": CATALOG_ID}))
    items = data.get("results", data) if isinstance(data, dict) else data
    if not items:
        return 0, 0
    scripts = items[0].get("scripts") or []
    done = sum(1 for x in scripts if str(x.get("script") or "").strip())
    audio = sum(1 for x in scripts if x.get("audio_url"))
    return done, len(scripts), audio


def run_with_polling(label, call):
    """发起一个生成请求，请求进行中每 1.2s 轮询一次进度，返回 (响应, 采样, 耗时)。"""
    samples = []
    stop = threading.Event()

    def poller():
        while not stop.is_set():
            try:
                samples.append((round(time.monotonic() - t0, 1), *progress()))
            except Exception:
                pass
            time.sleep(1.2)

    t0 = time.monotonic()
    thread = threading.Thread(target=poller, daemon=True)
    thread.start()
    try:
        result = call()
    finally:
        elapsed = time.monotonic() - t0
        stop.set()
        thread.join(timeout=3)
    print(f"\n== {label} ==")
    print(f"请求耗时 {elapsed:.1f}s，响应: {result}")
    for smp in samples:
        print("   轮询采样:", smp)
    mid = [x for x in samples if x[0] < elapsed - 0.4]
    return result, samples, elapsed, mid


# ---------- 1. 临时章节 + 6 页课件 ----------
cat = unwrap(s.post(f"{BASE}/api/catalogs/", json={"course": COURSE_ID, "title": "进度验证临时章节"}))
CATALOG_ID = cat["id"]
print(f"临时章节 catalog={CATALOG_ID}")

prs = Presentation()
for i in range(1, 7):
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = f"第{i}章 测试知识点{i}"
    slide.placeholders[1].text = f"要点一：概念{i}的定义与作用。\n要点二：概念{i}的典型应用场景。\n要点三：使用概念{i}的常见误区。"
buf = io.BytesIO()
prs.save(buf)
buf.seek(0)

ppt = unwrap(s.post(
    f"{BASE}/api/ppts/",
    data={"course": COURSE_ID, "catalog": CATALOG_ID, "file_name": "progress-check.pptx"},
    files={"file": ("progress-check.pptx", buf,
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
))
print(f"上传 ppt={ppt['id']} status={ppt['parse_status']} pages={len(ppt['parsed_pages'])}")
assert len(ppt["parsed_pages"]) == 6, "课件应解析出 6 页"

# ---------- 2. 讲稿：单批生成 + 批内轮询 ----------
before = progress()
print(f"\n生成前进度: {before}")
result, samples, elapsed, mid = run_with_polling(
    "讲稿生成（limit=2，4 页 = 3+1 两个小块）",
    lambda: unwrap(s.post(f"{BASE}/api/catalogs/{CATALOG_ID}/generate-script/", json={"limit": 2})),
)
script_advanced = [x for x in mid if x[1] > before[0]]
print(f"结论: 请求进行中 {len(mid)} 次采样，{len(script_advanced)} 次进度已推进 -> "
      f"{'讲稿实时进度生效 ✓' if script_advanced else '讲稿未见推进 ✗'}")

# 跑完剩余页（模拟前端循环）
guard = 0
while True:
    guard += 1
    r = unwrap(s.post(f"{BASE}/api/catalogs/{CATALOG_ID}/generate-script/", json={"limit": 6}))
    if r["done"] or guard > 10:
        break
print(f"讲稿全部完成: {progress()}")

# ---------- 3. 配音：单批生成 + 批内轮询 ----------
before_a = progress()
result_a, samples_a, elapsed_a, mid_a = run_with_polling(
    "配音生成（limit=2）",
    lambda: unwrap(s.post(f"{BASE}/api/catalogs/{CATALOG_ID}/generate-audio/", json={"limit": 2})),
)
audio_advanced = [x for x in mid_a if x[2] > before_a[2]]
print(f"结论: 请求进行中 {len(mid_a)} 次采样，{len(audio_advanced)} 次配音进度已推进 -> "
      f"{'配音实时进度生效 ✓' if audio_advanced else '配音未见推进 ✗'}")

guard = 0
while True:
    guard += 1
    ra = unwrap(s.post(f"{BASE}/api/catalogs/{CATALOG_ID}/generate-audio/", json={"limit": 3}))
    if ra["done"] or guard > 10:
        break
print(f"配音全部完成: {progress()}")

# ---------- 4. 清理 ----------
print("\n清理临时数据...")
print(json.dumps(unwrap(s.delete(f"{BASE}/api/ppts/{ppt['id']}/")), ensure_ascii=False))
try:
    print(json.dumps(unwrap(s.delete(f"{BASE}/api/catalogs/{CATALOG_ID}/")), ensure_ascii=False))
except Exception as exc:
    print(f"章节删除需服务端清理（向量片段外键保护）: {exc}")
