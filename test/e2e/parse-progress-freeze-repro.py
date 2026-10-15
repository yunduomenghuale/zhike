"""复现「上传解析 UI 冻结」：用用户第7章上传过的同一个 PDF，API 级记录
parse_status / parse_progress.stage 的完整时间线，定位冻结根因。

推断：perform_create 的事务块先把 parse_status 置 done（解析成功即激活），
之后才跑 ingest_ppt_pages（向量入库，44 页可能数分钟）；而前端轮询只认
parse_status === 'parsing'，状态一翻 done 轮询即失明——UI 停在最后一个
采样（如 render 43/44）直到上传 HTTP 响应回来才清零。
"""
import threading
import time

import requests

BASE = "http://127.0.0.1:8005"
COURSE_ID = 7
PPT_FILE = "D:/Claude_Code/智课系统V2/backend/media/ppt/1eacaf087c394965890ac3ca8f2c0e27.pdf"

s = requests.Session()
s.trust_env = False
login = s.post(BASE + "/api/auth/login/", json={"username": "t101", "password": "pass1234"}).json()
s.headers["Authorization"] = f"Bearer {login['data']['token']['access']}"


def unwrap(resp):
    body = resp.json()
    assert body.get("code") == 0, f"接口错误: {body}"
    return body["data"]


cat = unwrap(s.post(f"{BASE}/api/catalogs/", json={"course": COURSE_ID, "title": "冻结复现临时章节"}))
CATALOG_ID = cat["id"]
print(f"临时章节 catalog={CATALOG_ID}")

samples = []
stop = threading.Event()
t0 = time.monotonic()


def poller():
    while not stop.is_set():
        try:
            data = unwrap(s.get(f"{BASE}/api/ppts/", params={"catalog": CATALOG_ID}))
            items = data.get("results", data) if isinstance(data, dict) else data
            if items:
                p = items[0]
                prog = p.get("parse_progress") or {}
                samples.append((
                    round(time.monotonic() - t0, 2),
                    p.get("parse_status"),
                    prog.get("stage"),
                    prog.get("done"),
                    prog.get("total"),
                ))
        except Exception as exc:
            samples.append((round(time.monotonic() - t0, 2), "POLL_ERR", str(exc)[:60], "", ""))
        time.sleep(0.5)


thread = threading.Thread(target=poller, daemon=True)
thread.start()
try:
    with open(PPT_FILE, "rb") as f:
        ppt = unwrap(s.post(
            f"{BASE}/api/ppts/",
            data={"course": COURSE_ID, "catalog": CATALOG_ID, "file_name": "第2章.pdf"},
            files={"file": ("第2章.pdf", f, "application/pdf")},
        ))
finally:
    elapsed = time.monotonic() - t0
    stop.set()
    thread.join(timeout=3)

print(f"\n上传解析总耗时 {elapsed:.1f}s")
print(f"响应: status={ppt['parse_status']} pages={len(ppt['parsed_pages'])} "
      f"progress={ppt.get('parse_progress')} chunks={ppt.get('chunk_count')}")
print("\n时间线（t, parse_status, stage, done, total）：")
for smp in samples:
    print("   ", smp)

# 关键判断：parse_status 翻 done 的时刻 vs stage 还在 text/render 的时刻
status_done_t = next((x[0] for x in samples if x[1] == "done"), None)
blind_window = [x for x in samples if x[1] == "done" and x[2] in ("text", "render", "embed")]
print(f"\nparse_status 首次翻 done: t={status_done_t}s")
print(f"状态已 done 但阶段仍在 text/render/embed 的采样数: {len(blind_window)}"
      f"（>0 即前端轮询失明窗口，UI 会冻结在最后一帧）")

# 清理
def safe_delete(url):
    try:
        return unwrap(s.delete(url))
    except Exception as exc:
        return f"删除失败: {exc}"


print("\n清理临时数据...")
print(safe_delete(f"{BASE}/api/ppts/{ppt['id']}/"))
print(safe_delete(f"{BASE}/api/catalogs/{CATALOG_ID}/"))
