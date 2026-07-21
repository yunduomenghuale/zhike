from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.classroom.models import ClassRoom
from apps.courses.models import Course
from apps.ai.models import AIConfiguration
from apps.users.serializers import normalize_phone

User = get_user_model()


class AdminUserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    role_display = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "real_name", "phone", "avatar", "role",
            "role_display", "is_active", "date_joined", "last_login",
        ]

    def get_role(self, obj):
        return User.Role.ADMIN if obj.is_superuser else obj.role

    def get_role_display(self, obj):
        return "管理员" if obj.is_superuser else obj.get_role_display()


class AdminUserWriteSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=6)
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = User
        fields = ["username", "real_name", "phone", "role", "is_active", "password"]

    def validate_username(self, value):
        value = value.strip()
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

    def validate(self, attrs):
        if not self.instance and not attrs.get("password"):
            raise serializers.ValidationError({"password": "创建账号时必须设置初始密码"})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class PasswordResetSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, min_length=6)


class AdminCourseSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source="teacher.real_name", read_only=True)
    teacher_username = serializers.CharField(source="teacher.username", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    class_count = serializers.IntegerField(read_only=True)
    student_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Course
        fields = [
            "id", "name", "term", "status", "status_display", "teacher_name",
            "teacher_username", "class_count", "student_count", "created_at",
        ]


class CourseStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ["status"]


class AdminClassSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source="teacher.real_name", read_only=True)
    teacher_username = serializers.CharField(source="teacher.username", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    course_count = serializers.IntegerField(read_only=True)
    student_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ClassRoom
        fields = [
            "id", "name", "status", "status_display", "teacher_name",
            "teacher_username", "course_count", "student_count", "start_at", "end_at",
        ]


class AdminAIConfigurationSerializer(serializers.ModelSerializer):
    provider_display = serializers.CharField(source="get_provider_display", read_only=True)
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False)
    api_key_configured = serializers.BooleanField(read_only=True)
    updated_by_name = serializers.CharField(source="updated_by.username", read_only=True, allow_null=True)

    class Meta:
        model = AIConfiguration
        fields = [
            "provider", "provider_display", "enabled", "base_url", "chat_model",
            "embed_model", "tts_model", "api_key", "api_key_configured",
            "last_test_status", "last_test_message", "last_tested_at",
            "updated_at", "updated_by_name",
        ]
        read_only_fields = [
            "last_test_status", "last_test_message", "last_tested_at", "updated_at",
        ]

    def validate(self, attrs):
        provider = attrs.get("provider", getattr(self.instance, "provider", AIConfiguration.Provider.MOCK))
        enabled = attrs.get("enabled", getattr(self.instance, "enabled", False))
        api_key = attrs.get("api_key", None)
        previous_provider = getattr(self.instance, "provider", None)
        has_saved_key = bool(getattr(self.instance, "api_key_ciphertext", "")) and provider == previous_provider

        if enabled and provider != AIConfiguration.Provider.MOCK:
            if not (api_key or has_saved_key):
                raise serializers.ValidationError({"api_key": "启用真实模型时必须填写 API Key"})
            if not attrs.get("base_url", getattr(self.instance, "base_url", "")):
                raise serializers.ValidationError({"base_url": "请填写接口地址"})
            if not attrs.get("chat_model", getattr(self.instance, "chat_model", "")):
                raise serializers.ValidationError({"chat_model": "请填写对话模型名称"})
        return attrs

    def update(self, instance, validated_data):
        api_key = validated_data.pop("api_key", None)
        provider_changed = "provider" in validated_data and validated_data["provider"] != instance.provider
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if api_key:
            instance.set_api_key(api_key)
        elif provider_changed:
            instance.api_key_ciphertext = ""
        instance.last_test_status = AIConfiguration.TestStatus.UNTESTED
        instance.last_test_message = ""
        instance.last_tested_at = None
        instance.updated_by = self.context["request"].user
        instance.save()
        return instance
