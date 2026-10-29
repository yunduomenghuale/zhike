"""三类批量导入（班级 / 教师 / 学生）的统一管道。

设计要点（见方案 §3）：

1. **一套管道三类复用**：模板生成 → 解析 → 逐行校验（预览与提交共用同一份逻辑）
   → 单事务写入。差别只在 `ImportSpec` 的列定义、校验器与写入器。
2. **提交时不信任前端**：commit 会用服务端校验结果重算一遍，前端传来的
   `row_status` 一律丢弃。
3. **自动建班必须确认**：编码不存在时只在预览页列为「待建班级」，
   管理员勾选（`approved_classes`）后才真建；未被勾选的编码下学生行转 error。
4. **空班不创建**：某编码下合法学生数为 0 时该班不进入提交（方案 X-33）。
5. **编码先归一**：`strip().upper()` 后再比较与落库（方案 X-32），归一写在
   `ClassRoom.save()` 与这里的 `normalize_code()` 两处，任何入口都绕不过去。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO

from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from apps.classroom.models import ClassRoom, ClassStudent
from apps.classroom.services import ClassServiceError, assign_students
from apps.users.models import User

from .user_import import MIN_USERNAME_LENGTH, initial_password_for

KIND_CLASS = "class"
KIND_TEACHER = "teacher"
KIND_STUDENT = "student"

MAX_FILE_SIZE = 5 * 1024 * 1024
CODE_PATTERN = re.compile(r"^[A-Z0-9-]{3,32}$")
ALLOWED_DURATIONS = (2, 3, 4, 5)
DEFAULT_DURATION = 4
MIN_YEAR, MAX_YEAR = 2000, 2100

# 占用中/可入班的班级状态（其余状态视为不可再分配学生）
JOINABLE_CLASS_STATUSES = (ClassRoom.Status.PREPARING, ClassRoom.Status.ACTIVE)


class ImportFileError(ValueError):
    """文件级错误（表头缺列、格式不对、超行数）——直接 400，不做逐行预览。"""


class ImportValidationError(Exception):
    """提交时仍有错误行（且未开启 skip_invalid）。携带逐行结果供前端回显。"""

    def __init__(self, message: str, rows: list[dict]):
        super().__init__(message)
        self.message = message
        self.rows = rows


def normalize_code(value) -> str:
    return str(value or "").strip().upper()


# ---------------------------------------------------------------------------
# 列定义
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Column:
    header: str
    required: bool = False
    width: int = 16
    note: str = ""


@dataclass(frozen=True)
class ImportSpec:
    kind: str
    title: str
    sheet_name: str
    columns: tuple[Column, ...]
    max_rows: int
    tips: tuple[str, ...] = field(default_factory=tuple)

    @property
    def headers(self) -> list[str]:
        return [col.header for col in self.columns]


CLASS_SPEC = ImportSpec(
    kind=KIND_CLASS,
    title="班级批量导入",
    sheet_name="班级导入",
    max_rows=200,
    columns=(
        Column("班级编码", True, 18, "3–32 位，字母/数字/短横线；系统内唯一（不区分大小写）"),
        Column("班级名称", True, 22, "如 计算机2401班；编码已存在时不会覆盖"),
        Column("入学年", True, 10, "2000–2100，如 2026"),
        Column("学制", True, 8, "3 / 4 / 5（允许 2）"),
        Column("状态", False, 12, "空=在读；可填 筹备中/在读"),
    ),
    tips=(
        "1. 请在「班级导入」页从第 2 行开始填写，每行一个班级，表头请勿修改。",
        "2. 班级编码是学生导入时的匹配键，建好后不要随意修改。",
        "3. 编码已存在时该行标记为「已跳过」，不会覆盖已有班级的学制/届别。",
        "4. 学制用于计算预计毕业年份（入学年 + 学制）。",
        "5. 状态留空按「在读」处理；提前建班、暂不公开时填「筹备中」。",
    ),
)

TEACHER_SPEC = ImportSpec(
    kind=KIND_TEACHER,
    title="教师账号批量导入",
    sheet_name="教师导入",
    max_rows=500,
    columns=(
        Column("工号", True, 22, "教师登录账号，6 位以上，平台内唯一"),
        Column("姓名", True, 18, "用于名单与成绩展示"),
    ),
    tips=(
        "1. 请在「教师导入」页从第 2 行开始填写，每行一位教师，表头请勿修改。",
        "2. 工号即登录账号，6 位以上，平台内不可重复（不区分大小写）。",
        "3. 初始密码规则：Zk + 工号后 6 位（不足 6 位取整个工号）。",
        "4. 教师首次登录后系统会提示修改密码。",
    ),
)

STUDENT_SPEC = ImportSpec(
    kind=KIND_STUDENT,
    title="学生账号批量导入",
    sheet_name="学生导入",
    max_rows=500,
    columns=(
        Column("学号", True, 22, "学生登录账号，6 位以上，平台内唯一"),
        Column("姓名", True, 18, "必填，入班前要求填写姓名"),
        Column("班级编码", False, 16, "填了才入班；系统里没有该编码时可自动建班"),
        Column("班级名称", False, 22, "自动建班时用作班名；留空则用编码兜底"),
        Column("入学年", False, 10, "自动建班时用；留空取向导里的默认值"),
    ),
    tips=(
        "1. 请在「学生导入」页从第 2 行开始填写，每行一名学生，表头请勿修改。",
        "2. 学号即登录账号，6 位以上，平台内不可重复（不区分大小写）。",
        "3. 初始密码规则：Zk + 学号后 6 位（不足 6 位取整个学号）。",
        "4. 「班级编码」留空则只建账号不入班；填了但系统里没有该编码时，"
        "预览页会列出待建班级，确认后自动建班并把学生放进去。",
        "5. 一名学生只能在一个班（单班制），已在其他班的学生会报冲突。",
    ),
)

SPECS = {spec.kind: spec for spec in (CLASS_SPEC, TEACHER_SPEC, STUDENT_SPEC)}


def get_spec(kind: str) -> ImportSpec:
    spec = SPECS.get(kind)
    if spec is None:
        raise ImportFileError(f"未知的导入类型：{kind}")
    return spec


# ---------------------------------------------------------------------------
# 模板生成
# ---------------------------------------------------------------------------
_HEADER_FILL = PatternFill("solid", fgColor="EFF6FF")
_HEADER_FONT = Font(bold=True, color="1D4ED8")


def build_template(kind: str) -> bytes:
    spec = get_spec(kind)
    wb = Workbook()
    ws = wb.active
    ws.title = spec.sheet_name
    ws.append(spec.headers)
    for idx, col in enumerate(spec.columns, start=1):
        cell = ws.cell(row=1, column=idx)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[cell.column_letter].width = col.width
        if not col.required:
            cell.value = f"{col.header}"
    ws.freeze_panes = "A2"

    # 必填列在表头加 *，方便填写人一眼看出
    for idx, col in enumerate(spec.columns, start=1):
        if col.required:
            ws.cell(row=1, column=idx).value = f"{col.header} *"
    tips = wb.create_sheet("填写说明")
    tips.append([f"{spec.title}说明"])
    tips["A1"].font = Font(bold=True, size=13)
    for line in spec.tips:
        tips.append([line])
    tips.append([""])
    tips.append(["列说明："])
    for col in spec.columns:
        required = "必填" if col.required else "选填"
        tips.append([f"· {col.header}（{required}）：{col.note}"])
    tips.column_dimensions["A"].width = 96
    for row in tips.iter_rows(min_row=1, max_row=tips.max_row, max_col=1):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def _cell_text(row, index: int) -> str:
    """单元格统一转字符串：数字学号按整数处理，避免 2024010101.0 这类尾巴。"""
    if index >= len(row):
        return ""
    value = row[index]
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _cell_int(row, index: int):
    """可空整数列：空返回 None，非整数抛 ValueError。"""
    text = _cell_text(row, index)
    if not text:
        return None
    if re.fullmatch(r"\d+(\.0+)?", text):
        return int(float(text))
    raise ValueError(text)


def parse_excel(file_obj, kind: str) -> list[dict]:
    """按 spec 读列，返回 [{row_no, <字段名...>}]；文件级错误抛 ImportFileError。"""
    spec = get_spec(kind)
    try:
        workbook = load_workbook(file_obj, read_only=True, data_only=True)
    except Exception:
        raise ImportFileError("文件无法解析，请上传 .xlsx 格式的模板文件")
    sheet = workbook.worksheets[0]
    raw_rows = list(sheet.iter_rows(values_only=True))
    workbook.close()
    if not raw_rows:
        raise ImportFileError("Excel 内容为空")

    header = [str(cell).strip().rstrip("* ").strip() if cell is not None else "" for cell in raw_rows[0]]
    missing = [col.header for col in spec.columns if col.required and col.header not in header]
    if missing:
        raise ImportFileError(
            f"表头缺少必填列：{'、'.join(missing)}；请下载系统模板填写"
        )

    index_of = {col.header: (header.index(col.header) if col.header in header else None)
                for col in spec.columns}

    parsed: list[dict] = []
    for row_no, row in enumerate(raw_rows[1:], start=2):
        values, blank = {}, True
        for col in spec.columns:
            idx = index_of[col.header]
            if idx is None:
                values[col.header] = ""
                continue
            text = _cell_text(row, idx)
            if text:
                blank = False
            values[col.header] = text
        if blank:
            continue
        # 数值列单独解析：解析失败保留原文，由逐行校验给出可读提示
        for col in spec.columns:
            if col.header not in ("入学年", "学制"):
                continue
            idx = index_of[col.header]
            if idx is None:
                values[col.header] = None
                continue
            try:
                values[col.header] = _cell_int(row, idx)
            except ValueError:
                values[col.header] = values[col.header]
        parsed.append({"row_no": row_no, **{_field_of(kind, h): v for h, v in values.items()}})

    if not parsed:
        raise ImportFileError("未读取到有效数据行，请从第 2 行开始填写")
    if len(parsed) > spec.max_rows:
        raise ImportFileError(f"单次最多导入 {spec.max_rows} 行，请拆分文件")
    return parsed


def _field_of(kind: str, header: str) -> str:
    mapping = {
        KIND_CLASS: {"班级编码": "code", "班级名称": "name", "入学年": "enrollment_year",
                     "学制": "duration_years", "状态": "status"},
        KIND_TEACHER: {"工号": "username", "姓名": "real_name"},
        KIND_STUDENT: {"学号": "username", "姓名": "real_name", "班级编码": "class_code",
                       "班级名称": "class_name", "入学年": "enrollment_year"},
    }[kind]
    return mapping.get(header, header)


# ---------------------------------------------------------------------------
# 逐行校验（预览与提交共用）
# ---------------------------------------------------------------------------
def _username_error(username: str, real_name: str) -> str:
    if not username:
        return "用户名不能为空"
    if len(username) < MIN_USERNAME_LENGTH:
        return f"用户名至少 {MIN_USERNAME_LENGTH} 位（用于生成初始密码）"
    if len(username) > 150:
        return "用户名过长"
    if any(ch.isspace() for ch in username):
        return "用户名不能包含空格"
    if not real_name:
        return "姓名不能为空"
    if len(real_name) > 64:
        return "姓名过长"
    return ""


def _existing_usernames(lowered: list[str]) -> set[str]:
    from django.db.models.functions import Lower

    if not lowered:
        return set()
    return set(
        User.objects.annotate(lower_username=Lower("username"))
        .filter(lower_username__in=lowered)
        .values_list("lower_username", flat=True)
    )


def _existing_user_map(lowered: list[str]) -> dict:
    """用户名（小写）→ User，用于给出「已在哪个班」这种可操作提示。

    只查一次用户名集合，再单独查一次占位关系，避免每行一次 query。
    """
    from django.db.models.functions import Lower

    if not lowered:
        return {}
    rows = User.objects.annotate(lower_username=Lower("username")).filter(
        lower_username__in=lowered
    )
    return {row.lower_username: row for row in rows}


def _occupied_class_names(users) -> dict[int, str]:
    """user_id → 当前所在班级名。学生重复导入时用它说明「为什么这条过不了」。"""
    ids = [u.id for u in users]
    if not ids:
        return {}
    links = (
        ClassStudent.objects.filter(student_id__in=ids,
                                    learn_status__in=ClassStudent.OCCUPYING_STATUSES)
        .select_related("classroom")
        .order_by("id")
    )
    return {link.student_id: link.classroom.name for link in links}


def _mark(rows: list[dict]) -> list[dict]:
    """补齐 row_status / message 字段，保证前端拿到的结构一致。"""
    for row in rows:
        row.setdefault("row_status", "ok")
        row.setdefault("message", "")
    return rows


def annotate_rows(kind: str, rows: list[dict], options: dict | None = None) -> dict:
    """逐行校验。返回 {rows, summary, pending_classes}。

    - `row_status`：ok / error / skipped
    - 学生导入会额外产出 `pending_classes`（编码不存在、待管理员确认新建的班）
    """
    options = options or {}
    spec = get_spec(kind)
    annotate = {KIND_CLASS: _annotate_class, KIND_TEACHER: _annotate_teacher,
                KIND_STUDENT: _annotate_student}[kind]
    result = annotate(rows, options)
    result["rows"] = _mark(result["rows"][: spec.max_rows])
    result["summary"] = _summarize(result["rows"], result.get("pending_classes") or [])
    return result


def _summarize(rows: list[dict], pending_classes: list[dict]) -> dict:
    return {
        "total": len(rows),
        "ok": sum(1 for r in rows if r["row_status"] == "ok"),
        "error": sum(1 for r in rows if r["row_status"] == "error"),
        "skipped": sum(1 for r in rows if r["row_status"] == "skipped"),
        "pending_class_count": len(pending_classes),
        "pending_student_count": sum(int(c.get("student_count") or 0) for c in pending_classes),
    }


def _annotate_class(rows: list[dict], options: dict) -> dict:
    normalized = []
    for index, raw in enumerate(rows, start=1):
        normalized.append({
            "row_no": raw.get("row_no") or index,
            "code": normalize_code(raw.get("code")),
            "name": str(raw.get("name") or "").strip(),
            "enrollment_year": raw.get("enrollment_year"),
            "duration_years": raw.get("duration_years"),
            "status": str(raw.get("status") or "").strip(),
        })

    codes = [r["code"] for r in normalized if r["code"]]
    existing = {
        row.code: row
        for row in ClassRoom.objects.filter(code__in=codes)
    } if codes else {}

    seen: set[str] = set()
    out = []
    for row in normalized:
        code, name = row["code"], row["name"]
        message, status = "", "ok"

        if not code:
            status, message = "error", "班级编码不能为空"
        elif not CODE_PATTERN.match(code):
            status, message = "error", "班级编码只能是 3–32 位字母、数字或短横线"
        elif code in existing:
            status, message = "skipped", "编码已存在，未修改"
        elif code in seen:
            status, message = "skipped", "与表内其他行编码重复，已忽略"
        elif not name:
            status, message = "error", "班级名称不能为空"
        elif len(name) > 200:
            status, message = "error", "班级名称过长"
        else:
            year, duration = row["enrollment_year"], row["duration_years"]
            if not isinstance(year, int) or not (MIN_YEAR <= year <= MAX_YEAR):
                status, message = "error", f"入学年需为 {MIN_YEAR}–{MAX_YEAR} 的整数"
            elif not isinstance(duration, int) or duration not in ALLOWED_DURATIONS:
                status, message = "error", "学制只能是 2 / 3 / 4 / 5"
            elif year + duration > MAX_YEAR:
                status, message = "error", "入学年 + 学制超出合理范围"
            elif row["status"] and row["status"] not in ("筹备中", "在读", "preparing", "active"):
                status, message = "error", "状态只能填 筹备中 / 在读（或留空）"

        if code:
            seen.add(code)
        out.append({
            **row,
            "status": _class_status_value(row["status"]),
            "row_status": status,
            "message": message,
        })

    # 表头为「状态」列，前端展示中文
    for row in out:
        row["status_display"] = dict(ClassRoom.Status.choices).get(row["status"], row["status"])
    return {"rows": out, "pending_classes": []}


def _class_status_value(text: str) -> str:
    text = (text or "").strip()
    mapping = {"筹备中": ClassRoom.Status.PREPARING, "在读": ClassRoom.Status.ACTIVE,
               "preparing": ClassRoom.Status.PREPARING, "active": ClassRoom.Status.ACTIVE,
               "已毕业": ClassRoom.Status.GRADUATED, "graduated": ClassRoom.Status.GRADUATED,
               "已归档": ClassRoom.Status.ARCHIVED, "archived": ClassRoom.Status.ARCHIVED}
    return mapping.get(text, ClassRoom.Status.ACTIVE)


def _annotate_teacher(rows: list[dict], options: dict) -> dict:
    normalized = [{
        "row_no": raw.get("row_no") or index,
        "username": str(raw.get("username") or "").strip(),
        "real_name": str(raw.get("real_name") or "").strip(),
    } for index, raw in enumerate(rows, start=1)]

    existing = _existing_usernames([r["username"].lower() for r in normalized if r["username"]])
    seen, dup = set(), set()
    for row in normalized:
        key = row["username"].lower()
        if key:
            if key in seen:
                dup.add(key)
            seen.add(key)

    out = []
    for row in normalized:
        message, status = _username_error(row["username"], row["real_name"]), "ok"
        if message:
            status = "error"
        elif row["username"].lower() in dup:
            message, status = "与表内其他行工号重复", "error"
        elif row["username"].lower() in existing:
            # 已存在不算错：同一份名单重复上传应当整体幂等（方案 P2 准出 7）
            message, status = "工号已存在，未修改", "skipped"
        out.append({
            **row,
            "initial_password": initial_password_for(row["username"]) if row["username"] else "",
            "row_status": status,
            "message": message,
        })
    return {"rows": out, "pending_classes": []}


def _annotate_student(rows: list[dict], options: dict) -> dict:
    create_missing = bool(options.get("create_missing_classes", True))
    approved = {normalize_code(code) for code in (options.get("approved_classes") or [])}
    # 预览阶段不要求勾选（要先把清单展示出来）；提交阶段要求逐个确认，
    # 否则「编码打错一个字就造出空壳班」的口子就开了（方案 §3.4）。
    require_approval = bool(options.get("require_approval", False))
    default_year = options.get("default_enrollment_year")
    default_duration = options.get("default_duration_years") or DEFAULT_DURATION

    normalized = [{
        "row_no": raw.get("row_no") or index,
        "username": str(raw.get("username") or "").strip(),
        "real_name": str(raw.get("real_name") or "").strip(),
        "class_code": normalize_code(raw.get("class_code")),
        "class_name": str(raw.get("class_name") or "").strip(),
        "enrollment_year": raw.get("enrollment_year"),
    } for index, raw in enumerate(rows, start=1)]

    existing_map = _existing_user_map([r["username"].lower() for r in normalized if r["username"]])
    class_names = _occupied_class_names(existing_map.values())
    codes = sorted({r["class_code"] for r in normalized if r["class_code"]})
    classes = {row.code: row for row in ClassRoom.objects.filter(code__in=codes)} if codes else {}

    # 逐行先定「目标班级」：已存在 / 待建 / 不可入班（用下标索引，避免重复 row_no 互相覆盖）
    pending: dict[str, dict] = {}
    targets: list[dict] = []
    for row in normalized:
        code = row["class_code"]
        if not code:
            targets.append({"kind": "none"})
            continue
        classroom = classes.get(code)
        if classroom is not None:
            if classroom.status in JOINABLE_CLASS_STATUSES:
                targets.append({"kind": "existing", "id": classroom.id, "name": classroom.name})
            else:
                targets.append({"kind": "blocked", "name": classroom.name,
                                "status": classroom.get_status_display()})
            continue
        if not CODE_PATTERN.match(code):
            targets.append({"kind": "bad_code"})
            continue
        if not create_missing:
            targets.append({"kind": "missing"})
            continue
        # 待建班级：同编码只建一次，名称/届别取首次出现的值
        entry = pending.setdefault(code, {
            "code": code,
            "name": row["class_name"] or code,
            "name_from_code": not row["class_name"],
            "enrollment_year": row["enrollment_year"] if isinstance(row["enrollment_year"], int) else default_year,
            "duration_years": default_duration,
            "student_count": 0,
            "approved": code in approved,
        })
        targets.append({"kind": "pending", "code": code})

    seen, dup = set(), set()
    for row in normalized:
        key = row["username"].lower()
        if key:
            if key in seen:
                dup.add(key)
            seen.add(key)

    out = []
    for row, target in zip(normalized, targets):
        username, real_name = row["username"], row["real_name"]
        existing_user = existing_map.get(username.lower())
        message = _username_error(username, real_name)
        status = "ok" if not message else "error"
        reuse_user_id = None

        if status == "ok":
            if username.lower() in dup:
                message, status = "与表内其他行学号重复", "error"
            elif existing_user is not None and existing_user.role != User.Role.STUDENT:
                message, status = "该学号已被其他角色账号占用", "error"
            elif existing_user is not None and class_names.get(existing_user.id):
                # 已有班的学生不再动：重复上传同一份名单必须幂等（准出 7）
                message = f"账号已存在，已在「{class_names[existing_user.id]}」，未修改"
                status = "skipped"
            elif existing_user is not None:
                # 有账号但还没入班：只补入班，不重建账号（学号唯一，重建必撞）
                reuse_user_id = existing_user.id
                message = "账号已存在，本次只入班"

        if status == "ok":
            if target["kind"] == "blocked":
                message, status = f"该班级已{target['status']}，不能再分配学生", "error"
            elif target["kind"] == "missing":
                message, status = "班级编码不存在", "error"
            elif target["kind"] == "bad_code":
                message, status = "班级编码只能是 3–32 位字母、数字或短横线", "error"
            elif target["kind"] == "pending" and require_approval and target["code"] not in approved:
                message, status = "所在班级未勾选新建，该行不会导入", "error"

        row_status = status
        # 只有**合法**行才计入待建班级人数：某编码下学生全错时该编码不进提交，
        # 避免留下一个空壳班（方案 X-33）。
        if row_status == "ok" and target["kind"] == "pending":
            pending[target["code"]]["student_count"] += 1

        out.append({
            **row,
            "initial_password": initial_password_for(username) if username else "",
            "target_class_id": target.get("id"),
            "target_class_name": target.get("name") or "",
            "target_class_code": target.get("code") or row["class_code"],
            "existing_user_id": reuse_user_id,
            "row_status": row_status,
            "message": message,
        })

    pending_list = [item for item in pending.values() if item["student_count"] > 0]
    return {"rows": out, "pending_classes": pending_list}


# ---------------------------------------------------------------------------
# 提交
# ---------------------------------------------------------------------------
def _failure_sheet(kind: str, failures: list[dict]) -> bytes:
    spec = get_spec(kind)
    wb = Workbook()
    ws = wb.active
    ws.title = "失败行"
    ws.append(spec.headers + ["错误原因"])
    for row in failures:
        values = []
        for col in spec.columns:
            key = _field_of(kind, col.header)
            values.append(row.get(key, ""))
        ws.append(values + [row.get("message", "")])
    for idx in range(1, len(spec.columns) + 2):
        ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = 20
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def password_sheet(kind: str, rows: list[dict], classes: dict[int, str]) -> bytes:
    """初始密码表。教师没有班级列，表头也用「工号」而不是「学号」。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "初始密码"
    if kind == KIND_TEACHER:
        ws.append(["工号", "姓名", "初始密码"])
        for row in rows:
            ws.append([row.get("username", ""), row.get("real_name", ""),
                       row.get("initial_password") or "沿用原密码"])
        widths = (22, 18, 18)
    else:
        ws.append(["学号", "姓名", "班级", "初始密码"])
        for row in rows:
            class_name = classes.get(row.get("target_class_id") or 0, "")
            ws.append([row.get("username", ""), row.get("real_name", ""),
                       class_name, row.get("initial_password") or "沿用原密码"])
        widths = (22, 18, 26, 18)
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = width
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def commit(kind: str, rows: list[dict], options: dict | None = None, *, operator=None) -> dict:
    """单事务写入。任一行失败整体回滚（`skip_invalid=False` 时直接抛校验异常）。"""
    from .audit import log_admin_action
    from .models import AdminActionLog

    options = dict(options or {})
    skip_invalid = bool(options.get("skip_invalid", False))
    if not isinstance(rows, list) or not rows:
        raise ImportFileError("没有可导入的数据")
    spec = get_spec(kind)
    if len(rows) > spec.max_rows:
        raise ImportFileError(f"单次最多导入 {spec.max_rows} 行")

    # 提交阶段必须逐个确认待建班级：approved_classes 为空时，待建行的学生一律转 error，
    # 不存在"没勾也给建"的路径（预览阶段才允许先看清单）。
    if kind == KIND_STUDENT:
        options["require_approval"] = True
    annotated = annotate_rows(kind, rows, options)
    all_rows = annotated["rows"]
    failures = [row for row in all_rows if row["row_status"] == "error"]
    if failures and not skip_invalid:
        raise ImportValidationError("存在无效或冲突的数据行，请修正后重新提交", all_rows)

    good = [row for row in all_rows if row["row_status"] == "ok"]
    skipped = [row for row in all_rows if row["row_status"] == "skipped"]
    created_classes: list[dict] = []
    created_users = 0
    created_members = 0
    password_classes: dict[int, str] = {}

    with transaction.atomic():
        if kind == KIND_CLASS:
            for row in good:
                classroom = ClassRoom.objects.create(
                    code=row["code"],
                    name=row["name"],
                    enrollment_year=row["enrollment_year"],
                    duration_years=row["duration_years"],
                    status=row["status"],
                )
                created_classes.append({"id": classroom.id, "code": classroom.code,
                                        "name": classroom.name})
        elif kind == KIND_TEACHER:
            for row in good:
                _create_account(row, User.Role.TEACHER)
                created_users += 1
        else:
            # 学生：先建待确认的班（只建有合法学生的），再建账号，再入班
            pending = {item["code"]: item for item in annotated.get("pending_classes") or []}
            code_to_class: dict[str, ClassRoom] = {}
            for code, item in pending.items():
                if not item.get("approved") or not item.get("student_count"):
                    continue
                classroom = ClassRoom.objects.create(
                    code=code,
                    name=item["name"],
                    enrollment_year=item.get("enrollment_year"),
                    duration_years=item.get("duration_years") or DEFAULT_DURATION,
                    status=ClassRoom.Status.ACTIVE,
                )
                code_to_class[code] = classroom
                created_classes.append({"id": classroom.id, "code": classroom.code,
                                        "name": classroom.name})

            # 待建班级建完后回填 target_class_id：初始密码表按 id 找班名，
            # 不回填的话自动建班那批人的「班级」列会是空的。
            for row in good:
                if row.get("target_class_id"):
                    continue
                room = code_to_class.get(normalize_code(row.get("class_code")))
                if room is not None:
                    row["target_class_id"] = room.id

            for row in good:
                reused_id = row.get("existing_user_id")
                if reused_id:
                    # 已有账号只是没入班：直接复用，不再新建（学号唯一，重建必撞）
                    user = User.objects.get(pk=reused_id)
                    row["initial_password"] = ""  # 对方可能已改过密码，不能瞎给
                else:
                    user = _create_account(row, User.Role.STUDENT)
                    created_users += 1
                code = normalize_code(row.get("class_code"))
                classroom = code_to_class.get(code)
                if classroom is None and code:
                    classroom = ClassRoom.objects.filter(code=code).first()
                if classroom is not None:
                    try:
                        assign_students(classroom, [user], operator=operator)
                    except ClassServiceError as exc:
                        raise ImportValidationError(
                            f"第 {row['row_no']} 行：{exc.detail}", all_rows
                        ) from exc
                    created_members += 1
                    password_classes[classroom.id] = classroom.name

        label = _audit_label(kind, created_users, created_classes, created_members)
        if operator is not None:
            log_admin_action(
                operator,
                AdminActionLog.Action.CLASS_IMPORT if kind == KIND_CLASS else AdminActionLog.Action.USER_IMPORT,
                target_type=kind,
                target_label=label,
                new_value={
                    "created_users": created_users,
                    "created_classes": [item["code"] for item in created_classes],
                    "created_members": created_members,
                    "skipped": len(skipped),
                    "failed": len(failures),
                    "skip_invalid": skip_invalid,
                },
            )

    result = {
        "kind": kind,
        "created_users": created_users,
        "created_classes": created_classes,
        "created_members": created_members,
        "skipped": len(skipped),
        "failed": len(failures),
        "failures": [
            {"row_no": row.get("row_no"), "message": row.get("message"),
             "username": row.get("username", ""), "code": row.get("code", "")}
            for row in failures
        ],
    }
    if failures:
        result["failure_file"] = _failure_sheet(kind, failures)
    if kind in (KIND_STUDENT, KIND_TEACHER) and good:
        result["password_file"] = password_sheet(kind, good, password_classes)
    return result


def _create_account(row: dict, role: str) -> User:
    user = User(
        username=row["username"],
        real_name=row["real_name"],
        role=role,
        must_change_password=True,
    )
    user.set_password(initial_password_for(row["username"]))
    user.save()
    return user


def _audit_label(kind: str, users: int, classes: list[dict], members: int) -> str:
    if kind == KIND_CLASS:
        return f"批量导入 {len(classes)} 个班级"
    role = "教师" if kind == KIND_TEACHER else "学生"
    label = f"批量导入 {users} 个{role}账号"
    if members:
        label += f" / 入班 {members} 人"
    if classes:
        label += f" / 新建 {len(classes)} 个班级"
    return label[:200]
