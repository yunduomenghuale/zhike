# -*- coding: utf-8 -*-
"""题库文档规则解析器：抽取文本 → 结构化题目草稿（需求 T-Q-01 导入链路）。

设计口径：
- 纯函数、无 IO：输入 extract_text_with_tables / extract_text 的文本，输出 drafts 列表；
  每条草稿带 _warnings（识别告警），预览编辑兜底人工修正——这是「只做规则解析」
  决策的落地逻辑（方案 §2.2）。
- 题型来源优先取段落标题（「一、单选题」），无标题时按结构推断
  （有选项→单选/多选、有空位→填空、其余→简答）。
- 输出契约与 grading.py / Question 模型对齐：
  single/judge: answer={"key": "A"}；multi: {"keys": [...]}；
  blank: {"blanks": [{"text": ...}]}（分值留空，由 save 管道按题分均分）；
  short: {"text": ...}。
- 选项标签归一：甲乙丙丁/①②③/(1)/a b c → A/B/C...，题干内引用与答案同步重映射。
- 常见试卷格式变体见 questions/tests.py::ImportParserTests（每题型 ≥3 变体）。
"""
from __future__ import annotations

import re

# 题型默认分值（预览期展示用，教师可改；填空题按空均分在 save 管道完成）
DEFAULT_SCORES = {"single": 2, "multi": 3, "judge": 2, "blank": 4, "short": 10}

# ---------------------------------------------------------------------------
# 正则储备
# ---------------------------------------------------------------------------

# 段落题型标题：「一、单选题」「（二）多项选择题」「第二部分 判断题」「四、填空题」。
# 前缀后必须紧跟题型词（防「一、请判断以下说法…」这类题干被误判为标题），
# 且整行不含句号（标题通常不带句号）。
_SECTION_PREFIX = r"(?:[一二三四五六七八九十百]+\s*[、.．:：]|[（(][一二三四五六七八九十百]+[）)]|第[一二三四五六七八九十百]+\s*(?:部分|章节|篇|卷))"
_SECTION_RE = re.compile(
    rf"^\s*{_SECTION_PREFIX}\s*"
    r"(?:单项选择题|多项选择|选择题|单选题|多选题|单选|多选|判断题|判断|填空题|填空|"
    r"简答题|简答|问答题|问答|论述题|名词解释|计算题|证明题)[^\n。]{0,20}$"
)
# 无序号裸标题：「单选题」「判断题（每题2分）」——整行只有题型词（可带括号说明）
_BARE_TYPE_RE = re.compile(
    r"^(单项选择题|单项选择|选择题|多选题|多项选择|单选题|单选|多选|判断题|判断|"
    r"填空题|填空|简答题|简答|问答题|问答|论述题|名词解释|计算题|证明题)题?"
    r"(?:\s*[（(][^）)]{0,20}[）)]?)?\s*$"
)
# 题型关键词 → qtype（顺序即优先级：多选必须先于单选/选择）
_TYPE_KEYWORDS = [
    ("multi", ("多选", "多项选择")),
    ("single", ("单选", "单项选择", "选择题")),
    ("judge", ("判断",)),
    ("blank", ("填空",)),
    ("short", ("简答", "问答", "论述", "名词", "计算", "证明", "编程", "程序", "简述")),
]

# 题号：「1.」「2、」「3．」「第4题」「(5)」「（6）」。
# 小数点防护只针对 `.`／`．`（排除 1.5 小数），且防护位在分隔符紧后——
# 「1. 1+1=?」这类数字开头题干必须放行；`、`/`:` 后接数字是正常题干，不防护。
_QNUM_RES = [
    re.compile(r"^\s*(\d{1,2})\s*(?:[.．](?!\d)|[、])\s*(\S.*)$"),
    re.compile(r"^\s*第?\s*(\d{1,2})\s*题\s*(?:[.．](?!\d)|[、:：])?\s*(\S.*)$"),
    re.compile(r"^\s*[（(](\d{1,2})[）)]\s*(\S.*)$"),
]
# 卷末答案速查行：「1.A」「2.AB」「3. A、B」——不作为题干并入
_ANSWER_SUMMARY_RE = re.compile(r"^\s*\d{1,2}\s*[.、．]?\s*[A-H](?:\s*[、,，]\s*[A-H])*\s*$")

# 行首选项：「A.」「B、」「C．」「D:」「E）」「(F)」「（G）」。
# ASCII 字母标签必须带标点分隔符（防题干里的「A 公司」被误判为选项）。
_OPT_RE = re.compile(
    r"^\s*(?:[（(](?P<paren>[A-Ha-hＡ-Ｈ])[）)]|(?P<bare>[A-Ha-hＡ-Ｈ])\s*[.、．:：)）])"
    r"\s*(?P<text>.*)$"
)
# 中文/圈号标签：「甲. 北京」「① 80」「乙、上海」——无标点（纯空白分隔）也认
_OPT_RE_CJK = re.compile(
    r"^\s*(?P<label>[甲乙丙丁戊己庚辛]|[①②③④⑤⑥⑦⑧])\s*[.、．:：)）]?\s*(?P<text>\S.*)$"
)
# 行内选项粘连（PDF 高发：「A.xxx B.xxx C.xxx」），要求 ≥2 处才切分
_INLINE_OPT_RE = re.compile(r"(?<![A-Za-z0-9])([A-Ha-h])\s*[.、．]")

# 答案/解析标记（长词优先，避免「答案与解析」被「答案」抢先）。
# 两种形态：①【答案】C —— 方括号包裹，冒号可省略（Word/PDF 极常见）；
#         ②答案：C / 参考答案：C —— 冒号必需（防题干里的「答案」二字被误切）。
_MARKER_RE = re.compile(
    r"【\s*(答案与解析|试题解析|答案解析|解析|参考答案|正确答案|答案)\s*】\s*[：:]?\s*"
    r"|【?\s*(答案与解析|试题解析|答案解析|解析|参考答案|正确答案|答案)\s*】?\s*[：:]"
)
# 「答案与解析」「试题解析」「答案解析」同时含答案与解析：答案与解析都入账，
# 否则简答/判断题只会拿到半截信息
_COMBINED_WORDS = ("答案与解析", "试题解析", "答案解析")
_ANALYSIS_WORDS = _COMBINED_WORDS + ("解析",)

# 填空空位：2+ 下划线（半/全角）或空括号
_BLANK_MARKER_RE = re.compile(r"_{2,}|＿{2,}|[（(]\s*[）)]")
# 题干尾部分值：「（2分）」「(3.5分)」
_SCORE_TAIL_RE = re.compile(r"[（(]\s*(\d+(?:\.\d+)?)\s*分\s*[）)]\s*$")
# 简答题分值说明（题干中部，「（共10分）」不摘，只摘尾部）
_SCORE_ANY_RE = re.compile(r"[（(]\s*(\d+(?:\.\d+)?)\s*分\s*[）)]")

# docx 表格行（extract_text_with_tables 产物，单元格以制表符连接）
_TABLE_HEADER_WORDS = {"题干", "题目", "题号", "题型", "选项", "答案", "正确答案", "解析", "分值", "分数", "难度", "知识点"}
_QNUM_CELL_RE = re.compile(r"\d{1,2}|第\s*\d{1,2}\s*题|[（(]\d{1,2}[）)]")
# 表格末列答案样式：裸值（A / 对 / √）或「答案：A」单元格
_ANSWER_CELL_RE = re.compile(r"[A-Ha-h]|对|错|正确|错误|√|×|[TtFf]|是|否")

_CN_LABELS = "甲乙丙丁戊己庚辛"
_NEW_KEYS = "ABCDEFGH"

# 中日韩字符与中文标点（跨行拼接头：两侧都是中文时不插空格）
_CJK_TAIL_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]$")
_CJK_HEAD_RE = re.compile(r"^[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


def _join_parts(parts) -> str:
    """拼接多行碎片：中文之间直接相连（跨行题干无感），中英之间补空格。"""
    out = ""
    for p in parts:
        p = (p or "").strip()
        if not p:
            continue
        if not out:
            out = p
        elif _CJK_TAIL_RE.search(out) and _CJK_HEAD_RE.match(p):
            out += p
        else:
            out += " " + p
    return out


# ---------------------------------------------------------------------------
# 段落级识别
# ---------------------------------------------------------------------------

def _match_section_type(line: str) -> str | None:
    """行是题型段落标题时返回 qtype，否则 None。"""
    stripped = line.strip()
    if not stripped or len(stripped) > 40:
        return None
    if not (_SECTION_RE.match(stripped) or _BARE_TYPE_RE.match(stripped)):
        return None
    for qtype, keywords in _TYPE_KEYWORDS:
        if any(k in stripped for k in keywords):
            return qtype
    return None


def _match_question_start(line: str) -> str | None:
    """行以题号开头时返回去掉题号的内容，否则 None。"""
    for pattern in _QNUM_RES:
        m = pattern.match(line)
        if m and len(m.group(2).strip()) >= 2:
            return m.group(2)
    return None


def _split_markers(line: str) -> tuple[str, list[tuple[str, str]]]:
    """把行内「答案：/解析：/答案与解析：」标记切出。

    返回 (剩余内容, [(kind, text)])，kind ∈ answer/analysis/both，按出现顺序。
    无标记时原样返回 (line, [])。
    """
    events = []
    for m in _MARKER_RE.finditer(line):
        word = m.group(1) or m.group(2)
        if word in _COMBINED_WORDS:
            kind = "both"
        elif word in _ANALYSIS_WORDS:
            kind = "analysis"
        else:
            kind = "answer"
        events.append((m.start(), m.end(), kind))
    if not events:
        return line, []
    content = line[: events[0][0]]
    parts = []
    for i, (_s, e, kind) in enumerate(events):
        end = events[i + 1][0] if i + 1 < len(events) else len(line)
        text = line[e:end].strip()
        if text:
            parts.append((kind, text))
    return content, parts


def _extract_inline_options(text: str) -> tuple[str, list[tuple[str, str]]]:
    """切分行内粘连选项：「题干 A.甲 B.乙 C.丙」→ ("题干", [("A","甲"),...])。

    仅当出现 ≥2 个行首选项标记时才切分，避免把题干里的「A.」误判为选项。
    """
    matches = list(_INLINE_OPT_RE.finditer(text))
    if len(matches) < 2:
        return text, []
    head = text[: matches[0].start()].strip()
    options = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        options.append((m.group(1).upper(), body))
    return head, options


def _match_option_line(line: str) -> tuple[str, str] | None:
    """整行是一个选项时返回 (原始标签, 内容)，否则 None。"""
    m = _OPT_RE.match(line)
    if m:
        return (m.group("paren") or m.group("bare")), m.group("text").strip()
    m = _OPT_RE_CJK.match(line)
    if m:
        return m.group("label"), m.group("text").strip()
    return None


def _table_cells(line: str) -> list[str]:
    return [c.strip() for c in line.split("\t") if c.strip()]


def _is_table_header_row(line: str) -> bool:
    """表格表头行（题干/选项/答案…）→ 跳过，不并入任何题目。"""
    if "\t" not in line:
        return False
    cells = _table_cells(line)
    if len(cells) < 3 or not all(len(c) <= 8 for c in cells):
        return False
    return any(c in _TABLE_HEADER_WORDS for c in cells)


def _table_row_head(line: str) -> str | None:
    """一题一行的表格题目行：「1\\t题干\\tA\\tB」→ 去掉题号列后的制表符串。

    首列是题号样式（纯数字/第N题/(N)）才认，避免把普通制表符文本当题目行。
    """
    if "\t" not in line:
        return None
    cells = _table_cells(line)
    if len(cells) < 3 or not _QNUM_CELL_RE.fullmatch(cells[0]):
        return None
    return "\t".join(cells[1:])


def _answer_cell_value(cell: str) -> str | None:
    """表格末列是答案样式时返回答案文本（支持「答案：A」单元格），否则 None。"""
    t = (cell or "").strip()
    m = re.fullmatch(r"(?:正确答案|答案)\s*[：:]\s*(.+)", t)
    if m:
        t = m.group(1).strip()
    return t if _ANSWER_CELL_RE.fullmatch(t) else None


# ---------------------------------------------------------------------------
# 选项与答案归一
# ---------------------------------------------------------------------------

def _normalize_options(raw_options: list[tuple[str, str]]) -> tuple[list[dict], dict]:
    """选项按出现顺序编号 A/B/C...，返回 (options, {原始标签: 新标签})。

    原始标签是 ASCII 字母时仍按顺序重排（文档偶尔乱序），保证 answer 重映射一致。
    """
    options: list[dict] = []
    mapping: dict[str, str] = {}
    for raw_label, text in raw_options:
        text = (text or "").strip()
        if not text:
            continue
        new_key = _NEW_KEYS[len(options)] if len(options) < len(_NEW_KEYS) else str(len(options))
        mapping[raw_label] = new_key
        options.append({"key": new_key, "text": text})
    return options, mapping


def _translate_labels(text: str, mapping: dict) -> str:
    """把答案文本里的原始选项标签替换为新标签（甲→A、①→B、(1)→C）。"""
    for raw, new in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        if not raw:
            continue
        if raw.isascii() and raw.isalpha():
            # 字母标签要求独立出现，避免误伤词内字母
            text = re.sub(rf"(?<![A-Za-z]){re.escape(raw)}(?![A-Za-z])", new, text, flags=re.IGNORECASE)
        else:
            text = text.replace(raw, new)
    return text


def _parse_choice_answer(text: str) -> list[str]:
    """从答案文本提取选项字母列表（ABC / A、B / 选A / A项）。"""
    return re.findall(r"[A-H]", text.upper())


def _parse_judge_answer(text: str) -> str | None:
    """判断题答案归一为 A（正确）/ B（错误）。"""
    t = text.replace(" ", "").replace("　", "")
    if not t:
        return None
    if re.search(r"(错误|不对|不正确|有误|误|否|错|×|✗|[FfXx])", t):
        return "B"
    if re.search(r"(正确|对|是|√|✓|[Tt])", t):
        return "A"
    m = re.search(r"[AB]", t.upper())
    return m.group(0) if m else None


def _split_blank_answers(text: str) -> list[str]:
    """填空答案按分隔符拆分，剥掉 ①/（1）/1. 前缀与「（2分）」分值注释。"""
    t = text.strip().strip("。.;；")
    if not t:
        return []
    # ①封装②继承（无分隔符粘连）按序号环切
    parts = [p for p in re.split(r"[;；,，、]+|\s{2,}|(?=[①②③④⑤⑥⑦⑧⑨⑩])", t) if p.strip()]
    cleaned = []
    for p in parts:
        p = re.sub(r"^\s*(?:[①②③④⑤⑥⑦⑧⑨⑩]|[（(]\d+[）)]|\d+\s*[.、．])\s*", "", p.strip())
        p = re.sub(r"[（(]\s*\d+(?:\.\d+)?\s*分\s*[）)]\s*$", "", p).strip()
        if p:
            cleaned.append(p)
    return cleaned


def _count_blank_markers(stem: str) -> int:
    return len(_BLANK_MARKER_RE.findall(stem or ""))


def _extract_score(stem: str) -> tuple[str, float | None]:
    """摘除题干尾部「（2分）」并返回分值。"""
    m = _SCORE_TAIL_RE.search(stem)
    if m:
        return stem[: m.start()].rstrip(), float(m.group(1))
    return stem, None


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def parse_questions(raw_text: str) -> list[dict]:
    """解析抽取文本为题目草稿列表。解析不出任何题目时返回 []。"""
    if not raw_text or not raw_text.strip():
        return []

    questions: list[dict] = []
    current: dict | None = None
    section: str | None = None

    def _finalize():
        nonlocal current
        if current is not None:
            draft = _build_draft(current)
            if draft is not None:
                questions.append(draft)
            current = None

    for raw_line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if _ANSWER_SUMMARY_RE.match(line):
            continue  # 卷末答案速查行（整行仅「序号 + 选项字母」，不作题干并入）
        if _is_table_header_row(line):
            continue  # 表格表头行

        # 表格题目行优先于标记切分（行内单元格可能含「答案：A」）
        row_head = _table_row_head(line)
        is_row = row_head is not None
        if is_row:
            content, marker_parts = line, []
        else:
            content, marker_parts = _split_markers(line)

        section_type = _match_section_type(content)
        if section_type:
            _finalize()
            section = section_type
            continue

        if current is None:
            head = _match_question_start(content)
            if head is None:
                if not is_row:
                    continue  # 卷首说明/标题等前导内容，跳过
                head = row_head
            current = _new_question(None if is_row else section, table_row=is_row)
            _absorb(current, head)
        else:
            start_head = _match_question_start(content)
            if start_head is not None:
                _finalize()
                current = _new_question(section)
                _absorb(current, start_head)
            elif is_row:
                _finalize()
                current = _new_question(None, table_row=True)
                _absorb(current, row_head)
            else:
                _absorb(current, content)

        for kind, text in marker_parts:
            if current is None:
                break
            if kind == "analysis":
                current["analysis_parts"].append(text)
                continue
            # answer / both：both 同时进答案解析，保留完整解析文本
            current["answer_raw"] = (current["answer_raw"] + " " + text).strip() if current["answer_raw"] else text
            if kind == "both":
                current["analysis_parts"].append(text)

    _finalize()
    return questions


def _new_question(section: str | None, table_row: bool = False) -> dict:
    return {
        "section": section,
        "stem_parts": [],
        "options": [],           # [(原始标签, 文本)]
        "answer_raw": "",
        "analysis_parts": [],
        "_table_row": table_row,  # 一题一行的表格题目行（题型按结构推断）
    }


def _absorb(q: dict, content: str) -> None:
    """把一行内容并入当前题目：切行内选项 / 识别整行选项 / 其余并入题干。"""
    content = content.strip()
    if not content or not re.search(r"\w", content):
        return  # 空行或纯符号行（「——」「（」等标记残留）

    head, inline_options = _extract_inline_options(content)
    if inline_options:
        if head:
            q["stem_parts"].append(head)
        q["options"].extend(inline_options)
        q["_last_opt"] = True
        return

    opt = _match_option_line(content)
    if opt and (q["stem_parts"] or q["options"]):
        q["options"].append(opt)
        q["_last_opt"] = True
        return

    # 表格行：首列题干、其余列选项（docx 表格抽取产物）。
    # 普通行要求章节为选择类；表格题目行（题号列起题）不限章节。
    min_cells = 2 if q.get("_table_row") else 3
    if "\t" in content and not q["options"] and (
        q["section"] in ("single", "multi") or q.get("_table_row")
    ):
        cells = _table_cells(content)
        if len(cells) >= min_cells:
            answer_cell = None
            if q.get("_table_row"):
                # 末列是答案样式（A / 对 / 「答案：A」）→ 摘出，余下按 题干+选项 处理
                ans = _answer_cell_value(cells[-1])
                if ans is not None:
                    answer_cell = ans
                    cells = cells[:-1]
            q["stem_parts"].append(cells[0])
            for i, cell in enumerate(cells[1:]):
                q["options"].append((_NEW_KEYS[i], cell))
            q["_table_options"] = True
            if answer_cell and not q["answer_raw"]:
                q["answer_raw"] = answer_cell
            return

    # 选项换行续接：选项已开始且上一行是选项 → 并入最后一个选项，避免污染题干
    if q["options"] and q.get("_last_opt"):
        label, text = q["options"][-1]
        q["options"][-1] = (label, _join_parts([text, content]))
        return

    q["_last_opt"] = False
    q["stem_parts"].append(content)


def _build_draft(q: dict) -> dict | None:
    """累积态 → 题目草稿；无法构成题目时返回 None（丢弃）。"""
    stem = _join_parts(q["stem_parts"])
    if not stem:
        return None

    warnings: list[str] = []
    stem, score = _extract_score(stem)
    if not stem:
        return None

    options, key_map = _normalize_options(q["options"])
    analysis = _join_parts(q["analysis_parts"])

    qtype = q["section"] or _infer_type(stem, options, q["answer_raw"])
    if q["section"] is None:
        warnings.append("未识别到题型标题，已按结构推断")

    # 单选但答案含多个选项字母 → 转多选（保证 qtype 与 answer 结构一致）
    if qtype == "single":
        letters = _parse_choice_answer(_translate_labels(q["answer_raw"], key_map))
        if len(letters) > 1:
            qtype = "multi"
            warnings.append("原题型为单选但答案含多个选项，已按多选题处理")

    answer = _build_answer(qtype, q["answer_raw"], key_map, options, stem, warnings)
    _validate_draft(qtype, stem, options, answer, warnings)

    if q.get("_table_options"):
        warnings.append("选项来自无标签表格列，已按顺序编号，请核对")

    return {
        "qtype": qtype,
        "stem": stem,
        "options": options,
        "answer": answer,
        "analysis": analysis,
        "score": score if score else DEFAULT_SCORES.get(qtype, 2),
        "difficulty": "medium",
        "knowledge_tags": [],
        "_warnings": warnings,
    }


def _infer_type(stem: str, options: list, answer_raw: str) -> str:
    if options:
        return "multi" if len(_parse_choice_answer(answer_raw)) > 1 else "single"
    if _count_blank_markers(stem) >= 1:
        return "blank"
    # 答案是「对/错/√/×」样式 → 判断题（表格行与无标题场景都受益）
    if re.fullmatch(r"\s*(对|错|正确|错误|√|×|[TtFf]|是|否)\s*", str(answer_raw or "")):
        return "judge"
    return "short"


def _build_answer(qtype, answer_raw, key_map, options, stem, warnings) -> dict:
    text = (answer_raw or "").strip()
    if not text:
        return {}

    if qtype == "multi":
        letters = _parse_choice_answer(_translate_labels(text, key_map))
        if len(letters) < 2:
            warnings.append("多选题答案不足两个选项，请核对")
        return {"keys": letters}

    if qtype == "single":
        letters = _parse_choice_answer(_translate_labels(text, key_map))
        if not letters:
            warnings.append("未能从答案中识别出选项字母，请核对")
            return {}
        return {"key": letters[0]}

    if qtype == "judge":
        key = _parse_judge_answer(_translate_labels(text, key_map))
        if key is None:
            warnings.append("未能识别判断答案（对/错），请核对")
            return {}
        return {"key": key}

    if qtype == "blank":
        blanks = _split_blank_answers(text)
        if not blanks:
            warnings.append("填空题未识别到答案内容，请核对")
            return {"blanks": []}
        return {"blanks": [{"text": b} for b in blanks]}

    # 简答题：参考答案原文
    return {"text": text}


def _validate_draft(qtype, stem, options, answer, warnings) -> None:
    if qtype in ("single", "multi"):
        if len(options) < 2:
            warnings.append(f"选项不足（识别到 {len(options)} 个），请核对")
        if not (answer.get("key") or answer.get("keys")):
            warnings.append("未识别到答案，请核对")
    elif qtype == "judge":
        if not answer.get("key"):
            warnings.append("未识别到答案，请核对")
    elif qtype == "blank":
        markers = _count_blank_markers(stem)
        blanks = (answer or {}).get("blanks") or []
        if markers == 0:
            warnings.append("未识别到填空空位，请核对")
        elif len(blanks) != markers:
            warnings.append(f"空位数（{markers}）与答案数（{len(blanks)}）不一致，请核对")
