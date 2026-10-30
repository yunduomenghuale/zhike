"""账号格式规则：学生学号 6~8 位，教师工号 / 管理员账号 3~10 位，均只允许字母和数字。

统一入口（批量导入 / 管理端建号 / 注册 / 自助改名 / 存量整改）共用同一套判定，
避免各处规则漂移。四条约定：

1. 校验按**角色**取规则：学生 6~8 位（学号），教师与管理员 3~10 位（工号 / 账号）。
   两者业务含义不同——工号常是 wgy / sjy 这类 3 位简称，学号则要够长且唯一。
2. 规则只在**新建账号**或**值真的发生变化**时校验。存量可能不合规（早期拿中文姓名
   或 10 位数字当学号），若在编辑时无条件校验，这些账号连改姓名/头像都会被自己的
   账号挡住。登录与只读展示一律不校验；存量整改走 `manage.py normalize_usernames`。
3. 校验不依赖模型字段长度（`AbstractUser.username` 仍是 150）——收紧字段长度需要
   迁移，且存量超长数据会直接让迁移失败。
4. 中文错误文案在这里集中定义，导入预览、接口报错、前端提示共用同一措辞。
"""
import re

from django.core.exceptions import ValidationError
from rest_framework import serializers

ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9]+$")

STUDENT = "student"
TEACHER = "teacher"
ADMIN = "admin"

# 角色 → (最短, 最长, 字段中文名)
ROLE_RULES = {
    STUDENT: (6, 8, "学号"),
    TEACHER: (3, 10, "工号"),
    ADMIN: (3, 10, "账号"),
}
# 未指定角色时按宽松档（教师/管理员），避免误伤
FALLBACK_RULE = (3, 10, "账号")


def rule_for(role) -> tuple:
    return ROLE_RULES.get(str(role or ""), FALLBACK_RULE)


def account_rule_text(role) -> str:
    """规则提示语（前端与模板说明共用同一措辞）。"""
    low, high, label = rule_for(role)
    return f"{label}为 {low}~{high} 位字母或数字"


def account_problem(value, role=None, label: str = None) -> str:
    """返回中文错误说明；空串表示通过。role 决定长度区间与字段名。"""
    low, high, default_label = rule_for(role)
    name = label or default_label
    text = str(value or "").strip()
    if not text:
        return f"{name}不能为空"
    if not (low <= len(text) <= high):
        return f"{name}长度应为 {low}～{high} 位"
    if not ACCOUNT_PATTERN.match(text):
        return f"{name}只能由字母和数字组成"
    return ""


def validate_account(value, role=None, label: str = None):
    """Django 校验器语义：不合法抛 django.core.exceptions.ValidationError。"""
    problem = account_problem(value, role, label)
    if problem:
        raise ValidationError(problem, code="invalid_account")


def check_account(value, role=None, label: str = None) -> str:
    """DRF 序列化器语义：不合法抛 DRF ValidationError；通过返回去空格后的值。"""
    text = str(value or "").strip()
    problem = account_problem(text, role, label)
    if problem:
        raise serializers.ValidationError(problem)
    return text


def is_unchanged_account(value, instance) -> bool:
    """编辑已有账号时判断「值没变」——没变就跳过格式校验（存量账号放行）。"""
    if not instance:
        return False
    old = str(getattr(instance, "username", "") or "").strip()
    return str(value or "").strip().lower() == old.lower()


def is_compliant(value, role) -> bool:
    return account_problem(value, role) == ""
