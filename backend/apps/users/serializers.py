from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "real_name",
            "role",
            "role_display",
            "phone",
            "email",
            "avatar",
            "is_active",
            "date_joined",
        ]
        read_only_fields = ["id", "date_joined", "is_active"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ["username", "password", "real_name", "role", "phone", "email"]

    def validate_role(self, value):
        # 注册仅允许教师 / 学生，管理员由后台创建
        if value not in (User.Role.TEACHER, User.Role.STUDENT):
            raise serializers.ValidationError("角色只能是教师或学生")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user
