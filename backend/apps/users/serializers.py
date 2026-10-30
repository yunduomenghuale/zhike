from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .validators import check_account, is_unchanged_account

User = get_user_model()
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 12

# Django NumericPasswordValidator 的提示文案；统一报错时剔除，避免
# 「这个密码太常见了。，密码只包含数字。」这类多校验器文案被「，」生硬拼接
NUMERIC_ONLY_MESSAGE = "密码只包含数字。"


def validate_password_clean(value, user=None):
    """Django 密码校验的统一切面：校验规则不变，仅清理多条提示的拼接文案。"""
    try:
        django_validate_password(value, user)
    except DjangoValidationError as exc:
        messages = [m for m in exc.messages if NUMERIC_ONLY_MESSAGE not in m]
        raise DjangoValidationError(messages or exc.messages)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class UserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    role_display = serializers.SerializerMethodField()
    edu_status_display = serializers.CharField(source="get_edu_status_display", read_only=True)

    def get_role(self, obj):
        return User.Role.ADMIN if obj.is_superuser else obj.role

    def get_role_display(self, obj):
        return "管理员" if obj.is_superuser else obj.get_role_display()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "real_name",
            "role",
            "role_display",
            "avatar",
            "is_active",
            "must_change_password",
            "date_joined",
            "edu_status",
            "edu_status_display",
        ]
        # edu_status 只读：学籍变更走管理端 service（审计 + 状态时间留痕）
        read_only_fields = ["id", "date_joined", "is_active", "must_change_password", "edu_status"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
    )

    class Meta:
        model = User
        fields = ["username", "password", "role"]

    def validate_role(self, value):
        # 注册仅允许教师 / 学生，管理员由后台创建
        if value not in (User.Role.TEACHER, User.Role.STUDENT):
            raise serializers.ValidationError("角色只能是教师或学生")
        return value

    def validate_password(self, value):
        validate_password_clean(value)
        return value

    def validate_username(self, value):
        # 账号规则统一：6~8 位、仅字母数字（见 apps/users/validators.py）
        value = check_account(value, "用户名")
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("该用户名已被使用")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """当前用户可自行维护的基础资料（手机号已停止采集，DB 列保留）。"""

    class Meta:
        model = User
        fields = ["username", "real_name"]

    def validate_username(self, value):
        value = str(value or "").strip()
        if not value:
            raise serializers.ValidationError("用户名不能为空")
        # 历史账号（如 4 位工号）原样保存时跳过格式校验，否则改头像/姓名也会被挡
        if not is_unchanged_account(value, self.instance):
            value = check_account(value, "用户名")
        queryset = User.objects.filter(username__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("该用户名已被使用")
        return value


class AvatarUploadSerializer(serializers.Serializer):
    avatar = serializers.ImageField(write_only=True)

    def validate_avatar(self, value):
        if value.size > 3 * 1024 * 1024:
            raise serializers.ValidationError("头像大小不能超过 3MB")
        if value.image.format not in {"JPEG", "PNG", "WEBP"}:
            raise serializers.ValidationError("仅支持 JPG、PNG 或 WEBP 图片")
        # 拦截动图：GIF 已被上面的格式白名单挡住，这里挡 APNG / 动图 WebP
        # （Pillow 对 JPEG 无 is_animated 属性，getattr 回退 False）
        if getattr(value.image, "is_animated", False):
            raise serializers.ValidationError("不支持动图，请选择静态图片")
        return value


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
    )
    confirm_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        max_length=PASSWORD_MAX_LENGTH,
    )

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("当前密码不正确")
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "两次输入的新密码不一致"})
        validate_password_clean(attrs["new_password"], self.context["request"].user)
        return attrs


class NotificationSerializer(serializers.ModelSerializer):
    ntype_display = serializers.CharField(source="get_ntype_display", read_only=True)

    class Meta:
        from .models import Notification

        model = Notification
        fields = [
            "id", "ntype", "ntype_display", "title", "content", "link",
            "is_read", "created_at",
        ]
