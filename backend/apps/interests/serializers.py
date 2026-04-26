from rest_framework import serializers


class TopInterestSerializer(serializers.Serializer):
    tag = serializers.CharField()
    count = serializers.IntegerField()


class InterestPostSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    author_id = serializers.IntegerField()
    content = serializers.CharField()
    interest_tags = serializers.ListField(child=serializers.CharField())
    created_at = serializers.DateTimeField()


class InterestSuggestionSerializer(serializers.Serializer):
    tag = serializers.CharField()
    count = serializers.IntegerField()
