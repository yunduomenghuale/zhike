from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.classroom.models import ClassRoom
from apps.courses.models import Course
from apps.ai.models import AICallLog, AICapabilityChangeLog, AICapabilityConfig
from apps.ai.providers.factory import get_env_config
from apps.users.serializers import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, validate_password_clean
from apps.users.validators import check_account, is_unchanged_account

from .models import AdminActionLog

User = get_user_model()


class AdminUserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    role_display = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "real_name", "avatar", "role",
            "role_display", "is_active", "date_joined", "last_login",
        ]

    def get_role(self, obj):
        return User.Role.ADMIN if obj.is_superuser else obj.role

    def get_role_display(self, obj):
        return "管理员" if obj.is_superuser else obj.get_role_display()


class AdminUserWriteSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=False,
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
    )

    class Meta:
        model = User
        fields = ["username", "real_name", "role", "is_active", "password"]

    def validate_username(self, value):
        value = str(value or "").strip()
        # 账号规则统一：6~8 位、仅字母数字；历史账号值未变化时放行
        if not is_unchanged_account(value, self.instance):
            value = check_account(value, "用户名")
        queryset = User.objects.filter(username__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("该用户名已被使用")
        return value

    def validate_password(self, value):
        validate_password_clean(value, self.instance)
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
    password = serializers.CharField(
        write_only=True,
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
    )

    def validate_password(self, value):
        validate_password_clean(value)
        return value


class AdminCourseSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source="teacher.real_name", read_only=True)
    teacher_username = serializers.CharField(source="teacher.username", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    term = serializers.SerializerMethodField()
    term_id = serializers.IntegerField(read_only=True)
    class_count = serializers.IntegerField(read_only=True)
    student_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Course
        fields = [
            "id", "name", "term", "term_id", "status", "status_display", "teacher_name",
            "teacher_username", "class_count", "student_count", "created_at",
        ]

    def get_term(self, obj) -> str:
        return obj.term.name if obj.term_id else ""


class CourseStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ["status"]


class ClassStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassRoom
        fields = ["status"]


class AdminClassSerializer(serializers.ModelSerializer):
    # ClassRoom.teacher 已降级为「建班人」留痕（不参与权限），对外只暴露 creator_*
    creator_name = serializers.CharField(source="teacher.real_name", read_only=True)
    creator_username = serializers.CharField(source="teacher.username", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    course_count = serializers.IntegerField(read_only=True)
    student_count = serializers.IntegerField(read_only=True)
    graduate_year = serializers.IntegerField(read_only=True)

    class Meta:
        model = ClassRoom
        fields = [
            "id", "code", "name", "status", "status_display",
            "creator_name", "creator_username",
            "enrollment_year", "duration_years", "graduate_year",
            "course_count", "student_count", "start_at", "end_at",
        ]


class AICapabilityConfigSerializer(serializers.ModelSerializer):
    capability_display = serializers.CharField(source="get_capability_display", read_only=True)
    provider_display = serializers.CharField(source="get_provider_display", read_only=True)
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False)
    api_key_configured = serializers.BooleanField(read_only=True)
    updated_by_name = serializers.CharField(source="updated_by.username", read_only=True, allow_null=True)
    # 管理端可配的超时/发音人：留空(null/"")表示按环境变量/默认值
    timeout = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=3600, label="超时(秒)"
    )
    voice = serializers.CharField(
        required=False, allow_blank=True, max_length=64, label="发音人"
    )

    class Meta:
        model = AICapabilityConfig
        fields = [
            "capability", "capability_display", "provider", "provider_display", "enabled",
            "base_url", "model_name", "timeout", "voice", "supports_vision",
            "api_key", "api_key_configured",
            "updated_at", "updated_by_name",
        ]
        read_only_fields = ["updated_at"]

    def validate(self, attrs):
        provider = attrs.get("provider", getattr(self.instance, "provider", AICapabilityConfig.Provider.MOCK))
        enabled = attrs.get("enabled", getattr(self.instance, "enabled", False))
        api_key = attrs.get("api_key", None)
        previous_provider = getattr(self.instance, "provider", None)
        has_saved_key = bool(getattr(self.instance, "api_key_ciphertext", "")) and provider == previous_provider
        # 发音人仅对语音合成有意义：其他能力传了也清掉，避免保存无意义值
        capability = attrs.get("capability", getattr(self.instance, "capability", None))
        if "voice" in attrs and capability != AICapabilityConfig.Capability.TTS:
            attrs["voice"] = ""
        # 「支持图片」仅对对话有意义（问答图片上传入口）：其他能力强制关闭，
        # 防止误开后前端对 embed/rerank/tts 行显示无意义的开关状态
        if capability != AICapabilityConfig.Capability.CHAT:
            attrs["supports_vision"] = False
        # 能力-服务商白名单：DeepSeek 无 embedding/TTS 接口、重排序仅通义千问，拒收越界保存
        allowed = AICapabilityConfig.CAPABILITY_PROVIDERS.get(capability)
        if allowed and provider not in allowed:
            capability_label = dict(AICapabilityConfig.Capability.choices).get(capability, capability)
            allowed_labels = "、".join(
                dict(AICapabilityConfig.Provider.choices).get(p, p) for p in allowed
            )
            raise serializers.ValidationError(
                {"provider": f"该服务商暂不支持{capability_label}，请选择：{allowed_labels}"}
            )

        if enabled and provider != AICapabilityConfig.Provider.MOCK:
            if provider == AICapabilityConfig.Provider.LOCAL:
                # 系统内置模型：无需 Key/接口地址；模型名留空补默认（BGE-M3 / Qwen3-Reranker）
                if not attrs.get("model_name", getattr(self.instance, "model_name", "")):
                    from apps.ai.local_models import default_model

                    attrs["model_name"] = default_model(capability) if capability in ("embed", "rerank") else ""
                attrs["base_url"] = ""
                return attrs
            if not (api_key or has_saved_key):
                # 表单 Key 留空即"不修改"（密码框不留值）：回退到环境变量里同服务商已生效的
                # Key，与「测试连接」同源；取到后物化进本记录——否则空 Key 的 DB 行会影子
                # 覆盖环境变量，保存后 build_provider 拿不到 Key 将静默回落 mock。
                fallback = self._env_api_key(provider, attrs.get("capability"))
                if not fallback:
                    raise serializers.ValidationError({"api_key": "启用真实模型时必须填写 API Key"})
                attrs["api_key"] = fallback
            if not attrs.get("base_url", getattr(self.instance, "base_url", "")):
                raise serializers.ValidationError({"base_url": "请填写接口地址"})
            if not attrs.get("model_name", getattr(self.instance, "model_name", "")):
                raise serializers.ValidationError({"model_name": "请填写模型名称"})
        return attrs

    def _env_api_key(self, provider: str, capability=None) -> str:
        """环境变量派生配置中同服务商的 API Key（服务商不匹配或未配置时返回空串）。"""
        capability = capability or getattr(self.instance, "capability", None)
        if capability not in dict(AICapabilityConfig.Capability.choices):
            return ""
        try:
            env_provider, env_config = get_env_config(capability)
        except Exception:
            return ""
        return env_config.get("api_key", "") if env_provider == provider else ""

    def create(self, validated_data):
        # api_key 是 write_only 序列化字段而非模型字段，需弹出后单独加密落库
        api_key = validated_data.pop("api_key", None)
        instance = AICapabilityConfig(**validated_data)
        if api_key:
            instance.set_api_key(api_key)
        request = self.context.get("request")
        if request is not None:
            instance.updated_by = request.user
        instance.save()
        return instance

    def update(self, instance, validated_data):
        api_key = validated_data.pop("api_key", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if api_key:
            instance.set_api_key(api_key)
        instance.updated_by = self.context["request"].user
        instance.save()
        return instance


class AICallLogSerializer(serializers.ModelSerializer):
    """AI 调用流水（只读）。token 字段仅 HTTP 类服务有值；本地内置模型看 item_count。"""

    capability_display = serializers.CharField(source="get_capability_display", read_only=True)
    scene_display = serializers.CharField(source="get_scene_display", read_only=True)
    provider_display = serializers.SerializerMethodField()
    triggered_by_name = serializers.CharField(
        source="triggered_by.username", read_only=True, allow_null=True
    )
    course_name = serializers.CharField(source="course.name", read_only=True, allow_null=True)

    class Meta:
        model = AICallLog
        fields = [
            "id", "created_at", "capability", "capability_display", "provider",
            "provider_display", "model_name", "scene", "scene_display", "success",
            "is_mock", "error", "latency_ms", "attempts", "prompt_tokens",
            "completion_tokens", "total_tokens", "item_count", "input_chars",
            "output_chars", "input_digest", "input_preview", "trace_id",
            "triggered_by", "triggered_by_name", "course", "course_name",
        ]

    def get_provider_display(self, obj):
        return dict(AICapabilityConfig.Provider.choices).get(obj.provider, obj.provider or "—")


class AICapabilityChangeLogSerializer(serializers.ModelSerializer):
    """能力配置变更记录（只读）。changes 为字段级 old→new，API Key 只记存在性。"""

    capability_display = serializers.CharField(source="get_capability_display", read_only=True)
    changed_by_name = serializers.CharField(
        source="changed_by.username", read_only=True, allow_null=True
    )

    class Meta:
        model = AICapabilityChangeLog
        fields = [
            "id", "created_at", "capability", "capability_display",
            "changed_by", "changed_by_name", "changes",
        ]


class AdminActionLogSerializer(serializers.ModelSerializer):
    """管理端操作审计（只读）。old_value/new_value 为字段级 old→new 快照。"""

    action_display = serializers.CharField(source="get_action_display", read_only=True)
    actor_name = serializers.CharField(source="actor.username", read_only=True)

    class Meta:
        model = AdminActionLog
        fields = [
            "id", "created_at", "actor", "actor_name", "action", "action_display",
            "target_type", "target_id", "target_label",
            "old_value", "new_value", "note",
        ]
