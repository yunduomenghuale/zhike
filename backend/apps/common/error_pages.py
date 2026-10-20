"""门控内容不可用时的统一提示页（直接浏览器导航场景，非 JSON）。

课程资源门控（courses/views.py）与实验门控（labs/views.py）共用同一套视觉，
保证「下架/链接过期/页面不存在」等场景用户看到的提示页样式一致。
"""
from django.http import HttpResponse


def render_block_page(status: int, title: str, hint: str):
    """统一风格的门控失败提示页（浅色卡片居中，适配桌面与移动端）。"""
    html = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title><style>body{{font-family:sans-serif;display:flex;"
        "align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f1f5f9}}"
        ".box{{background:#fff;border-radius:12px;padding:32px 40px;max-width:420px;text-align:center;"
        "box-shadow:0 8px 30px rgba(15,23,42,.08)}}h1{{font-size:18px;color:#0f172a;margin:0 0 10px}}"
        "p{{font-size:13px;color:#64748b;margin:0;line-height:1.7}}</style></head>"
        f'<body><div class="box"><h1>{title}</h1><p>{hint}</p></div></body></html>'
    )
    return HttpResponse(html, status=status, content_type="text/html; charset=utf-8")
