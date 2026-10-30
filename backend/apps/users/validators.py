"""账号（学号 / 工号 / 用户名）格式规则：6~8 位，只能由字母和数字组成。

统一入口（批量导入 / 管理端建号 / 注册 / 自助改名）共用同一套判定，避免各处
规则漂移。三条约定：

1. 规则只在**新建账号**或**值真的发生变化**时校验。历史账号可能不满足
   （admin 5 位、t101 4 位、lymatrix2020 11 位等），若在编辑时无条件校验，
   这些账号连改头像/姓名都会被自己的用户名挡死。登录与只读展示一律不校验。
2. 校验不再依赖模型字段长度（`AbstractUser.username` 仍是 150）——收紧字段
   长度需要迁移，且存量超长数据会直接让迁移失败。
3. 中文错误文案在这里集中定义，导入预览、接口报错、前端提示共用同一措辞。
"""
import re

from django.core.exceptions import ValidationError
from rest_framework import serializers

ACCOUNT_MIN_LENGTH = 6
ACCOUNT_MAX_LENGTH = 8
ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9]+$")
# 提示语统一口径（前端与模板说明直接引用这段文字）
ACCOUNT_RULE_TEXT = f"{ACCOUNT_MIN_LENGTH}~{ACCOUNT_MAX_LENGTH} 位字母或数字"


def account_problem(value, label="用户名") -> str:
    """返回中文错误说明；空串表示通过。供导入行校验等需要「拿文案」的场景使用。"""
    text = str(value or "").strip()
    if not text:
        return f"{label}不能为空"
    if not (ACCOUNT_MIN_LENGTH <= len(text) <= ACCOUNT_MAX_LENGTH):
        return f"{label}长度应为 {ACCOUNT_MIN_LENGTH}～{ACCOUNT_MAX_LENGTH} 位"
    if not ACCOUNT_PATTERN.match(text):
        return f"{label}只能由字母和数字组成"
    return ""


def validate_account(value, label="用户名"):
    """Django 校验器语义：不合法抛 django.core.exceptions.ValidationError。"""
    problem = account_problem(value, label)
    if problem:
        raise ValidationError(problem, code="invalid_account")


def check_account(value, label="用户名") -> str:
    """DRF 序列化器语义：不合法抛 DRF ValidationError；通过返回去空格后的值。"""
    text = str(value or "").strip()
    problem = account_problem(text, label)
    if problem:
        raise serializers.ValidationError(problem)
    return text


def is_unchanged_account(value, instance) -> bool:
    """编辑已有账号时判断「值没变」——没变就跳过格式校验（历史账号放行）。"""
    if not instance:
        return False
    old = str(getattr(instance, "username", "") or "").strip()
    return str(value or "").strip().lower() == old.lower()
