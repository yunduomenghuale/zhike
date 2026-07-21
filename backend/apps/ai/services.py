"""业务侧 AI 能力封装（对齐需求第 7 节大模型应用场景）。

所有函数只依赖 provider 抽象与向量检索工具，业务视图调用这里的函数即可。
真实模型未配置时自动走 Mock，保证一期业务流程可跑通。
"""
from __future__ import annotations

import json
import re

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
def generate_catalog_from_plan(plan_text: str) -> list[dict]:
    provider = get_provider()
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
def generate_scripts_for_video(pages: list[dict]) -> list[dict]:
    provider = get_provider()
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
                "body": (page.get("body") or "")[:500],
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
                "8. 输出 JSON 数组，元素格式为 {\"page\":页码,\"script\":\"讲解稿\"}。\n\n"
                f"PPT 页面：\n{json.dumps(compact_pages, ensure_ascii=False)}"
            ),
        },
    ]

    try:
        result = _safe_json(
            provider.chat(messages, temperature=0.4, timeout=timeout, retries=3, enable_thinking=False),
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
    body = (page.get("body") or "").strip()
    if _is_course_intro_page(title, body):
        return {"page": page.get("page"), "script": _polish_script_text(_script_for_course_intro(body))}
    if _is_chapter_cover_page(title, body):
        return {"page": page.get("page"), "script": _polish_script_text(_script_for_chapter_cover(title))}

    points = _extract_page_points(body)
    section_title = _extract_section_title(body)
    if points:
        lead = _topic_lead(title, section_title)
        point_text = "；".join(_explain_point(point) for point in points[:6])
        script = f"{lead}{point_text}。学习时先把这些要点按顺序串起来，再回到具体例子中理解它们各自解决的问题。"
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
    return text.lstrip("，,。；;：: ")


# ---------------------------------------------------------------------------
# 逐页 AI 配音（需求 T-V-03）：对讲解稿合成语音，落地音频地址
# ---------------------------------------------------------------------------
def synthesize_audio_for_video(video, voice: str = "Cherry") -> int:
    """为教学视频的逐页讲解稿补齐配音，音频地址写回 scripts 每页。返回本次新增成功页数。"""
    provider = get_provider()
    scripts = video.scripts or []
    ok = 0
    for item in scripts:
        if item.get("audio_url"):
            item.pop("audio_error", None)
            continue
        text = (item.get("script") or "").strip()
        if not text:
            continue
        try:
            item["audio_url"] = provider.tts(text, voice=voice)
            item.pop("audio_error", None)
            ok += 1
        except Exception as exc:
            item["audio_error"] = str(exc)[:300]
    video.scripts = scripts
    audio_count = sum(1 for item in scripts if item.get("audio_url"))
    video.gen_status = (
        video.GenStatus.AUDIO_READY
        if audio_count == len([item for item in scripts if item.get("script")])
        else video.GenStatus.SCRIPT_READY
    )
    video.save(update_fields=["scripts", "gen_status", "updated_at"])
    return ok


# ---------------------------------------------------------------------------
# 教辅资料入库：切分 -> 向量化 -> 写入片段（需求 T-K-02 / 7.2）
# ---------------------------------------------------------------------------
def ingest_material(material, chunk_size: int = 500) -> int:
    """把资料文本抽取→切分→向量化→写入知识库片段。返回片段数。

    文本抽取按文件类型（TXT/PDF/Word/PPT）自动进行；抽取为空时标记解析失败。
    """
    from apps.knowledge.extractor import extract_text
    from apps.knowledge.models import KnowledgeChunk

    provider = get_provider()
    file_path = material.file.path if material.file else ""
    raw_text = (getattr(material, "_extracted_text", "") or extract_text(file_path)).strip()

    if not raw_text:
        material.parse_status = material.ParseStatus.FAILED
        material.save(update_fields=["parse_status", "updated_at"])
        return 0

    pieces = [raw_text[i : i + chunk_size] for i in range(0, len(raw_text), chunk_size)] or [raw_text]

    embeddings = provider.embed(pieces)
    material.chunks.all().delete()
    objs = [
        KnowledgeChunk(
            material=material,
            course_id=material.course_id,
            content=piece,
            embedding=emb,
        )
        for piece, emb in zip(pieces, embeddings)
    ]
    KnowledgeChunk.objects.bulk_create(objs)

    material.parse_status = material.ParseStatus.DONE
    material.save(update_fields=["parse_status", "updated_at"])
    return len(objs)


# ---------------------------------------------------------------------------
# 知识库问答（需求 S-K-01/02/04）
# ---------------------------------------------------------------------------
QA_SYSTEM_PROMPT = (
    "你是课程 AI 助教，语气自然、友好、有条理。"
    "请优先依据下面提供的「课程资料」（课件 PPT、讲解稿、知识库片段）回答学生的问题，答案要简明、分点清晰。"
    "如果课程资料里没有相关内容，可以结合你的通识知识作答，但要提醒学生这部分未在本课程资料中出现。"
    "如果学生的问题或图片与本课程明显无关，不要展开详细解答，只需简要说明它与本课程无关，"
    "并友好地引导学生围绕本课程内容提问。"
    "遇到寒暄、问候或与课程无关的闲聊，友好、简短地回应即可，不要生硬地拒答。"
)


def _gather_course_context(
    course_id, question: str, catalog_id=None, max_chars: int = 6000
) -> tuple[str, list[dict]]:
    """汇总某课程可用于问答的资料上下文（需求 S-K-01/02）。

    资料来源（按优先级）：知识库检索片段 → 课件 PPT 讲义 → 逐页讲解稿。
    把 PPT / 讲解稿也当作「资料」，避免知识库为空时一律拒答。
    传入 catalog_id 时优先取该章节的课件与讲稿。返回 (context, cited)。
    """
    from apps.courses.models import PPTResource, TeachingVideo

    provider = get_provider()
    parts: list[str] = []
    cited: list[dict] = []

    # 1) 知识库向量检索（若有片段）
    try:
        query_vec = provider.embed([question])[0]
        for chunk, score in search_chunks(course_id, query_vec, top_k=5):
            if score <= 0:
                continue
            parts.append(chunk.content)
            cited.append(
                {
                    "chunk_id": chunk.id,
                    "material_name": chunk.material.file_name,
                    "page": chunk.page,
                    "snippet": chunk.content[:120],
                    "score": round(score, 4),
                }
            )
    except Exception:
        pass

    # 2) 课件 PPT 讲义（把 PPT 当资料）
    ppt_qs = PPTResource.objects.filter(course_id=course_id, is_active=True)
    if catalog_id:
        ppt_qs = ppt_qs.filter(catalog_id=catalog_id)
    seen_catalogs: set = set()
    for ppt in ppt_qs.order_by("catalog_id", "-version"):
        if ppt.catalog_id in seen_catalogs:  # 每个章节只取最新启用版本
            continue
        seen_catalogs.add(ppt.catalog_id)
        page_segs = []
        for pg in (ppt.parsed_pages or [])[:40]:
            seg = f"{pg.get('title', '')} {pg.get('body', '')}".strip()
            if seg:
                page_segs.append(seg)
        if page_segs:
            parts.extend(page_segs)
            cited.append(
                {
                    "material_name": ppt.file_name or "课程课件",
                    "page": None,
                    "snippet": page_segs[0][:120],
                }
            )

    # 3) 逐页讲解稿（自然语言，最贴近讲课内容）
    vid_qs = TeachingVideo.objects.filter(course_id=course_id)
    if catalog_id:
        vid_qs = vid_qs.filter(catalog_id=catalog_id)
    for vid in vid_qs:
        for s in (vid.scripts or []):
            t = (s.get("script") or "").strip()
            if t:
                parts.append(t)

    context = "\n---\n".join(p for p in parts if p)[:max_chars]
    return context, cited


def knowledge_qa(course_id: int, question: str, catalog_id=None, image_b64: str | None = None) -> tuple[str, list[dict]]:
    provider = get_provider()
    context, cited = _gather_course_context(course_id, question, catalog_id=catalog_id)
    user_content = (
        f"课程资料：\n{context}\n\n学生问题：{question}"
        if context
        else f"（本课程暂无可引用的课程资料）\n\n学生问题：{question}"
    )
    messages = [
        {"role": "system", "content": QA_SYSTEM_PROMPT},
        {"role": "user", "content": _qa_user_content(user_content, image_b64)},
    ]
    return provider.chat(messages), cited


def _qa_user_content(text: str, image_b64: str | None):
    """构造问答 user 消息体；带图片时使用 OpenAI 多模态 content 结构。"""
    if not image_b64:
        return text
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": image_b64}},
    ]


def knowledge_qa_stream(course_id: int, question: str, catalog_id=None, image_b64: str | None = None):
    """知识库问答的流式版本（需求 S-K-01/02/04）。

    先产出一条 {"type":"meta","cited":[...]} 事件（引用片段），
    再逐段产出 {"type":"delta","text":"..."} 事件（回答文本）。
    资料来源除知识库片段外，也纳入课件 PPT 与讲解稿，避免生硬拒答。
    """
    provider = get_provider()
    context, cited = _gather_course_context(course_id, question, catalog_id=catalog_id)
    yield {"type": "meta", "cited": cited}

    user_content = (
        f"课程资料：\n{context}\n\n学生问题：{question}"
        if context
        else f"（本课程暂无可引用的课程资料）\n\n学生问题：{question}"
    )
    messages = [
        {"role": "system", "content": QA_SYSTEM_PROMPT},
        {"role": "user", "content": _qa_user_content(user_content, image_b64)},
    ]
    for piece in provider.chat_stream(messages):
        if piece:
            yield {"type": "delta", "text": piece}


# ---------------------------------------------------------------------------
# 章节题目生成（需求 T-Q-01）
# ---------------------------------------------------------------------------
def generate_questions(course_id: int, catalog_id, count: int, qtype: str, objective: str = "") -> list[dict]:
    """基于章节 PPT + 知识库资料 + 教学目标生成题目（需求 T-Q-01 / 7.1）。"""
    provider = get_provider()
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
        "单选 answer={\"key\":\"X\"}；多选 answer={\"keys\":[...]}；填空 options=[]，answer={\"blanks\":[...]}；"
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
def auto_grade_homework(content: str, reference: str, rubric: str) -> dict:
    provider = get_provider()
    messages = [
        {"role": "system", "content": "你是作业批改助手，给出分数、评语、错误定位与修改建议。"},
        {"role": "user", "content": f"评分标准：{rubric}\n参考答案：{reference}\n学生作业：{content}"},
    ]
    return _safe_json(provider.chat(messages), default={"score": None, "comment": provider.chat(messages)})


# ---------------------------------------------------------------------------
# 班级学情分析（需求 T-L-04 延伸）：整体报告 + 逐学生简评
# ---------------------------------------------------------------------------
def analyze_class_stats(stats: dict) -> dict:
    """基于班级学习统计数据生成 AI 学情分析。

    返回 {"overview": <markdown 报告>, "student_comments": [{"student_id", "comment"}]}。
    解析失败时兜底为 {"overview": 原始文本, "student_comments": []}。
    """
    from django.utils import timezone

    provider = get_provider()
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
