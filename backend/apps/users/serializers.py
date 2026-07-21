import re

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


def normalize_phone(value):
    """统一手机号格式，避免空格或连字符绕过唯一校验。"""
    if value is None:
        return None
    value = str(value).strip().replace(" ", "").replace("-", "")
    if not value:
        return None
    if not re.fullmatch(r"\+?\d{6,20}", value):
        raise serializers.ValidationError("请输入正确的手机号")
    return value


class UserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    role_display = serializers.SerializerMethodField()

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
            "phone",
            "avatar",
            "is_active",
            "date_joined",
        ]
        read_only_fields = ["id", "date_joined", "is_active"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = User
        fields = ["username", "password", "real_name", "role", "phone"]

    def validate_role(self, value):
        # 注册仅允许教师 / 学生，管理员由后台创建
        if value not in (User.Role.TEACHER, User.Role.STUDENT):
            raise serializers.ValidationError("角色只能是教师或学生")
        return value

    def validate_username(self, value):
        value = value.strip()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("该用户名已被使用")
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError("该用户名已被其他账号作为手机号使用")
        return value

    def validate_phone(self, value):
        value = normalize_phone(value)
        if value is None:
            return None
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError("该手机号已被使用")
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("该手机号已被其他账号作为用户名使用")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """当前用户可自行维护的基础资料。"""

    class Meta:
        model = User
        fields = ["username", "phone", "real_name"]

    def validate_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("用户名不能为空")
        queryset = User.objects.filter(username__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("该用户名已被使用")
        phone_queryset = User.objects.filter(phone=value)
        if self.instance:
            phone_queryset = phone_queryset.exclude(pk=self.instance.pk)
        if phone_queryset.exists():
            raise serializers.ValidationError("该用户名已被其他账号作为手机号使用")
        return value

    def validate_phone(self, value):
        value = normalize_phone(value)
        if value is None:
            return None
        queryset = User.objects.filter(phone=value)
        username_queryset = User.objects.filter(username__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
            username_queryset = username_queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("该手机号已被使用")
        if username_queryset.exists():
            raise serializers.ValidationError("该手机号已被其他账号作为用户名使用")
        return value


class AvatarUploadSerializer(serializers.Serializer):
    avatar = serializers.ImageField(write_only=True)

    def validate_avatar(self, value):
        if value.size > 3 * 1024 * 1024:
            raise serializers.ValidationError("头像大小不能超过 3MB")
        if value.image.format not in {"JPEG", "PNG", "WEBP"}:
            raise serializers.ValidationError("仅支持 JPG、PNG 或 WEBP 图片")
        return value


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, min_length=6)
    confirm_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("当前密码不正确")
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "两次输入的新密码不一致"})
        validate_password(attrs["new_password"], self.context["request"].user)
        return attrs
