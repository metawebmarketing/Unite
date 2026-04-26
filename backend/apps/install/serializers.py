from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


class InstallStatusSerializer(serializers.Serializer):
    installed = serializers.BooleanField()
    installed_at = serializers.DateTimeField(allow_null=True)
    seed_requested = serializers.BooleanField()
    seed_status = serializers.CharField()
    seed_task_id = serializers.CharField(allow_blank=True)
    seed_total_users = serializers.IntegerField()
    seed_total_posts = serializers.IntegerField()
    seed_created_users = serializers.IntegerField()
    seed_created_posts = serializers.IntegerField()
    seed_last_message = serializers.CharField(allow_blank=True)


class InstallRunSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)
    display_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    location = serializers.CharField(max_length=120, required=False, allow_blank=True)
    seed_demo_data = serializers.BooleanField(required=False, default=False)

    def validate_username(self, value: str) -> str:
        lowered = value.strip()
        if User.objects.filter(username=lowered).exists():
            raise serializers.ValidationError("Username is already in use.")
        return lowered

    def validate_email(self, value: str) -> str:
        lowered = value.strip().lower()
        if User.objects.filter(email__iexact=lowered).exists():
            raise serializers.ValidationError("Email is already in use.")
        return lowered

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value
