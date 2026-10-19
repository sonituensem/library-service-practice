"""Serializers for user registration and profile management."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from users.models import User


def normalize_unique_email(value, instance=None):
    """Normalize an email and prevent case-only duplicates."""

    email = User.objects.normalize_email(value)
    users = User.objects.filter(email__iexact=email)
    if instance is not None:
        users = users.exclude(pk=instance.pk)
    if users.exists():
        raise serializers.ValidationError("A user with this email already exists.")
    return email


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Create a user while keeping the password out of API responses."""

    password = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = ("id", "email", "password", "first_name", "last_name")
        read_only_fields = ("id",)

    def validate_email(self, value):
        return normalize_unique_email(value)

    def validate_password(self, value):
        user = User(email=self.initial_data.get("email", ""))
        validate_password(value, user=user)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class UserProfileSerializer(serializers.ModelSerializer):
    """Allow users to update their own profile and password safely."""

    password = serializers.CharField(
        write_only=True,
        required=False,
        trim_whitespace=False,
    )

    class Meta:
        model = User
        fields = ("id", "email", "password", "first_name", "last_name")
        read_only_fields = ("id",)
        extra_kwargs = {"email": {"required": False}}

    def validate_email(self, value):
        return normalize_unique_email(value, instance=self.instance)

    def validate(self, attrs):
        if "password" in attrs:
            candidate = User(
                email=attrs.get("email", self.instance.email),
                first_name=attrs.get("first_name", self.instance.first_name),
                last_name=attrs.get("last_name", self.instance.last_name),
            )
            try:
                validate_password(attrs["password"], user=candidate)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password is not None:
            instance.set_password(password)
        instance.save()
        return instance
