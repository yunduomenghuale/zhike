"""账号规范化：把不合规的学号 / 工号整改为符合角色规则的账号。

规则见 apps/users/validators.py：学生 6~8 位、教师与管理员 3~10 位，均只允许字母数字。
本命令只处理**存量**数据（新账号在建号/导入时已被拦），默认 dry-run。

用法：
    manage.py normalize_usernames                     # 只打印将要改什么
    manage.py normalize_usernames --apply             # 真正执行
    manage.py normalize_usernames --role student      # 只处理学生
    manage.py normalize_usernames --apply --map 孟燕姿=B260101 --map 张一=B260102

改名策略：
- 优先保留原账号里的字母数字部分（学生截到 8 位、教师/管理员截到 10 位），
  这样「hys2007」这类本来就合规的不动，「e2ep4_x_s1」会退化成「e2ep4s1」；
- 退化后仍不满足长度（如中文姓名、纯 3 位学生的学号）则按
  「B + 两位年份 + 4 位序号」（学生）/「T + 两位年份 + 3 位序号」（教师）生成，
  年份取入学年、没有则取账号创建年；
- 生成结果与全库账号（不区分大小写）比对，冲突自动顺延序号；
- 密码、班级关系、学习记录都不动，只改登录账号。

执行后会在 output/ 下留一份 CSV（旧账号,新账号,姓名,角色,班级），便于发给学生本人。
"""
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.functions import Lower
from django.utils import timezone

from apps.classroom.models import ClassStudent
from apps.platform_admin.audit import log_admin_action
from apps.platform_admin.models import AdminActionLog
from apps.users.models import User
from apps.users.validators import ADMIN, STUDENT, TEACHER, account_problem, rule_for

SLUG_RE = re.compile(r"[^A-Za-z0-9]")


def _slug(username: str) -> str:
    return SLUG_RE.sub("", username or "")


def _enroll_year(user, fallback: int) -> int:
    if getattr(user, "enrollment_year", None):
        return int(user.enrollment_year)
    if user.date_joined:
        return timezone.localtime(user.date_joined).year
    return fallback


class Command(BaseCommand):
    help = "把不合规的学号/工号整改为符合角色规则的账号（默认 dry-run）"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="真正写库（默认只预览）")
        parser.add_argument(
            "--role", choices=[STUDENT, TEACHER, ADMIN], help="只处理指定角色"
        )
        parser.add_argument(
            "--map", action="append", default=[], metavar="OLD=NEW",
            help="手工指定映射，可重复；优先级高于自动生成",
        )
        parser.add_argument(
            "--keep-slug", action="store_true",
            help="不保留原账号片段，一律按规则重新生成",
        )
        parser.add_argument("--actor", help="审计记录的执行人用户名（默认取第一个管理员）")

    # ---- 主流程 -----------------------------------------------------------
    def handle(self, *args, **options):
        apply = options["apply"]
        only_role = options.get("role")
        keep_slug = options["keep_slug"]
        manual = self._parse_maps(options["map"])
        now_year = timezone.localdate().year

        users = list(User.objects.all().order_by("id"))
        taken = {u.username.lower() for u in users if u.username}

        pending = []
        for user in users:
            role = ADMIN if user.is_superuser else user.role
            if only_role and role != only_role:
                continue
            problem = account_problem(user.username, role)
            if not problem:
                continue
            new_name = manual.get(user.username) or self._generate(
                user, role, taken, now_year, keep_slug, apply
            )
            if not new_name:
                self.stderr.write(f"跳过 {user.username}：无法生成合规账号")
                continue
            taken.add(new_name.lower())
            pending.append((user, role, problem, new_name))

        if not pending:
            self.stdout.write("没有需要整改的账号")
            return

        self._print_table(pending, now_year, apply)
        csv_path = self._write_csv(pending)
        self.stdout.write(f"\n映射表已写入 {csv_path}")

        if not apply:
            self.stdout.write(
                self.style.WARNING("\n以上为预览（dry-run）。加 --apply 才会真正改名。")
            )
            return

        actor = self._resolve_actor(options.get("actor"))
        with transaction.atomic():
            for user, role, _problem, new_name in pending:
                old_name = user.username
                User.objects.filter(pk=user.pk).update(username=new_name)
                if actor is not None:
                    log_admin_action(
                        actor,
                        AdminActionLog.Action.USER_UPDATE,
                        target_type="user",
                        target_id=user.pk,
                        target_label=f"{user.real_name or old_name}",
                        old_value={"username": old_name},
                        new_value={"username": new_name},
                        note=f"账号规范化（{role}）：不合规账号整改",
                    )
        self.stdout.write(self.style.SUCCESS(f"\n已整改 {len(pending)} 个账号"))

    # ---- 辅助 -------------------------------------------------------------
    @staticmethod
    def _parse_maps(pairs: list[str]) -> dict:
        mapping = {}
        for raw in pairs:
            if "=" not in raw:
                raise SystemExit(f"--map 格式应为 OLD=NEW：{raw}")
            old, new = (part.strip() for part in raw.split("=", 1))
            mapping[old] = new
        return mapping

    def _generate(self, user, role, taken, now_year, keep_slug, apply) -> str:
        low, high, _label = rule_for(role)
        if not keep_slug:
            slug = _slug(user.username)
            if len(slug) >= low:
                candidate = slug[:high]
                if candidate.lower() not in taken and not account_problem(candidate, role):
                    return candidate
        prefix = "B" if role == STUDENT else "T"
        year = str(_enroll_year(user, now_year))[-2:]
        width = 4 if role == STUDENT else 3
        for seq in range(1, 10000):
            candidate = f"{prefix}{year}{seq:0{width}d}"
            if len(candidate) < low or account_problem(candidate, role):
                continue
            if candidate.lower() not in taken:
                return candidate
        return ""

    def _print_table(self, pending, now_year, apply):
        self.stdout.write(f"{'角色':<8}{'旧账号':<22}{'新账号':<14}{'姓名':<10}原因")
        self.stdout.write("-" * 78)
        for user, role, problem, new_name in pending:
            self.stdout.write(
                f"{role:<8}{user.username:<22}{new_name:<14}{(user.real_name or '—'):<10}{problem}"
            )

    def _write_csv(self, pending) -> Path:
        base = Path(getattr(settings, "BASE_DIR", ".")).parent / "output"
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"username-normalize-{datetime.now():%Y%m%d-%H%M%S}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["旧账号", "新账号", "姓名", "角色", "班级"])
            for user, role, _problem, new_name in pending:
                classes = list(
                    ClassStudent.objects.filter(
                        student=user, learn_status__in=ClassStudent.OCCUPYING_STATUSES
                    ).values_list("classroom__name", flat=True)
                )
                writer.writerow([user.username, new_name, user.real_name or "", role, "、".join(classes)])
        return path

    @staticmethod
    def _resolve_actor(username: str | None):
        qs = User.objects.all()
        if username:
            user = qs.filter(username__iexact=username).first()
            if user is None:
                raise SystemExit(f"未找到执行人：{username}")
            return user
        return (
            qs.filter(role=User.Role.ADMIN).order_by("id").first()
            or qs.filter(is_superuser=True).order_by("id").first()
        )
