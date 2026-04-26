from rest_framework import serializers

from apps.themes.models import ThemeConfig


class ThemeUploadSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    version = serializers.CharField(max_length=32)
    tokens = serializers.DictField()

    def validate_tokens(self, tokens):
        required_roots = {"colors", "spacing", "radius", "typography"}
        root_keys = set(tokens.keys())
        missing = sorted(required_roots - root_keys)
        if missing:
            raise serializers.ValidationError(f"Missing required token groups: {', '.join(missing)}")
        unexpected_roots = sorted(root_keys - required_roots)
        if unexpected_roots:
            raise serializers.ValidationError(f"Unexpected token groups: {', '.join(unexpected_roots)}")

        colors = tokens.get("colors")
        spacing = tokens.get("spacing")
        radius = tokens.get("radius")
        typography = tokens.get("typography")
        if not isinstance(colors, dict) or not isinstance(spacing, dict):
            raise serializers.ValidationError("Theme token groups must be JSON objects.")
        if not isinstance(radius, dict) or not isinstance(typography, dict):
            raise serializers.ValidationError("Theme token groups must be JSON objects.")

        self._validate_color_tokens(colors)
        self._validate_numeric_token(spacing, "sm", min_value=0, max_value=64)
        self._validate_numeric_token(spacing, "md", min_value=0, max_value=128)
        self._validate_numeric_token(radius, "md", min_value=0, max_value=64)
        self._validate_numeric_token(typography, "base", min_value=10, max_value=32)
        return tokens

    def _validate_color_tokens(self, colors: dict) -> None:
        required_colors = {"background", "surface", "textPrimary", "border"}
        missing = sorted(required_colors - set(colors.keys()))
        if missing:
            raise serializers.ValidationError(f"Missing required color tokens: {', '.join(missing)}")
        for key in required_colors:
            value = colors.get(key)
            if not isinstance(value, str) or not value.startswith("#") or len(value) not in {4, 7}:
                raise serializers.ValidationError(f"Color token '{key}' must be a hex color string.")
            is_valid_hex = all(ch in "0123456789abcdefABCDEF" for ch in value[1:])
            if not is_valid_hex:
                raise serializers.ValidationError(f"Color token '{key}' must be a valid hex color.")

    def _validate_numeric_token(self, group: dict, key: str, *, min_value: int, max_value: int) -> None:
        if key not in group:
            raise serializers.ValidationError(f"Missing required numeric token: {key}")
        value = group[key]
        if not isinstance(value, (int, float)):
            raise serializers.ValidationError(f"Numeric token '{key}' must be a number.")
        if value < min_value or value > max_value:
            raise serializers.ValidationError(
                f"Numeric token '{key}' must be between {min_value} and {max_value}."
            )


class ThemeConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ThemeConfig
        fields = ["id", "name", "version", "tokens", "is_active", "updated_at"]
