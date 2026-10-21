"""业务侧 AI 能力封装（对齐需求第 7 节大模型应用场景）。

所有函数只依赖 provider 抽象与向量检索工具，业务视图调用这里的函数即可。
真实模型未配置时自动走 Mock，保证一期业务流程可跑通。
"""
from __future__ import annotations

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings

from .calllog import ai_scene, copy_call_context, run_in_context, scene_decorator
from .models import AICallLog
from .providers.factory import get_provider
from .vectorstore import search_chunks


def _safe_json(text: str, default):
    try:
        # 兼容模型可能包裹的 ```json 代码块
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(cleaned)
    except Exception:
        pass
    # 退一步：从文本中提取第一个 JSON 数组/对象
    import re

    m = re.search(r"(\[.*\]|\{.*\})", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return default


# ---------------------------------------------------------------------------
# 授课计划 -> 课程目录（需求 T-D-02）
# ---------------------------------------------------------------------------
@scene_decorator(AICallLog.Scene.CATALOG_GEN)
def generate_catalog_from_plan(plan_text: str) -> list[dict]:
    provider = get_provider("chat")
    messages = [
        {"role": "system", "content": "你是课程建设助手，需从授课计划中识别章节结构。"},
        {
            "role": "user",
            "content": (
                "请识别章节结构，输出 JSON 数组，元素形如 "
                '{"title":"第一章 xxx","children":[{"title":"1.1 xxx"}]}。\n\n'
                f"授课计划：\n{plan_text}"
            ),
        },
    ]
    return _safe_json(provider.chat(messages), default=[])


# ---------------------------------------------------------------------------
# PPT 逐页讲解稿（需求 T-V-01）
# ---------------------------------------------------------------------------
@scene_decorator(AICallLog.Scene.SCRIPT_GEN)
def generate_scripts_for_video(pages: list[dict]) -> list[dict]:
    provider = get_provider("chat")
    pages = pages or []
    fallback = [_local_script_for_page(page) for page in pages]
    if not pages:
        return fallback

    compact_pages = []
    for page in pages[:30]:
        compact_pages.append(
            {
                "page": page.get("page"),
                "title": (page.get("title") or "")[:80],
                "body": _dedupe_page_body(page.get("body") or "")[:500],
            }
        )

    by_page = _request_script_batch(provider, compact_pages, timeout=45)
    if len(by_page) < len(compact_pages) and len(compact_pages) > 6:
        missing_pages = {page.get("page") for page in compact_pages if page.get("page") not in by_page}
        for i in range(0, len(compact_pages), 6):
            chunk = [page for page in compact_pages[i : i + 6] if page.get("page") in missing_pages]
            if not chunk:
                continue
            by_page.update(_request_script_batch(provider, chunk, timeout=45))

    scripts = []
    for page, local in zip(pages, fallback):
        script = by_page.get(page.get("page")) or local["script"]
        scripts.append({"page": page.get("page"), "script": _polish_script_text(script)})
    return scripts


@scene_decorator(
    AICallLog.Scene.SCRIPT_GEN,
    course_getter=lambda args, kwargs: getattr(args[0], "course_id", None),
)
def generate_script_pages_batched(video, pages: list[dict], batch_size: int = 6) -> dict:
    """分批为教学视频生成讲解稿（避免一次生成几十页超过网关 180s 超时）。

    对 video.scripts 中尚无讲解稿的页，每批最多 batch_size*2 页；批内按
    AI_SCRIPT_CHUNK_PAGES（默认 3 页）切成小块并发调用，**每个小块一完成即
    合并落库**（as_completed 增量保存）——前端轮询因此能在请求进行中就看到
    页数推进，不再「一批卡几分钟、响应后跳一大截」；请求中断不丢已完成页。
    AI 失败的页用本地兜底文本。
    返回 {generated, pages, script_pages, remaining, done}。

    超时：每小块的请求超时取管理端该能力配置的 timeout，未配则
    settings.AI_SCRIPT_TIMEOUT（默认 45s，可用 AI_SCRIPT_TIMEOUT 环境变量调大）——
    本地模型推理慢，不调大易整批超时落兜底。
    """
    provider = get_provider("chat")
    timeout = getattr(provider, "timeout", None) or getattr(settings, "AI_SCRIPT_TIMEOUT", 45)
    chunk_pages = max(1, int(getattr(settings, "AI_SCRIPT_CHUNK_PAGES", 3) or 3))
    pages = pages or []
    scripts = list(video.scripts or [])
    if not scripts:
        scripts = [{"page": page.get("page"), "script": ""} for page in pages]
    page_map = {page.get("page"): page for page in pages}

    pending = [item for item in scripts if not str(item.get("script") or "").strip()]
    batch = pending[: batch_size * 2]
    generated = 0
    if batch:
        compact_pages = []
        for item in batch:
            page_data = page_map.get(item.get("page"), {})
            compact_pages.append(
                {
                    "page": item.get("page"),
                    "title": (page_data.get("title") or "")[:80],
                    "body": _dedupe_page_body(page_data.get("body") or "")[:500],
                }
            )
        # 小块并发：线程间只读共享数据、各产各的 {page: script} 字典，主线程统一合并
        chunks = [
            compact_pages[i : i + chunk_pages] for i in range(0, len(compact_pages), chunk_pages)
        ]
        filled: set = set()  # 已拿到 AI 结果并合并落库的页

        def _absorb(chunk_result: dict) -> bool:
            """把一个小块的结果合并进 scripts 并立即落库，返回是否有新增。"""
            added = False
            for pg, script in (chunk_result or {}).items():
                if pg in filled or not script:
                    continue
                for item in batch:
                    if item.get("page") == pg and not str(item.get("script") or "").strip():
                        item["script"] = _polish_script_text(script)
                        filled.add(pg)
                        added = True
                        break
            if added:
                video.scripts = scripts
                video.save(update_fields=["scripts", "updated_at"])
            return added

        if len(chunks) > 1:
            with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
                # 线程池不继承 contextvars：提交时复制调用上下文（场景/trace_id/触发人）
                # 带进 worker，否则并发批次的调用流水丢场景归属
                futures = [
                    pool.submit(
                        run_in_context,
                        copy_call_context(),
                        _request_script_batch,
                        provider,
                        chunk,
                        timeout,
                    )
                    for chunk in chunks
                ]
                # as_completed：哪个小块先回来就先合并落库，进度实时可见
                for future in as_completed(futures):
                    try:
                        _absorb(future.result())
                    except Exception:
                        continue  # 单块异常不拖垮其他块；无结果页走本地兜底
        else:
            try:
                _absorb(_request_script_batch(provider, compact_pages, timeout=timeout))
            except Exception:
                pass  # 无结果页走本地兜底
        # AI 没覆盖到的页（失败/超时/漏页）：本地兜底文本补上再落库
        fallback_added = False
        for item in batch:
            if item.get("page") in filled:
                continue
            page_data = page_map.get(item.get("page"), {})
            item["script"] = _local_script_for_page(page_data)["script"]
            filled.add(item.get("page"))
            fallback_added = True
        if fallback_added:
            video.scripts = scripts
            video.save(update_fields=["scripts", "updated_at"])
        generated = len(batch)

    total = len(scripts)
    script_pages = sum(1 for item in scripts if str(item.get("script") or "").strip())
    all_done = total > 0 and script_pages == total
    if all_done:
        from django.utils import timezone

        video.gen_status = video.GenStatus.SCRIPT_READY
        # 与主线一次性生成接口保持一致：讲解稿全部完成即对学生发布
        video.is_published = True
        video.published_at = timezone.now()
        video.save(update_fields=["gen_status", "is_published", "published_at", "updated_at"])
    return {
        "generated": generated,
        "pages": total,
        "script_pages": script_pages,
        "remaining": total - script_pages,
        "done": all_done,
    }


def _request_script_batch(provider, compact_pages: list[dict], timeout: int) -> dict:
    if not compact_pages:
        return {}

    messages = [
        {
            "role": "system",
            "content": (
                "你是一名有课堂经验的高校教师，负责把 PPT 页面改写成可直接朗读的课堂讲解稿。"
                "只输出 JSON 数组，不要解释，不要 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请为每页 PPT 生成自然、连贯、适合配音朗读的课堂讲解稿。\n"
                "要求：\n"
                "1. 每页 100 到 180 字左右，像老师在课堂上讲，不要像摘要。\n"
                "2. 不要照抄 PPT 条目，不要出现“核心信息”“本页内容如下”“结合示例说明”等模板话。\n"
                "3. 先判断页面类型：课程安排页讲清学习节奏和考核规则；章节封面页做自然过渡；知识点页再解释概念。\n"
                "4. 如果 PPT 是列表，请把每个要点用一句话解释清楚，并说明它们之间的关系。\n"
                "5. 可以补充必要的过渡语和通俗解释，但不要编造课件没有支撑的知识点。\n"
                "6. 不要把课程安排、考核方式写成专业知识点。\n"
                "7. 每页开头必须变化，禁止用“这一页”“这页”“本页”“我们继续看”作为固定开头。\n"
                "8. 同一个概念和同一句话只能讲一次，禁止重复句子，也不要给不同页面追加相同的固定总结。\n"
                "9. 输出 JSON 数组，元素格式为 {\"page\":页码,\"script\":\"讲解稿\"}。\n\n"
                f"PPT 页面：\n{json.dumps(compact_pages, ensure_ascii=False)}"
            ),
        },
    ]

    try:
        result = _safe_json(
            provider.chat(messages, temperature=0.4, timeout=timeout, retries=2, enable_thinking=False),
            default=[],
        )
    except Exception:
        return {}

    if not isinstance(result, list):
        return {}

    by_page = {}
    for item in result:
        if not isinstance(item, dict):
            continue
        script = str(item.get("script") or "").strip()
        if script:
            by_page[item.get("page")] = script
    return by_page


def _local_script_for_page(page: dict) -> dict:
    title = (page.get("title") or f"第 {page.get('page', '')} 页").strip()
    body = _dedupe_page_body(page.get("body") or "").strip()
    if _is_course_intro_page(title, body):
        return {"page": page.get("page"), "script": _polish_script_text(_script_for_course_intro(body))}
    if _is_chapter_cover_page(title, body):
        return {"page": page.get("page"), "script": _polish_script_text(_script_for_chapter_cover(title))}

    points = _extract_page_points(body)
    section_title = _extract_section_title(body)
    if points:
        lead = _topic_lead(title, section_title)
        explanations = _dedupe_keep_order([_explain_point(point) for point in points[:6]])
        point_text = "；".join(explanations)
        script = f"{lead}{point_text}。"
    elif body:
        cleaned = _clean_inline_text(body)
        script = f"围绕“{title}”展开时，可以先把页面文字看作一个线索，重点理解它想引出的主题：{cleaned[:140]}。后面遇到具体概念时，再回到这里对照。"
    else:
        script = f"接下来进入“{title}”。先交代它在本章中的位置，再说明接下来要解决什么问题。听的时候先建立整体框架，后面遇到具体概念时就更容易串联起来。"
    return {"page": page.get("page"), "script": _polish_script_text(script)}


def _is_course_intro_page(title: str, body: str) -> bool:
    text = f"{title}\n{body}"
    return any(key in text for key in ["课程介绍", "学时安排", "考核方式", "平时考核", "实验安排"])


def _script_for_course_intro(body: str) -> str:
    lines = [_clean_inline_text(line) for line in (body or "").splitlines() if line.strip()]
    text = "\n".join(lines)
    total_hours = _find_value(text, r"学时安排[:：]?\s*(\d+)")
    lecture_hours = _find_value(text, r"讲授学时\s*(\d+)")
    lab_hours = _find_value(text, r"实验学时\s*(\d+)")
    exam = _find_line(lines, "考核方式")
    daily = _find_line(lines, "平时考核组成")
    homework = _find_line(lines, "作业形式")
    lab = _find_line(lines, "实验安排")
    design = _find_line(lines, "课程设计")

    parts = ["先交代课程怎么学、怎么考。"]
    if total_hours:
        if lecture_hours and lab_hours:
            parts.append(f"这门课一共 {total_hours} 学时，其中课堂讲授 {lecture_hours} 学时，实验 {lab_hours} 学时，所以理论和上机练习都要跟上。")
        else:
            parts.append(f"课程总学时是 {total_hours}，后续学习要按课件和实验节奏推进。")
    if exam:
        parts.append(f"考核采用{_speechy_ratio(_strip_label(exam, '考核方式'))}的结构，平时、实验和考试都会影响最终成绩。")
    if daily:
        parts.append(f"平时部分由{_speechy_ratio(_strip_label(daily, '平时考核组成'))}构成，不能只等期末突击。")
    if homework or lab:
        details = []
        if homework:
            details.append(f"作业包括{_strip_label(homework, '作业形式')}")
        if lab:
            details.append(f"实验包括{_speechy_ratio(_strip_label(lab, '实验安排'))}")
        parts.append(f"{'；'.join(details)}，这些安排是帮助大家把语法真正落实到代码里。")
    if design:
        parts.append("课程结束后还有课程设计，相当于把前面学过的内容综合用一次。")
    return "".join(parts)


def _is_chapter_cover_page(title: str, body: str) -> bool:
    return not body.strip() and bool(re.search(r"第.+章", title or ""))


def _script_for_chapter_cover(title: str) -> str:
    clean_title = _clean_inline_text(title).replace("\x0b", " ")
    return f"接下来进入“{clean_title}”。这部分相当于本章的开场，先告诉大家接下来要学习的范围。听这一章时，可以先抓住两个问题：它要介绍什么概念，以及这些概念后面会怎样用到 Java 程序设计里。"


def _extract_page_points(body: str) -> list[str]:
    points = []
    lines = [line for line in (body or "").splitlines() if line.strip()]
    if len(lines) <= 1:
        lines = re.split(r"(?=\d+[\.\、)]\s*)", body or "")

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^\d+(\.\d+)+\s*\S{0,24}$", line):
            continue
        line = re.sub(r"^[\s\-•·●○]+", "", line)
        line = re.sub(r"^\d+[\.\、)]\s*", "", line)
        line = re.sub(r"^[（(]?\d+[）)]\s*", "", line)
        line = line.strip(" ：:；;，,。")
        if not line:
            continue
        if len(line) <= 4 and re.search(r"第.+章|^\d+(\.\d+)+$", line):
            continue
        if line == body.strip():
            continue
        points.append(line)
    return _dedupe_keep_order(points)


def _extract_section_title(body: str) -> str:
    for raw in (body or "").splitlines():
        line = raw.strip()
        if re.match(r"^\d+(\.\d+)+\s+\S+", line):
            return re.sub(r"^\d+(\.\d+)+\s*", "", line).strip()
    return ""


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        key = re.sub(r"\s+", "", item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedupe_page_body(body: str) -> str:
    """移除 PPT 中因重叠文本框产生的重复文本，保留原始出现顺序。"""
    lines = [line.strip() for line in (body or "").splitlines() if line.strip()]
    if len(lines) <= 1:
        return (body or "").strip()

    seen = set()
    result = []
    for line in lines:
        key = re.sub(r"\s+", "", line).strip(" ：:；;，,。")
        key = re.sub(r"^[\-•·●○]*(?:\d+[.、)]|[（(]\d+[）)])", "", key)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(line)
    return "\n".join(result)


def _find_value(text: str, pattern: str) -> str:
    match = re.search(pattern, text or "")
    return match.group(1) if match else ""


def _find_line(lines: list[str], keyword: str) -> str:
    for line in lines:
        if keyword in line:
            return line
    return ""


def _strip_label(text: str, label: str) -> str:
    return re.sub(rf"^{re.escape(label)}\s*[:：]?\s*", "", text or "").strip()


def _speechy_ratio(text: str) -> str:
    return (text or "").replace("+", "、").replace("%", "%")


def _topic_lead(title: str, section_title: str = "") -> str:
    clean_title = section_title or re.sub(r"^\d+(\.\d+)*\s*", "", title).strip(" ：:；;，,。")
    if clean_title:
        return f"接下来讲“{clean_title}”。"
    return "继续往下看。"


def _explain_point(point: str) -> str:
    text = _clean_inline_text(point)
    explanations = {
        "前身": "先从 Java 的前身讲起，是为了理解它为什么一开始就重视跨平台和网络环境",
        "诞生": "再看 Java 正式诞生的背景，重点把握这门语言最初想解决什么开发问题",
        "Java2平台": "Java2 平台标志着 Java 体系逐渐成熟，课程后面的 API 和开发工具都建立在这个体系上",
        "三大平台": "三大平台把 Java 的应用场景分开理解，分别面向嵌入式、桌面基础和企业级开发",
        "Java ME": "Java ME 主要面向资源受限的嵌入式设备",
        "Java SE": "Java SE 是标准平台，也是学习 Java 语法、类库和基本程序结构的基础",
        "Java EE": "Java EE 面向企业级应用，关注服务器端组件和大型系统开发",
        "平台无关性": "平台无关性强调程序写好以后，可以在不同系统上运行，减少重复开发",
        "完全面向对象": "面向对象让程序围绕类和对象组织，结构更清晰，也更便于复用",
        "面向对象": "面向对象让程序围绕类和对象组织，结构更清晰，也更便于复用",
        "简单性": "简单性指的是语法和工程模型相对规整，初学者更容易建立编程习惯",
        "可靠性": "可靠性关注程序运行时的稳定表现，减少常见错误带来的影响",
        "安全性": "安全性体现在运行环境和语言机制对危险操作有一定约束",
        "多线程": "多线程让程序可以同时处理多个任务，适合网络服务和交互式应用",
        "分布式": "分布式能力使程序可以通过网络协作，支撑更复杂的应用场景",
        "JDBC": "JDBC 用来连接和操作数据库，是 Java 程序访问数据的重要接口",
        "JSP": "JSP 主要用于生成动态网页，帮助把 Java 能力用到 Web 页面中",
        "JavaBeans": "JavaBeans 强调组件化封装，便于在程序中复用对象",
        "EJB": "EJB 面向企业级组件开发，用来支撑更复杂的服务器端业务",
        "JavaMail": "JavaMail 提供邮件相关能力，可以让程序完成邮件发送和处理",
        "Application": "Application 是普通 Java 应用程序，通常从 main 方法开始运行",
        "Applet": "Applet 是早期嵌入网页运行的 Java 程序，今天更多作为历史概念了解",
        "动态性": "动态性说明 Java 可以在运行过程中加载和连接需要的类",
        "异常处理": "异常处理让程序遇到错误时有统一的处理机制，而不是直接失控退出",
        "安装JDK": "安装 JDK 是写 Java 程序的第一步，因为编译和运行工具都在这里",
        "设置环境变量": "设置环境变量是为了让命令行能够找到 Java 的编译和运行命令",
        "编译": "编译会把源代码转换成字节码，这是 Java 程序运行前的重要步骤",
        "运行Application": "运行 Application 时，要执行包含 main 方法的类",
        "命令行参数": "命令行参数可以在程序启动时把外部数据传给 main 方法",
        "包的概念": "包用来组织类和接口，避免命名冲突，也让项目结构更清楚",
        "导入包": "导入包可以让代码更方便地使用其他包中的类或接口",
        "默认包路径": "默认包路径说明没有声明 package 时类所在的位置，但实际项目中通常要主动规划包结构",
        "Java源程序结构": "Java 源程序结构体现了 package、import 和类声明之间的基本顺序",
        "jar文件": "jar 文件可以把一组类和资源打包，便于发布和引用",
        "安装MyEclipse": "安装并启动 MyEclipse 是为了使用集成开发环境完成项目管理和代码编辑",
        "界面": "熟悉界面能帮助我们找到项目、编辑器、控制台等常用区域",
        "代码提示": "代码提示可以减少拼写错误，也能帮助初学者熟悉类和方法",
        "项目和工作区": "项目和工作区用于组织代码文件，是使用 IDE 时必须先弄清楚的概念",
        "新建Java项目": "新建 Java 项目是使用 IDE 编写程序的第一步",
        "新建Java类": "新建 Java 类以后，代码才有具体承载的位置",
        "重构": "重构是在不改变功能的前提下调整代码结构，让程序更清楚、更容易维护",
        "切换工作区": "切换工作区会改变 IDE 当前管理的项目集合",
        "程序调试技术": "调试技术帮助我们定位程序哪里出了问题，而不是只看运行结果猜原因",
        "程序错误": "程序错误需要先判断发生在编写、编译还是运行阶段，再选择处理方法",
        "调试过程": "调试过程一般包括设置断点、单步执行、观察变量和分析调用顺序",
    }
    for key, explanation in explanations.items():
        if key in text:
            return explanation
    if len(text) <= 18:
        return f"{text}先作为一个名称建立印象，后面会通过操作或代码进一步展开"
    return text


def _clean_inline_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text.strip(" ：:；;，,。")


def _polish_script_text(text: str) -> str:
    text = _clean_inline_text(text)
    replacements = [
        (r"^这一页我们继续看[“\"]([^”\"]+)[”\"]。?", r"接下来讲“\1”。"),
        (r"^这一页我们讲[“\"]([^”\"]+)[”\"]。?", r"接下来讲“\1”。"),
        (r"^这一页围绕[“\"]([^”\"]+)[”\"]展开。?", r"围绕“\1”展开时，"),
        (r"^这一页的主题是[“\"]([^”\"]+)[”\"]。?", r"接下来进入“\1”。"),
        (r"^这一页相当于", "这里相当于"),
        (r"^这一页", ""),
        (r"^这页", ""),
        (r"^本页", ""),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text).strip()
    text = text.lstrip("，,。；;：: ")
    return _dedupe_script_clauses(text)


def _dedupe_script_clauses(text: str) -> str:
    """移除模型或本地规则生成的重复句/分号分句。"""
    segments = re.findall(r"[^。！？!?；;]+(?:[。！？!?；;]+|$)", text or "")
    if len(segments) <= 1:
        return text

    seen = set()
    result = []
    for segment in segments:
        content = re.sub(r"[。！？!?；;]+$", "", segment).strip()
        punctuation_match = re.search(r"([。！？!?；;]+)$", segment)
        punctuation = punctuation_match.group(1) if punctuation_match else ""
        key = re.sub(r"[\s‘’“”\"'，,：:（）()]", "", content).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(f"{content}{punctuation}")

    polished = "".join(result).strip()
    return re.sub(r"[；;]+$", "。", polished)


# ---------------------------------------------------------------------------
# 逐页 AI 配音（需求 T-V-03）：对讲解稿合成语音，落地音频地址
# ---------------------------------------------------------------------------
@scene_decorator(
    AICallLog.Scene.TTS,
    course_getter=lambda args, kwargs: getattr(args[0], "course_id", None),
)
def synthesize_audio_for_video(video, voice: str | None = None, limit: int | None = None) -> int:
    """为教学视频的逐页讲解稿补齐配音，音频地址写回 scripts 每页。返回本批新增成功页数。

    limit：本批最多合成的页数（分段生成，避免多页同步合成超过网关超时）；None 表示不限制。
    voice：发音人；优先级 调用参数 > 管理端该能力配置 > settings.AI_TTS_VOICE > Cherry。
    本地 TTS 的发音人是服务端说话人 ID，在管理端「语音合成」配置里填写。

    性能：本批页在线程池中并发合成（每页是独立的无状态 API 调用，实测单页约 6s）——
    并发 3 路可把 30 页课件的配音时间从约 3 分钟压到约 1 分钟；
    as_completed 每页成功即写库（进度实时可见，中断不丢已合成页）；失败页记
    audio_error，下次调用补齐。
    """
    provider = get_provider("tts")
    voice = voice or getattr(provider, "voice", "") or getattr(settings, "AI_TTS_VOICE", "Cherry")
    scripts = video.scripts or []

    todo = []
    for item in scripts:
        if item.get("audio_url"):
            item.pop("audio_error", None)
            continue
        if not (item.get("script") or "").strip():
            continue
        todo.append(item)
    if limit is not None:
        todo = todo[:limit]

    ok = 0
    if todo:
        def _persist():
            video.scripts = scripts
            video.save(update_fields=["scripts", "updated_at"])

        def _synthesize(item):
            # 每个 item 是独立 dict，线程间无共享状态；provider 只读配置，requests 线程安全
            try:
                item["audio_url"] = provider.tts(item["script"].strip(), voice=voice)
            except Exception as exc:
                item["audio_error"] = str(exc)[:300]
                return False
            item.pop("audio_error", None)
            return True

        with ThreadPoolExecutor(max_workers=min(3, len(todo))) as pool:
            # 与讲稿分批同理：复制调用上下文带进 worker，保留场景/trace_id/触发人
            futures = [
                pool.submit(run_in_context, copy_call_context(), _synthesize, item)
                for item in todo
            ]
            # as_completed：每合成成功一页立即落库，前端轮询可实时看到配音页数推进
            for future in as_completed(futures):
                if future.result():
                    ok += 1
                    _persist()

    audio_count = sum(1 for item in scripts if item.get("audio_url"))
    script_count = len([item for item in scripts if item.get("script")])
    all_done = script_count > 0 and audio_count == script_count
    video.scripts = scripts
    video.gen_status = (
        video.GenStatus.AUDIO_READY if all_done else video.GenStatus.SCRIPT_READY
    )
    if all_done:
        video.is_published = True  # 全部配音完成后自动对学生发布
    video.save(update_fields=["scripts", "gen_status", "is_published", "updated_at"])
    return ok


# ---------------------------------------------------------------------------
# 教辅资料入库：切分 -> 向量化 -> 写入片段（需求 T-K-02 / 7.2）
# ---------------------------------------------------------------------------
@scene_decorator(
    AICallLog.Scene.MATERIAL_EMBED,
    course_getter=lambda args, kwargs: getattr(args[0], "course_id", None),
)
def split_text_semantic(raw: str, size: int = 500, overlap: int = 60) -> list[str]:
    """语义切分：段落优先、句子兜底、相邻片段重叠。

    旧版 500 字符硬切会切断句子、割裂语义，跨片段的答案两边都残缺
    （2026-10-21 治理）。规则：
    1. 按换行/空行切段落，顺序聚合到 size 内成片段；
    2. 单段落超 size：按句末标点（。！？；）断句再聚合，仍超才硬切；
    3. 相邻片段尾部重叠 overlap 字符，重叠起点落在标点/空白边界，不截断词。
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", raw) if p.strip()]
    sentences: list[str] = []
    for para in paragraphs:
        if len(para) <= size:
            sentences.append(para)
            continue
        # 段落超长：断句（保留句末标点）
        buf = ""
        for part in re.split(r"(?<=[。！？；!?;])", para):
            part = part.strip()
            if not part:
                continue
            if len(part) > size:
                # 单句仍超长：硬切
                if buf:
                    sentences.append(buf)
                    buf = ""
                sentences.extend(part[i : i + size] for i in range(0, len(part), size))
            elif buf and len(buf) + len(part) > size:
                sentences.append(buf)
                buf = part
            else:
                buf = f"{buf}{part}" if buf else part
        if buf:
            sentences.append(buf)

    chunks: list[str] = []
    buf = ""
    for sent in sentences:
        if not buf:
            buf = sent
        elif len(buf) + len(sent) + 1 <= size:
            buf = f"{buf}\n{sent}"
        else:
            chunks.append(buf)
            buf = sent
    if buf:
        chunks.append(buf)

    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            tail = chunks[i - 1][-overlap:]
            m = re.search(r"[。！？；!?;\n]", tail)
            if m and m.end() < len(tail):
                tail = tail[m.end() :]
            overlapped.append(tail + chunks[i])
        chunks = overlapped
    return chunks


def ingest_material(material, chunk_size: int = 500) -> int:
    """把资料文本抽取→切分→向量化→写入知识库片段。返回片段数。

    文本抽取按文件类型（TXT/PDF/Word/PPT）自动进行；抽取为空时标记解析失败。
    切分走语义切分（段落优先+句子兜底+重叠），与 rebuild_vectors 口径一致。
    """
    from apps.knowledge.extractor import extract_text
    from apps.knowledge.models import KnowledgeChunk

    provider = get_provider("embed")
    file_path = material.file.path if material.file else ""
    raw_text = (getattr(material, "_extracted_text", "") or extract_text(file_path)).strip()

    if not raw_text:
        material.parse_status = material.ParseStatus.FAILED
        material.save(update_fields=["parse_status", "updated_at"])
        return 0

    pieces = split_text_semantic(raw_text, size=chunk_size) or [raw_text]

    embeddings = provider.embed(pieces)
    material.chunks.all().delete()
    objs = [
        KnowledgeChunk(
            source=KnowledgeChunk.Source.MATERIAL,
            material=material,
            course_id=material.course_id,
            catalog_id=material.catalog_id,
            content=piece,
            embedding=emb,
        )
        for piece, emb in zip(pieces, embeddings)
    ]
    KnowledgeChunk.objects.bulk_create(objs)

    material.parse_status = material.ParseStatus.DONE
    material.save(update_fields=["parse_status", "updated_at"])
    return len(objs)


# 向量接口单批上限（DashScope text-embedding 最多 10 条/请求）：超过必须切片，
# 否则整批 400 全量失败；切片后还可逐批回调进度，让上传弹窗的索引阶段可观测
EMBED_BATCH_SIZE = 10


@scene_decorator(
    AICallLog.Scene.PPT_EMBED,
    course_getter=lambda args, kwargs: getattr(args[0], "course_id", None),
)
def ingest_ppt_pages(ppt, on_progress=None) -> int:
    """把课件 PPT 逐页文本向量化写入知识库片段（每页一个片段）。

    课件是向量库的主要内容：QA 检索主要依赖它，因此上传解析成功后
    即入库（与教辅资料 ingest_material 对称）。

    与 ingest_material 的区别——失败必须「静默」：
    - 向量模型未配置/不可用（allow_fallback=False 下真实报错）时返回 0，
      旧片段原样保留，也不修改 PPT 的任何状态（QA 侧有原文拼接兜底，
      见 _gather_course_context 第 2 步）；
    - 全链路 allow_fallback=False，杜绝 64 维 Mock 假向量混入真实向量空间。

    分批：单批最多 EMBED_BATCH_SIZE 条（DashScope 上限），逐批
    on_progress(done, total) 回调；任一批失败即整体返回 0、不删旧片段，
    与改造前「一次性 embed 失败」语义一致。
    """
    from django.db import transaction

    from apps.knowledge.models import KnowledgeChunk

    pieces: list[str] = []
    page_nos: list = []
    for pg in ppt.parsed_pages or []:
        if not isinstance(pg, dict):
            continue
        text = f"{pg.get('title', '') or ''}\n{pg.get('body', '') or ''}".strip()
        if not text:
            continue
        pieces.append(text)
        page_nos.append(pg.get("page") or len(pieces))
    if not pieces:
        return 0

    provider = get_provider("embed")
    # 未配置向量模型（回退模拟模式）：本次不入库，QA 侧走原文拼接兜底
    from apps.ai.providers.mock import MockProvider

    if isinstance(provider, MockProvider):
        return 0
    total = len(pieces)
    embeddings: list = []
    for start in range(0, total, EMBED_BATCH_SIZE):
        batch = pieces[start : start + EMBED_BATCH_SIZE]
        try:
            batch_embeddings = provider.embed(batch, allow_fallback=False)
        except Exception:
            return 0
        if len(batch_embeddings) != len(batch) or any(not emb for emb in batch_embeddings):
            return 0
        embeddings.extend(batch_embeddings)
        if on_progress:
            try:
                on_progress(len(embeddings), total)
            except Exception:
                pass  # 进度回调失败不影响入库主流程

    objs = [
        KnowledgeChunk(
            source=KnowledgeChunk.Source.PPT,
            ppt=ppt,
            course_id=ppt.course_id,
            catalog_id=ppt.catalog_id,
            content=piece,
            page=page_no,
            embedding=emb,
        )
        for piece, page_no, emb in zip(pieces, page_nos, embeddings)
    ]
    with transaction.atomic():
        ppt.chunks.all().delete()
        KnowledgeChunk.objects.bulk_create(objs)
    return len(objs)


def ingest_video_scripts(video) -> int:
    """把教学视频的逐页讲解稿向量化写入知识库片段（每页一个片段）。

    讲稿是「最贴近讲课内容」的自然语言材料：入库后与课件/资料同池检索
    （替代旧版在 _gather_course_context 里无检索全量拼接的做法——课程级
    提问时讲稿覆盖随机且与已入库 PPT 页内容重复，2026-10-21 治理）。
    片段文本带 PPT 页标题（讲稿口语化、缺术语，标题利于检索命中）。

    与 ingest_ppt_pages 同款约定：Mock/失败静默返回 0、旧片段保留；
    全链路 allow_fallback=False；先算后删、事务内替换；调用方负责在
    讲稿整体就绪（整章生成完成/单页编辑保存）后调用，幂等全量替换。
    """
    from django.db import transaction

    from apps.knowledge.models import KnowledgeChunk

    video.refresh_from_db(fields=["scripts"])
    # PPT 页标题映射：讲稿片段带页标题利于检索（讲稿本身口语化、缺术语）
    page_titles: dict = {}
    for pg in (video.ppt.parsed_pages or []) if video.ppt else []:
        if isinstance(pg, dict) and pg.get("page"):
            page_titles[int(pg["page"])] = (pg.get("title") or "").strip()

    pieces: list[str] = []
    page_nos: list = []
    for s in video.scripts or []:
        if not isinstance(s, dict):
            continue
        text = (s.get("script") or "").strip()
        if not text:
            continue
        page_no = s.get("page") or len(pieces) + 1
        title = page_titles.get(int(page_no) if page_no else 0, "")
        pieces.append(f"{title}\n{text}" if title else text)
        page_nos.append(page_no)
    if not pieces:
        return 0

    provider = get_provider("embed")
    from apps.ai.providers.mock import MockProvider

    if isinstance(provider, MockProvider):
        return 0
    embeddings: list = []
    for start in range(0, len(pieces), EMBED_BATCH_SIZE):
        batch = pieces[start : start + EMBED_BATCH_SIZE]
        try:
            batch_embeddings = provider.embed(batch, allow_fallback=False)
        except Exception:
            return 0
        if len(batch_embeddings) != len(batch) or any(not emb for emb in batch_embeddings):
            return 0
        embeddings.extend(batch_embeddings)

    objs = [
        KnowledgeChunk(
            source=KnowledgeChunk.Source.SCRIPT,
            video=video,
            course_id=video.course_id,
            catalog_id=video.catalog_id,
            content=piece,
            page=page_no,
            embedding=emb,
        )
        for piece, page_no, emb in zip(pieces, page_nos, embeddings)
    ]
    with transaction.atomic():
        video.chunks.all().delete()
        KnowledgeChunk.objects.bulk_create(objs)
    return len(objs)


# ---------------------------------------------------------------------------
# 知识库问答（需求 S-K-01/02/04）
# ---------------------------------------------------------------------------
QA_SYSTEM_PROMPT = (
    "你是一位严谨、耐心的课程助教，负责根据教师提供的课程资料回答学生问题。\n"
    "【回答依据与优先级】\n"
    "1. 优先依据「课程资料片段」回答；片段按【资料N】编号，标头注明了来源类型、章节与页码。\n"
    "2. 多个片段内容冲突时以来源优先级仲裁：课件 > 讲解稿 > 课程资料；"
    "资料与你的通识冲突时以资料为准，并可简要说明。\n"
    "3. 使用了某资料片段的内容时，在该句末尾标注来源编号，格式如 [1][3]；"
    "未使用资料的内容不要标注。\n"
    "4. 资料不足以回答时，明确说明「课程资料中暂未覆盖该内容」，"
    "再基于通识简要回答并提示学生向教师确认。\n"
    "【回答风格】\n"
    "- 循序渐进：先给定义/结论，再展开解释，适当分点。\n"
    "- 学生追问时结合对话上下文理解指代（如「它」「第五个」），保持连贯。\n"
    "- 如果学生的问题或图片与本课程明显无关，简要说明并友好地引导其围绕课程提问；"
    "寒暄问候友好简短回应即可。\n"
)

# 前端图片提问未配文字时的默认问题文案（与前端两处保持一致）：此时检索无意义——
# 拿这句去 embed 只会命中噪声片段，跳过 RAG 直接走视觉理解。
IMAGE_ONLY_DEFAULT_QUESTION = "请描述并解读这张图片"


def est_tokens(text: str) -> int:
    """中英混合 token 保守估算：CJK 约 1.5 字/token，其余约 4 字符/token。

    用于上下文预算管理（历史装填 / RAG 注入）。宁可高估不可低估——低估会在
    provider 侧才触发上下文超限，走分级降级重试，白白多一次模型调用。
    """
    if not text:
        return 0
    cjk = sum(
        1
        for ch in text
        if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f" or "\uff00" <= ch <= "\uffef"
    )
    return math.ceil(cjk / 1.5 + (len(text) - cjk) / 4)


def rewrite_query_for_retrieval(question: str, history: list[dict] | None) -> str:
    """多轮对话时把最新问题改写成可独立检索的完整问题（查询改写）。

    为什么需要：追问（"第五个详细讲讲""那它呢"）拿原句去 embed 检索必然退化
    ——历史只进 messages 没进检索，多轮越深入回答越脱离课程资料。改写结果
    只用于检索（embed/重排 query），不进 messages、不改变学生看到的问题；
    任何异常（超时/格式异常）静默回退原问题——改写是增强项，不能拖垮主链路。
    """
    if not history:
        return question
    # 取最近 3 轮（问答对 = 2 条 message）作改写上下文
    lines = []
    for msg in history[-6:]:
        role = "问" if msg.get("role") == "user" else "答"
        lines.append(f"{role}: {str(msg.get('content') or '')[:200]}")
    prompt = (
        "你是检索查询改写器。根据对话历史，把学生的最新问题改写成可独立检索的完整问题："
        "补全指代（这个/它/第N个/上面说的）、保留专业术语、不回答问题本身。"
        "只输出改写后的问题，单行，不要解释。\n\n"
        "对话历史：\n" + "\n".join(lines) + f"\n最新问题：{question}"
    )
    try:
        provider = get_provider("chat")
        with ai_scene(AICallLog.Scene.QA_REWRITE):
            rewritten = provider.chat(
                [{"role": "user", "content": prompt}],
                temperature=0,
                enable_thinking=False,
            )
    except Exception:
        return question
    rewritten = (rewritten or "").strip()
    rewritten = rewritten.splitlines()[0].strip() if rewritten else ""
    # 防空输出 / 异常长输出（模型没按指令只给问题时回退原问题）
    if not rewritten or len(rewritten) > 500:
        return question
    return rewritten


# ---------------------------------------------------------------------------
# 检索编排：向量召回 -> 重排序 -> 阈值过滤（RAG 引用质量治理）
# ---------------------------------------------------------------------------
def _resolve_rerank_threshold(model_name: str) -> float:
    """解析重排相关性阈值：显式环境变量 > 按模型名匹配的分模型阈值 > 默认值。

    为什么不能一个阈值打天下：不同重排模型的分数尺度差异极大——
    gte-rerank-v2 相关片段只有 0.09~0.9（无关 ~0.006），qwen3-rerank 相关
    0.87+（无关 ~0.09）。曾统一按 qwen3 量级取 0.3，结果 gte-rerank 下
    「考核方式」一问的目标页仅 0.288 被当作不相关滤掉，参考来源全空
    （2026-10-15 实测复现），故阈值必须随模型解析。
    """
    explicit = getattr(settings, "AI_RERANK_THRESHOLD", None)
    if explicit is not None:
        try:
            return float(explicit)
        except (TypeError, ValueError):
            pass
    table = getattr(settings, "AI_RERANK_MODEL_THRESHOLDS", {}) or {}
    name = (model_name or "").lower()
    best_key, best_value = "", None
    for key, value in table.items():
        key = str(key).lower()
        if key in name and len(key) > len(best_key):
            best_key, best_value = key, value
    if best_value is not None:
        return float(best_value)
    return float(getattr(settings, "AI_RERANK_THRESHOLD_DEFAULT", 0.3) or 0.3)


class RetrievalUnit:
    """同页融合后的检索单元：主片段 + （可选）同页另一来源片段。

    讲稿由该页 PPT 生成，同页课件片段与讲稿片段同时命中时，同一知识点会以
    两种形态重复占用注入单元与引用编号——融合为一个单元（高分者为主片段，
    另一个内容并入），信息不丢、编号不重复（2026-10-21 讲稿入检索体系引入）。
    """

    __slots__ = ("chunk", "score", "peer")

    def __init__(self, chunk, score: float, peer=None):
        self.chunk, self.score, self.peer = chunk, score, peer

    @property
    def sources(self) -> list[str]:
        """单元包含的来源类型（主片段在前），如 ["ppt"] / ["ppt", "script"]。"""
        kinds = [self.chunk.source]
        if self.peer is not None:
            kinds.append(self.peer.source)
        return kinds

    @property
    def text(self) -> str:
        if self.peer is None:
            return self.chunk.content
        return f"{self.chunk.content}\n{self.peer.content}"


def _merge_same_page_units(picked: list[tuple]) -> list[RetrievalUnit]:
    """把 top_k 结果按 (章节, 页码) 融合同页 ppt+script 片段（见 RetrievalUnit）。

    material 片段无页码概念，不参与融合；融合保持原有降序位置。
    """
    by_page: dict[tuple, RetrievalUnit] = {}
    order: list[RetrievalUnit] = []
    for chunk, score in picked:
        key = None
        if chunk.page and chunk.source in ("ppt", "script"):
            key = (chunk.catalog_id, chunk.page)
        if key and key in by_page:
            unit = by_page[key]
            # 高分者为主片段（同分保留先到者）
            if score > unit.score:
                unit.peer, unit.chunk, unit.score = unit.chunk, chunk, score
            else:
                unit.peer = chunk
            continue
        unit = RetrievalUnit(chunk, score)
        if key:
            by_page[key] = unit
        order.append(unit)
    return order


def _search_relevant_chunks(
    course_id: int,
    question: str,
    *,
    student_access: bool = False,
    classroom_ids=None,
    catalog_id=None,
    top_k: int = 5,
) -> list[RetrievalUnit]:
    """检索并精排课程知识库片段，返回 [RetrievalUnit]（按相关性降序，同页已融合）。

    为什么需要重排：向量检索是纯余弦相似度，关键词面重合但语义不相关的片段
    也会拿高分——实测「Java 程序设计这门课的考核方式是什么？」一问，噪声页
    （网络层/多线程课件页）与目标页分数带重叠（0.54~0.76），直接取 top_k=5
    会把 4 页噪声当「参考来源」展示，用户感知为「乱引用」。

    编排（配了重排能力时）：
    1. 向量召回 AI_RERANK_RECALL 条候选（比 top_k 多，给重排留筛选余地）。
       传入 catalog_id 时候选池收敛到该章节名下的片段（资料/课件挂靠该章节），
       「这一章的重点是什么」不再把其他章节与未挂章节资料（如遗留测试上传）
       送进候选——重排压分挡不住语义沾边的跨章节内容（2026-10-15 实测：
       未挂章节的测试 PDF 重排分 0.1661 反超目标页）；
    2. 重排模型按 query 语义相关性精排，阈值按模型解析（见 _resolve_rerank_threshold）：
       - 最高分都低于阈值 → 判定本课资料确实没有与问题直接相关的内容，返回空，
         上层据此走「资料无相关内容」的话术；
       - 否则保留分数 >= max(阈值, 最高分 * AI_RERANK_KEEP_RATIO) 的片段——
         与最高分存在 2 倍以上落差的多为同课程弱相关噪声，相对截断避免乱引用；
    3. 取前 top_k 条返回，score 为重排相关性分。

    章节兜底：章节内没有任何已挂靠片段（资料未挂章节/章节无课件）时退回全课程
    检索——避免这类课程在章节内一问就「资料不足」；章节有素材时严格按章节过滤。

    回退（重排是增强项，不能拖垮问答主链路）：未配置重排能力（Mock）/
    非 DashScope 端点 / 网络或接口异常 / 响应结构异常（无有效条目）时，
    按原行为返回向量 top_k——噪声问题回到治理前，但问答链路始终可用。
    """
    embed_provider = get_provider("embed")
    # 召回数显式配小（< top_k）时尊重配置：候选池小，最终结果就少，不强行抬回 top_k
    recall = max(int(getattr(settings, "AI_RERANK_RECALL", 15) or 15), 1)

    query_vec = embed_provider.embed([question])[0]
    candidates = [
        (chunk, score)
        for chunk, score in search_chunks(
            course_id,
            query_vec,
            top_k=recall,
            student_access=student_access,
            classroom_ids=classroom_ids,
            catalog_id=catalog_id,
        )
        if score > 0
    ]
    if not candidates and catalog_id:
        # 章节无挂靠片段：退回全课程检索（见 docstring「章节兜底」）
        candidates = [
            (chunk, score)
            for chunk, score in search_chunks(
                course_id,
                query_vec,
                top_k=recall,
                student_access=student_access,
                classroom_ids=classroom_ids,
            )
            if score > 0
        ]
    if not candidates:
        return []

    rerank_provider = get_provider("rerank")
    # 模型名两种取法：OpenAI 兼容服务用 rerank_model，系统内置本地模型用 model
    model_name = (
        getattr(rerank_provider, "rerank_model", "")
        or getattr(rerank_provider, "model", "")
        or ""
    )
    threshold = _resolve_rerank_threshold(model_name)
    # keep_ratio 允许显式配 0（关闭相对截断）：不能用 `or` 兜底，否则 0 会被当成未配置
    try:
        keep_ratio = min(max(float(getattr(settings, "AI_RERANK_KEEP_RATIO", 0.5)), 0.0), 1.0)
    except (TypeError, ValueError):
        keep_ratio = 0.5

    try:
        ranked = rerank_provider.rerank(
            question, [chunk.content for chunk, _ in candidates], top_n=top_k
        )
    except Exception:
        return _merge_same_page_units(candidates[:top_k])

    scored: list[tuple[int, float]] = []
    for item in ranked:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        score = item.get("score")
        if not isinstance(index, int) or not 0 <= index < len(candidates):
            continue
        if not isinstance(score, (int, float)):
            continue
        scored.append((index, float(score)))
    if not scored:
        # 协议异常（有候选但重排未返回有效条目）：回退纯向量 top_k，
        # 而不是把候选全部丢弃导致问答无资料可用
        return _merge_same_page_units(candidates[:top_k])

    top_score = max(score for _, score in scored)
    if top_score < threshold:
        # 最高分都够不到阈值：本课资料确实没有与问题直接相关的内容，返回空——
        # 上层据此走「资料无相关内容」的话术，而不是把关键词命中的噪声当参考来源
        return []
    cutoff = max(threshold, top_score * keep_ratio)
    picked = [
        (candidates[index][0], score) for index, score in scored if score >= cutoff
    ]
    # 同页 ppt+script 融合：讲稿由该页 PPT 生成，同现于结果时合并为一个单元
    return _merge_same_page_units(picked[:top_k])


# 注入标头的来源类型名（与 cited.source 一致；前端来源徽章同口径）
_SOURCE_LABELS = {
    "material": "课程资料",
    "ppt": "课件",
    "script": "讲解稿",
    "ppt+script": "课件+讲稿",
    "script+ppt": "讲稿+课件",
    "prev": "上一轮参考",
}

# 单个注入单元（原文兜底课件 / 单章讲稿汇总）的字符上限：
# 防止一个单元吃光整个 RAG 预算，也让截断发生在单元边界而非句子中间
_CONTEXT_UNIT_MAX_CHARS = 800


def _chunk_display_name(chunk) -> str:
    """参考来源展示名：优先真实章节名（教师上传文件名可能与章节无关/混乱）。
    资料挂章节 → 「章节标题 · 资料」，未挂 → 原文件名；
    课件片段 → 「章节标题课件」，回退文件名；讲稿片段 → 「章节标题讲解稿」。
    """
    material = chunk.material
    if material is not None:
        if material.catalog_id and material.catalog:
            return f"{material.catalog.title} · 资料"
        return material.file_name
    if chunk.ppt is not None:
        ppt_obj = chunk.ppt
        if ppt_obj.catalog_id and ppt_obj.catalog:
            return f"{ppt_obj.catalog.title}课件"
        return ppt_obj.file_name or "课程课件"
    if chunk.video is not None:
        video = chunk.video
        if video.catalog_id and video.catalog:
            return f"{video.catalog.title}讲解稿"
        return "课程讲解稿"
    return "课程资料"


def _context_header(n: int, source: str, name: str, page=None) -> str:
    """注入标头：【资料N｜类型｜名称｜页码】——模型据此在回答中标注 [N] 引用，
    编号与 cited[n] 一一对应，前端可据此做引用回链。"""
    page_part = f"｜P{page}" if page else ""
    return f"【资料{n}｜{_SOURCE_LABELS.get(source, '课程资料')}｜{name}{page_part}】"


def _gather_course_context(
    course_id,
    question: str,
    catalog_id=None,
    *,
    student_access: bool = False,
    classroom_ids=None,
    token_budget: int | None = None,
) -> tuple[str, list[dict], dict]:
    """汇总某课程可用于问答的资料上下文（需求 S-K-01/02）。返回 (context, cited, snapshot)。

    资料来源按优先级填充 RAG 预算（AI_QA_RAG_TOKEN_BUDGET，token 维度）：
    1. 知识库检索片段（_search_relevant_chunks 编排：向量召回+重排+阈值过滤
       +同页融合；讲稿片段与课件/资料同池竞争）；
    2. 课件 PPT 原文兜底（仅该课件未入向量库时，避免与检索结果重复占用预算）；
    3. 逐页讲解稿原文兜底（同样仅未入向量库时启用；讲稿已入检索体系，
       正常走第 1 步同页融合，不再无差别全量拼接）。

    每个注入单元带结构化标头（【资料N｜类型｜名称｜页码】），编号与 cited
    一一对应——模型知道每段出处并可标注 [N] 引用，前端可做引用回链；预算
    按 token 估算（est_tokens）并在单元边界截断。
    snapshot 为上下文快照（预算/命中片段元数据/降级级别），供 QARecord 审计
    与追问兜底使用。
    """
    from apps.courses.models import PPTResource, TeachingVideo
    from apps.knowledge.models import KnowledgeChunk

    if token_budget is None:
        token_budget = int(getattr(settings, "AI_QA_RAG_TOKEN_BUDGET", 3000) or 3000)

    units: list[str] = []  # 注入单元（标头+内容），按优先级序
    cited: list[dict] = []
    used_tokens = 0

    def _try_add(source: str, name: str, content: str, cited_item: dict, page=None) -> bool:
        """预算内追加一个注入单元；返回是否成功。编号 = 单元序号，与 cited 对齐。"""
        nonlocal used_tokens
        content = content[:_CONTEXT_UNIT_MAX_CHARS].strip()
        if not content:
            return False
        n = len(units) + 1
        header = _context_header(n, source, name, page)
        cost = est_tokens(header) + est_tokens(content)
        if used_tokens + cost > token_budget:
            return False
        units.append(f"{header}\n{content}")
        cited.append({"n": n, "source": source, **cited_item})
        used_tokens += cost
        return True

    # 1) 知识库向量检索（若有片段）。课程没有任何片段时跳过 embed 调用，
    #    省一次 embedding API 往返（首字延迟的主要来源之一）。
    if KnowledgeChunk.objects.filter(course_id=course_id).exists():
        try:
            for unit in _search_relevant_chunks(
                course_id,
                question,
                student_access=student_access,
                classroom_ids=classroom_ids,
                catalog_id=catalog_id,
            ):
                chunk = unit.chunk
                source_key = "+".join(unit.sources)  # ppt / material / ppt+script
                name = _chunk_display_name(chunk)
                added = _try_add(
                    source_key,
                    name,
                    unit.text,
                    {
                        "chunk_id": chunk.id,
                        "material_name": name,
                        "page": chunk.page,
                        "snippet": chunk.content[:120],
                        "score": round(unit.score, 4),
                    },
                    page=chunk.page,
                )
                if not added:  # 预算耗尽：后续片段排名更低，整段舍弃
                    break
        except Exception:
            pass

    # 2) 课件 PPT 讲义原文兜底：仅当该课件没有任何向量片段（向量模型不可用/
    #    从未重建）时启用，避免同一份内容既进检索结果又进原文、挤占预算。
    ppt_qs = PPTResource.objects.filter(course_id=course_id, is_active=True).select_related("catalog")
    if student_access:
        ppt_qs = ppt_qs.filter(catalog__is_published=True)
    if catalog_id:
        ppt_qs = ppt_qs.filter(catalog_id=catalog_id)
    seen_catalogs: set = set()
    for ppt in ppt_qs.order_by("catalog_id", "-version"):
        if ppt.catalog_id in seen_catalogs:  # 每个章节只取最新启用版本
            continue
        seen_catalogs.add(ppt.catalog_id)
        if ppt.chunks.exists():
            continue  # 已入向量库：走检索，不重复拼接原文
        page_segs = []
        for pg in (ppt.parsed_pages or [])[:40]:
            seg = f"{pg.get('title', '')} {pg.get('body', '')}".strip()
            if seg:
                page_segs.append(seg)
        if not page_segs:
            continue
        ppt_name = (
            f"{ppt.catalog.title}课件" if ppt.catalog_id and ppt.catalog else (ppt.file_name or "课程课件")
        )
        _try_add(
            "ppt",
            ppt_name,
            "\n".join(page_segs),
            {"material_name": ppt_name, "page": None, "snippet": page_segs[0][:120]},
        )

    # 3) 逐页讲解稿原文兜底：仅当该视频讲稿未入向量库（向量模型不可用/尚未
    #    回填/回滚开关关闭讲稿检索）时才原文限量拼接——正常已走第 1 步检索。
    script_disabled = bool(getattr(settings, "AI_QA_DISABLE_SCRIPT_SOURCE", False))
    vid_qs = TeachingVideo.objects.filter(course_id=course_id).select_related("catalog")
    if student_access:
        vid_qs = vid_qs.filter(catalog__is_published=True, is_published=True)
    if catalog_id:
        vid_qs = vid_qs.filter(catalog_id=catalog_id)
    for vid in vid_qs.order_by("catalog_id"):
        if not script_disabled and vid.chunks.exists():
            continue  # 已入向量库：走检索与同页融合，不重复拼接原文
        texts = []
        for s in (vid.scripts or []):
            t = (s.get("script") or "").strip()
            if t:
                page_no = s.get("page")
                texts.append(f"P{page_no} {t}" if page_no else t)
        if not texts:
            continue
        script_name = (
            f"{vid.catalog.title}讲解稿" if vid.catalog_id and vid.catalog else "课程讲解稿"
        )
        _try_add(
            "script",
            script_name,
            "\n".join(texts),
            {"material_name": script_name, "page": None, "snippet": texts[0][:120]},
        )

    # 上下文快照：预算与命中片段元数据（QARecord 审计 / 追问兜底用）
    snapshot = {
        "budgets": {"rag_tokens": token_budget},
        "chunks": [
            {
                k: item[k]
                for k in ("n", "chunk_id", "source", "page", "score")
                if item.get(k) is not None
            }
            for item in cited
        ],
        "degraded_level": 0,
    }
    return "\n\n".join(units), cited, snapshot


_HISTORY_ELLIPSIS = "……（中间省略）……"


def _clip_history_text(text: str, limit: int) -> str:
    """超长文本保留首尾：开头含结论与结构，结尾含列举的最后条目。

    追问（如"第五点详细讲讲"）常指向列举的末尾，故尾部权重略高（4:6）。
    """
    if len(text) <= limit:
        return text
    marker = _HISTORY_ELLIPSIS
    if limit <= len(marker) * 2 + 40:
        return text[:limit]
    usable = limit - len(marker)
    tail_len = int(usable * 0.6)
    head_len = usable - tail_len
    return text[:head_len] + marker + text[-tail_len:]


def build_qa_history(
    course_id: int,
    student_id,
    session: str,
    *,
    exclude_id=None,
    max_turns: int = 10,
    max_chars_per_msg: int = 4000,
    total_token_budget: int | None = None,
) -> list[dict]:
    """取同会话最近 N 轮问答，拼成多轮 messages（需求：AI 问答多轮对话）。

    - 只认「student + course + session」三元组，天然会话隔离；
    - 超长回答以「首尾保留」方式裁剪（绝不整轮丢弃）——课程问答的总结/
      详解类回答天然很长，整轮跳过会让多轮上下文在最常见场景下失效；
    - 总预算为 token 维度（est_tokens 估算）：缺省按 AI_CHAT_CONTEXT_WINDOW
      联动（窗口 − RAG 注入 − 输出预留 − system/模板 − 安全余量），窗口配小
      时历史自动收紧；从新往旧装填，超预算丢最旧轮次；
    - 生成失败/空回答不入历史；返回按时间正序的 messages。
    """
    if not session:
        return []
    from apps.knowledge.models import QARecord

    if total_token_budget is None:
        window = int(getattr(settings, "AI_CHAT_CONTEXT_WINDOW", 32768) or 32768)
        rag = int(getattr(settings, "AI_QA_RAG_TOKEN_BUDGET", 3000) or 3000)
        reserve = int(getattr(settings, "AI_QA_OUTPUT_RESERVE", 2048) or 2048)
        # system/模板约 600，安全余量 512；下限 2000 保证小窗口模型也能带几轮
        total_token_budget = max(2000, window - rag - reserve - 600 - 512)

    qs = (
        QARecord.objects.filter(course_id=course_id, student_id=student_id, session=session)
        .exclude(answer="")
        .exclude(question="")
        .order_by("-id")
    )
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    rows = list(qs[:max_turns])  # 一轮 = 一条 QARecord；倒序取最近 N 轮

    turns: list[tuple[str, str]] = []
    used = 0
    for rec in rows:  # 从新往旧收，超预算时丢最旧轮次
        q = _clip_history_text(rec.question.strip(), 300)
        a = _clip_history_text((rec.answer or "").strip(), max_chars_per_msg)
        # 失败/兜底回答不入历史
        if not q or not a or a.startswith("[出错]") or "AI 助教暂时没有响应" in a[:60]:
            continue
        pair_tokens = est_tokens(q) + est_tokens(a)
        if used + pair_tokens > total_token_budget:
            break
        used += pair_tokens
        turns.append((q, a))
    turns.reverse()  # 恢复时间正序

    history: list[dict] = []
    for q, a in turns:
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": a})
    return history


# 会话滚动摘要参数：会话超过 12 轮后，每累计 6 轮未摘要内容触发一次压缩；
# 原文保留最近 6 轮，更早轮次以摘要形式注入（见 build_conversation_context）
QA_SUMMARY_TRIGGER_TURNS = 12
QA_SUMMARY_KEEP_RECENT_TURNS = 6
QA_SUMMARY_MIN_BATCH_TURNS = 6
QA_MAX_RECENT_TURNS = 10


def build_conversation_context(
    qa_session,
    *,
    max_recent_turns: int = QA_MAX_RECENT_TURNS,
    max_chars_per_msg: int = 4000,
    total_token_budget: int | None = None,
) -> list[dict]:
    """基于持久化会话（QASession）装配历史 messages：[摘要段] + 预算内最近原文轮。

    - 有滚动摘要时：摘要作为 system 段置顶，原文轮只取 summary_upto_turn 之后的；
    - 预算装填（est_tokens，与上下文窗口联动）：从新往旧，超预算丢最旧轮次；
    - 失败/兜底回答不入历史；返回按时间正序的 messages。
    """
    if qa_session is None:
        return []
    if total_token_budget is None:
        window = int(getattr(settings, "AI_CHAT_CONTEXT_WINDOW", 32768) or 32768)
        rag = int(getattr(settings, "AI_QA_RAG_TOKEN_BUDGET", 3000) or 3000)
        reserve = int(getattr(settings, "AI_QA_OUTPUT_RESERVE", 2048) or 2048)
        total_token_budget = max(2000, window - rag - reserve - 600 - 512)

    rows = list(
        qa_session.records.exclude(answer="")
        .exclude(question="")
        .filter(turn_index__gt=qa_session.summary_upto_turn)
        .order_by("-turn_index", "-id")[:max_recent_turns]
    )

    turns: list[tuple[str, str]] = []
    used = 0
    for rec in rows:  # 从新往旧收，超预算时丢最旧轮次
        q = _clip_history_text(rec.question.strip(), 300)
        a = _clip_history_text((rec.answer or "").strip(), max_chars_per_msg)
        if not q or not a or a.startswith("[出错]") or "AI 助教暂时没有响应" in a[:60]:
            continue
        pair_tokens = est_tokens(q) + est_tokens(a)
        if used + pair_tokens > total_token_budget:
            break
        used += pair_tokens
        turns.append((q, a))
    turns.reverse()  # 恢复时间正序

    history: list[dict] = []
    if qa_session.summary:
        history.append(
            {
                "role": "system",
                "content": (
                    "以下是本对话此前内容的摘要（背景信息，非学生发言，"
                    "回答时不要向学生复述摘要本身）：\n" + qa_session.summary
                ),
            }
        )
    for q, a in turns:
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": a})
    return history


def maybe_update_session_summary(qa_session) -> bool:
    """滚动摘要：会话轮数超阈值且未摘要轮数达到一个批次时，把早期轮次压缩进摘要。

    时机：回答全文产出后执行（不阻塞正文显示）；失败静默保留旧摘要——
    摘要是增强项，不能拖垮问答主链路。
    """
    if qa_session is None:
        return False
    total = qa_session.records.exclude(answer="").count()
    pending = total - qa_session.summary_upto_turn
    if total <= QA_SUMMARY_TRIGGER_TURNS or pending < QA_SUMMARY_MIN_BATCH_TURNS:
        return False
    compress_to = total - QA_SUMMARY_KEEP_RECENT_TURNS  # 摘要覆盖到该轮次
    rows = list(
        qa_session.records.exclude(answer="")
        .filter(turn_index__gt=qa_session.summary_upto_turn, turn_index__lte=compress_to)
        .order_by("turn_index")
    )
    if not rows:
        return False
    lines = [f"问: {r.question[:300]}\n答: {(r.answer or '')[:300]}" for r in rows]
    prompt = (
        "你在维护一段师生问答对话的滚动摘要，供后续对话保持连贯。\n"
        "把「旧摘要 + 新增问答轮」压缩为不超过 400 字的新摘要。保留：学生问过的问题主题、"
        "助手给出的关键结论与定义、学生表现出的薄弱点、尚未解决的疑问。丢弃寒暄与重复。"
        "只输出新摘要本身。\n\n"
        f"旧摘要：{qa_session.summary or '（无）'}\n\n新增问答：\n" + "\n\n".join(lines)
    )
    try:
        provider = get_provider("chat")
        with ai_scene(AICallLog.Scene.QA_SUMMARY):
            summary = provider.chat(
                [{"role": "user", "content": prompt}],
                temperature=0,
                enable_thinking=False,
            )
    except Exception:
        return False
    summary = (summary or "").strip()
    if not summary:
        return False
    qa_session.summary = summary[:2000]
    qa_session.summary_upto_turn = compress_to
    qa_session.save(update_fields=["summary", "summary_upto_turn", "updated_at"])
    return True


def _prev_snapshot_fallback_units(prev_chunks, *, max_items: int = 3, token_budget: int = 800):
    """把上一轮 context_snapshot.chunks 的片段内容装配为「上一轮参考」注入单元。

    学生追问（"第五个详细讲讲"）经改写仍检索为空时，上一轮引用过的片段
    就是最可能的上下文来源——直接捞出内容注入，避免追问无根回答。
    返回 (units, cited)：与 _gather_course_context 相同的数据结构。
    """
    if not prev_chunks:
        return [], []
    from apps.knowledge.models import KnowledgeChunk

    ids = []
    for item in prev_chunks:
        cid = item.get("chunk_id")
        if cid and cid not in ids:
            ids.append(cid)
        if len(ids) >= max_items:
            break
    if not ids:
        return [], []
    by_id = {
        c.id: c
        for c in KnowledgeChunk.objects.filter(id__in=ids).select_related(
            "material", "material__catalog", "ppt", "ppt__catalog", "video", "video__catalog"
        )
    }
    units: list[str] = []
    cited: list[dict] = []
    used = 0
    for item in prev_chunks:
        chunk = by_id.get(item.get("chunk_id"))
        if chunk is None:
            continue
        n = len(units) + 1
        name = _chunk_display_name(chunk)
        header = _context_header(n, "prev", name, chunk.page)
        content = chunk.content[:_CONTEXT_UNIT_MAX_CHARS]
        cost = est_tokens(header) + est_tokens(content)
        if used + cost > token_budget:
            break
        units.append(f"{header}\n{content}")
        cited.append(
            {
                "n": n,
                "source": "prev",
                "chunk_id": chunk.id,
                "material_name": name,
                "page": chunk.page,
                "snippet": chunk.content[:120],
            }
        )
        used += cost
    return units, cited


def _apply_prev_snapshot_fallback(context, cited, snapshot: dict, prev_snapshot):
    """追问检索兜底：检索为空时用上一轮引用片段作「上一轮参考」。返回 (context, cited)。"""
    if cited or not prev_snapshot:
        return context, cited
    prev_units, prev_cited = _prev_snapshot_fallback_units(prev_snapshot)
    if not prev_units:
        return context, cited
    context = f"{context}\n\n" + "\n\n".join(prev_units) if context else "\n\n".join(prev_units)
    snapshot["fallback_used"] = True
    snapshot["chunks"] = [
        {k: item[k] for k in ("n", "chunk_id", "source", "page") if item.get(k) is not None}
        for item in prev_cited
    ]
    return context, prev_cited


def _qa_user_text(context: str, question: str, history) -> str:
    """构造问答 user 文本；带历史时附加「结合上文理解指代」提示。"""
    base = (
        "以下是与问题相关的课程资料片段（按相关度排序，编号供引用）：\n\n"
        f"{context}\n\n学生问题：{question}"
        if context
        else f"（本课程暂无可引用的课程资料）\n\n学生问题：{question}"
    )
    if history:
        base = (
            "（注意：下文附有本次对话的历史记录，学生的问题可能是在追问上文，"
            "请结合历史理解指代，如「它」「第五个」等。）\n\n" + base
        )
    return base


def _build_qa_messages(question, user_content, image_b64, history):
    """拼 QA messages：system + 多轮历史 + 当前问题（带图走多模态 content）。"""
    messages = [{"role": "system", "content": QA_SYSTEM_PROMPT}]
    messages += history or []
    messages.append({"role": "user", "content": _qa_user_content(user_content, image_b64)})
    return messages


def _degraded_history_chain(history: list[dict]) -> list[list[dict]]:
    """上下文超限的分级降级链（按序重试）：L1 丢旧一半 → L2 仅最近 2 轮 → L4 全丢。

    旧版超限一次丢光全部历史，多轮对话瞬间失忆；分级后超长会话先丢最旧的，
    尽量保住最近上下文。L3（仅摘要无原文轮）依赖会话摘要能力，随会话模型
    改造启用（设计文档 §6.4）。链内按长度去重（历史太短时 L1 与 L2 相同）。
    """
    if not history:
        return []
    pairs = len(history) // 2
    if pairs <= 2:
        return [[]]
    chain: list[list[dict]] = []
    for keep in (max(2, pairs // 2), 2, 0):
        candidate = history[-keep * 2 :] if keep else []
        if len(candidate) < len(history) and (not chain or len(candidate) < len(chain[-1])):
            chain.append(candidate)
    if not chain or chain[-1]:
        chain.append([])
    return chain


def _chat_with_history_fallback(provider, messages, history, **kwargs):
    """chat 并处理上下文超限：按 L1→L2→L4 分级降级重试（预算裁剪失手时）。

    返回 (answer, degraded_level)：0=未降级；1=丢旧一半；2=仅最近 2 轮；4=全丢。
    """
    from apps.ai.providers.base import token_limit_error_hint

    try:
        return provider.chat(messages, **kwargs), 0
    except Exception as exc:
        if not history or not token_limit_error_hint(str(exc)):
            raise
    for idx, degraded_history in enumerate(_degraded_history_chain(history), start=1):
        level = 4 if not degraded_history else idx
        retry = [messages[0], *degraded_history, messages[-1]]
        try:
            return provider.chat(retry, **kwargs), level
        except Exception as exc:
            if not token_limit_error_hint(str(exc)):
                raise
    # 所有降级级仍超限（极小概率：当前问题+RAG 本身就超窗口），异常自然上抛
    return provider.chat([messages[0], messages[-1]], **kwargs), 4


@scene_decorator(
    AICallLog.Scene.QA,
    course_getter=lambda args, kwargs: args[0] if args else kwargs.get("course_id"),
)
def knowledge_qa(
    course_id: int,
    question: str,
    catalog_id=None,
    image_b64: str | None = None,
    *,
    student_access: bool = False,
    classroom_ids=None,
    history: list[dict] | None = None,
    prev_snapshot=None,
) -> tuple[str, list[dict], str]:
    """非流式知识库问答（移动端用）。返回 (answer, cited, rewritten_question, snapshot)。

    rewritten_question 为改写后的检索问题（与原问题相同时为空串），仅供展示
    与审计，不改变学生看到的问题；snapshot 为上下文快照（含 degraded_level），
    供 QARecord 落库审计。prev_snapshot 为会话上一轮的 snapshot.chunks，
    当前检索为空时用作「上一轮参考」追问兜底。
    """
    provider = get_provider("chat")
    history = history or []
    # 多轮追问：先改写为可独立检索的问题（失败静默回退原问题）
    rewritten = rewrite_query_for_retrieval(question, history)
    if image_b64 and question.strip() == IMAGE_ONLY_DEFAULT_QUESTION:
        # 纯图片提问：默认文案检索无意义，跳过 RAG 直接走视觉理解
        context, cited = "", []
        snapshot = {"budgets": {}, "chunks": [], "degraded_level": 0}
    else:
        context, cited, snapshot = _gather_course_context(
            course_id,
            rewritten,
            catalog_id=catalog_id,
            student_access=student_access,
            classroom_ids=classroom_ids,
        )
        context, cited = _apply_prev_snapshot_fallback(context, cited, snapshot, prev_snapshot)
    user_content = _qa_user_text(context, question, history)
    messages = _build_qa_messages(question, user_content, image_b64, history)
    answer, level = _chat_with_history_fallback(provider, messages, history, **_QA_NO_THINKING)
    snapshot["degraded_level"] = level
    return answer, cited, (rewritten if rewritten != question else ""), snapshot


def _qa_user_content(text: str, image_b64: str | None):
    """构造问答 user 消息体；带图片时使用 OpenAI 多模态 content 结构。"""
    if not image_b64:
        return text
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": image_b64}},
    ]


# 学生 QA 用 enable_thinking=False 关闭思考模式：Qwen3 系列默认先输出
# reasoning_content（思考流）再出正文，实测简单问题首 token 也要 ~4.7s，
# 课程问答是封闭域检索回答，思考对质量无实质帮助、徒增延迟；其他 Provider
# （mock 等）不识别该参数，直接忽略无副作用。
_QA_NO_THINKING = {"enable_thinking": False}


@scene_decorator(
    AICallLog.Scene.QA,
    course_getter=lambda args, kwargs: args[0] if args else kwargs.get("course_id"),
)
def knowledge_qa_stream(
    course_id: int,
    question: str,
    catalog_id=None,
    image_b64: str | None = None,
    *,
    student_access: bool = False,
    classroom_ids=None,
    history: list[dict] | None = None,
    prev_snapshot=None,
):
    """知识库问答的流式版本（需求 S-K-01/02/04）。

    先产出一条 {"type":"meta","cited":[...],"rewritten_question":str} 事件
    （引用片段带编号 n 与来源 source；rewritten 为改写后的检索问题，与
    原问题相同时为空串），再逐段产出 {"type":"delta","text":"..."} 事件。
    资料来源除知识库片段外，也纳入课件 PPT 与讲解稿，避免生硬拒答。
    上下文超限时按 L1→L2→L4 分级丢弃部分历史重试（仅在未产出任何 delta
    时才重试，已产出内容的流无法干净重试），每级重试前产出一条
    {"type":"history_dropped","level":N} 事件告知前端。
    """
    provider = get_provider("chat")
    history = history or []
    # 多轮追问：先改写为可独立检索的问题（失败静默回退原问题）
    rewritten = rewrite_query_for_retrieval(question, history)
    if image_b64 and question.strip() == IMAGE_ONLY_DEFAULT_QUESTION:
        # 纯图片提问：默认文案检索无意义，跳过 RAG 直接走视觉理解
        context, cited = "", []
        snapshot = {"budgets": {}, "chunks": [], "degraded_level": 0}
    else:
        context, cited, snapshot = _gather_course_context(
            course_id,
            rewritten,
            catalog_id=catalog_id,
            student_access=student_access,
            classroom_ids=classroom_ids,
        )
        context, cited = _apply_prev_snapshot_fallback(context, cited, snapshot, prev_snapshot)
    yield {
        "type": "meta",
        "cited": cited,
        "rewritten_question": rewritten if rewritten != question else "",
        "snapshot": snapshot,
    }

    user_content = _qa_user_text(context, question, history)

    from apps.ai.providers.base import token_limit_error_hint

    chain = [history, *_degraded_history_chain(history)]
    produced = False
    last_exc: Exception | None = None
    for idx, level_history in enumerate(chain):
        messages = _build_qa_messages(question, user_content, image_b64, level_history)
        if idx > 0:
            level = 4 if not level_history else idx
            # snapshot 与 meta 事件同一对象引用：此处更新，调用方落库即为最终级别
            snapshot["degraded_level"] = level
            # 降级重试：先发事件让前端尽早提示（重试失败则由上层 error 事件收尾）
            yield {"type": "history_dropped", "level": level}
        try:
            for piece in provider.chat_stream(messages, **_QA_NO_THINKING):
                if piece:
                    produced = True
                    yield {"type": "delta", "text": piece}
            return
        except Exception as exc:
            last_exc = exc
            if produced or not token_limit_error_hint(str(exc)):
                raise
            # 未产出任何内容且是上下文超限：继续下一级降级
    if last_exc is not None:
        raise last_exc


# ---------------------------------------------------------------------------
# 章节题目生成（需求 T-Q-01）
# ---------------------------------------------------------------------------
@scene_decorator(
    AICallLog.Scene.QUESTION_GEN,
    course_getter=lambda args, kwargs: args[0] if args else kwargs.get("course_id"),
)
def generate_questions(course_id: int, catalog_id, count: int, qtype: str, objective: str = "") -> list[dict]:
    """基于章节 PPT + 知识库资料 + 教学目标生成题目（需求 T-Q-01 / 7.1）。"""
    provider = get_provider("chat")
    from apps.courses.models import Catalog, PPTResource
    from apps.knowledge.models import KnowledgeChunk

    parts: list[str] = []
    catalog_title = ""
    if catalog_id:
        cat = Catalog.objects.filter(id=catalog_id).first()
        catalog_title = cat.title if cat else ""
        ppt = (
            PPTResource.objects.filter(catalog_id=catalog_id, is_active=True)
            .order_by("-version")
            .first()
        )
        if ppt and ppt.parsed_pages:
            for pg in ppt.parsed_pages[:25]:
                seg = f"{pg.get('title', '')} {pg.get('body', '')}".strip()
                if seg:
                    parts.append(seg)

    # 知识库资料补充
    parts += [
        c for c in KnowledgeChunk.objects.filter(course_id=course_id).values_list("content", flat=True)[:5]
    ]
    context = "\n".join(p for p in parts if p).strip()

    qtype_hint = (
        "判断题 options 固定为 [{\"key\":\"A\",\"text\":\"正确\"},{\"key\":\"B\",\"text\":\"错误\"}]，answer={\"key\":\"A\"或\"B\"}；"
        "单选 answer={\"key\":\"X\"}；多选 answer={\"keys\":[...]}；"
        "填空 options=[]，answer={\"blanks\":[{\"text\":\"答案\",\"score\":2},...]}（每个空单独赋分，score 为该空分值）；"
        "简答 options=[]，answer={}。"
    )
    user_prompt = (
        f"请依据下面的课程内容出题。\n"
        f"章节：{catalog_title or '（未指定）'}\n"
        f"教学目标/出题要求：{objective or '覆盖本章核心知识点，难度适中'}\n"
        f"题型={qtype}，数量={count}。\n"
        f"严格只输出 JSON 数组（不要任何解释文字），每个元素含字段："
        f"qtype, stem, options([{{key,text}}]), answer, analysis, difficulty(easy/medium/hard), knowledge_tags(数组)。\n"
        f"{qtype_hint}\n\n"
        f"课程内容：\n{context[:3000] if context else '（暂无课件与资料，请基于该章节标题的常见知识点合理出题）'}"
    )
    messages = [
        {"role": "system", "content": "你是严谨的高校命题老师，只输出规范的 JSON，不输出多余文字。"},
        {"role": "user", "content": user_prompt},
    ]
    result = _safe_json(provider.chat(messages), default=[])
    return result if isinstance(result, list) else []


# ---------------------------------------------------------------------------
# 作业自动批改（二期，需求 T-H-04）—— 预留接口
# ---------------------------------------------------------------------------
@scene_decorator(AICallLog.Scene.GRADING)
def auto_grade_homework(content: str, reference: str, rubric: str) -> dict:
    provider = get_provider("chat")
    messages = [
        {"role": "system", "content": "你是作业批改助手，给出分数、评语、错误定位与修改建议。"},
        {"role": "user", "content": f"评分标准：{rubric}\n参考答案：{reference}\n学生作业：{content}"},
    ]
    return _safe_json(provider.chat(messages), default={"score": None, "comment": provider.chat(messages)})


# ---------------------------------------------------------------------------
# 班级学情分析（需求 T-L-04 延伸）：整体报告 + 逐学生简评
# ---------------------------------------------------------------------------
@scene_decorator(AICallLog.Scene.ANALYTICS)
def analyze_class_stats(stats: dict) -> dict:
    """基于班级学习统计数据生成 AI 学情分析。

    返回 {"overview": <markdown 报告>, "student_comments": [{"student_id", "comment"}]}。
    解析失败时兜底为 {"overview": 原始文本, "student_comments": []}。
    """
    from django.utils import timezone

    provider = get_provider("chat")
    now = timezone.now()
    summary = stats.get("summary", {})

    # 课程内容上下文：章节 / 作业 / 考试名称，让简评落到具体课程内容上
    from apps.courses.models import Catalog
    from apps.exams.models import Exam
    from apps.homework.models import Homework

    course_id = stats.get("course_id")
    chapters = list(
        Catalog.objects.filter(course_id=course_id, parent__isnull=True, is_published=True)
        .order_by("order", "id")
        .values_list("title", flat=True)
    )
    hw_titles = list(
        Homework.objects.filter(course_id=course_id, status="published")
        .order_by("id")
        .values_list("title", flat=True)
    )
    exam_names = list(
        Exam.objects.filter(course_id=course_id, status__in=["published", "finished"])
        .order_by("id")
        .values_list("name", flat=True)
    )

    students_brief = []
    for row in stats.get("students", []):
        last_active = row.get("last_active")
        inactive_days = (now - last_active).days if last_active else None
        students_brief.append({
            "student_id": row.get("student_id"),
            "姓名": row.get("name"),
            "练习正确率%": row.get("accuracy"),
            "练习题量": row.get("practice_total"),
            "作业提交": f"{row.get('homework_submitted')}/{row.get('homework_total')}",
            "缺交作业": row.get("homework_missing") or [],
            "考试参加": f"{row.get('exam_taken')}/{row.get('exam_total')}",
            "缺考考试": row.get("exam_missing") or [],
            "考试均分": row.get("avg_exam_score"),
            "未学习天数": inactive_days if inactive_days is not None else "从未",
            "预警": row.get("warnings") or [],
        })

    user_prompt = (
        "请根据以下班级学习统计数据生成学情分析。\n"
        "严格只输出 JSON（不要任何解释文字、不要 Markdown 代码块），格式：\n"
        '{"overview": "<markdown 报告>", "student_comments": [{"student_id": 数字, "comment": "..."}]}\n'
        "要求：\n"
        "1. overview 为 markdown 文本，含「## 整体学情」「## 需重点关注的学生」「## 教学建议」三个小节，"
        "总计 200~350 字，数据引用要准确，语言自然、像写给授课教师的周报。\n"
        "2. student_comments 覆盖每一名学生，comment 不超过 50 字。\n"
        "3. 简评是写给授课教师参考的，一律用第三人称描述该学生（如「该生」「其」），"
        "先概括表现、再给出教师可采取的行动建议（如「建议提醒其…」「可安排…」），"
        "严禁以对学生喊话的第二人称口吻（「你/加油/等着你」等）。\n"
        "4. 简评必须紧密结合本课程内容：建议要落到具体章节（用章节名称）或具体作业/考试（用其名称），"
        "缺交作业或缺考时直接点名对应任务名称；禁止「好好学习、巩固基础」这类放之四海皆准的空泛评语。\n"
        "5. student_id 必须与输入数据中的 student_id 完全一致。\n\n"
        f"课程：{stats.get('course_name')}　班级：{stats.get('class_name')}\n"
        f"课程章节：{json.dumps(chapters, ensure_ascii=False)}\n"
        f"课程作业：{json.dumps(hw_titles, ensure_ascii=False)}\n"
        f"课程考试：{json.dumps(exam_names, ensure_ascii=False)}\n"
        f"班级汇总：{json.dumps(summary, ensure_ascii=False)}\n"
        f"学生明细：{json.dumps(students_brief, ensure_ascii=False)}"
    )
    messages = [
        {"role": "system", "content": "你是高校教学质量分析助手，擅长从学习数据中提炼可执行的教学建议，只输出规范的 JSON。"},
        {"role": "user", "content": user_prompt},
    ]
    raw = provider.chat(messages)
    result = _safe_json(raw, default=None)
    if not isinstance(result, dict) or "overview" not in result:
        return {"overview": raw, "student_comments": []}
    if not isinstance(result.get("student_comments"), list):
        result["student_comments"] = []
    return result
