from collections import Counter

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.interests.serializers import InterestPostSerializer, InterestSuggestionSerializer, TopInterestSerializer
from apps.posts.models import Post


class TopInterestsView(APIView):
    def get(self, request):
        limit = max(1, min(int(request.query_params.get("limit", 10)), 50))
        post_tags = Post.objects.values_list("interest_tags", flat=True)[:1000]
        counter: Counter = Counter()
        for tags in post_tags:
            if isinstance(tags, list):
                for tag in tags:
                    normalized = str(tag).strip().lower()
                    if normalized:
                        counter[normalized] += 1

        top = [{"tag": tag, "count": count} for tag, count in counter.most_common(limit)]
        serializer = TopInterestSerializer(top, many=True)
        return Response(serializer.data)


class TopInterestPostsView(APIView):
    def get(self, request):
        limit = max(1, min(int(request.query_params.get("limit", 20)), 50))
        tag = str(request.query_params.get("tag", "")).strip().lower()
        queryset = Post.objects.select_related("author").order_by("-created_at")[:500]
        filtered_posts = []
        for post in queryset:
            tags = post.interest_tags if isinstance(post.interest_tags, list) else []
            if tag and tag not in [str(item).strip().lower() for item in tags]:
                continue
            filtered_posts.append(post)
            if len(filtered_posts) >= limit:
                break

        posts = [
            {
                "id": post.id,
                "author_id": post.author_id,
                "content": post.content,
                "interest_tags": post.interest_tags if isinstance(post.interest_tags, list) else [],
                "created_at": post.created_at,
            }
            for post in filtered_posts
        ]
        serializer = InterestPostSerializer(posts, many=True)
        return Response(serializer.data)


class InterestSuggestionsView(APIView):
    def get(self, request):
        limit = max(1, min(int(request.query_params.get("limit", 8)), 20))
        selected_raw = str(request.query_params.get("selected", ""))
        query = str(request.query_params.get("query", "")).strip().lower()
        selected = {
            str(tag).strip().lower()
            for tag in selected_raw.split(",")
            if str(tag).strip()
        }
        post_tags = Post.objects.values_list("interest_tags", flat=True)[:1500]
        counter: Counter = Counter()
        for tags in post_tags:
            if not isinstance(tags, list):
                continue
            for tag in tags:
                normalized = str(tag).strip().lower()
                if not normalized or normalized in selected:
                    continue
                if query and query not in normalized:
                    continue
                counter[normalized] += 1

        suggestions = [{"tag": tag, "count": count} for tag, count in counter.most_common(limit)]
        serializer = InterestSuggestionSerializer(suggestions, many=True)
        return Response(serializer.data)
