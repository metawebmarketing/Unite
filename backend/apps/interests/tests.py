from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.accounts.models import Profile
from apps.posts.models import Post

User = get_user_model()


class InterestsApiTests(APITestCase):
    def test_top_interests_endpoint(self):
        user = User.objects.create_user(username="interests_user", password="Password123!")
        Profile.objects.create(user=user, display_name="InterestsUser")
        self.client.force_authenticate(user=user)
        Post.objects.create(author=user, content="a", interest_tags=["tech", "ai"])
        Post.objects.create(author=user, content="b", interest_tags=["tech", "design"])

        response = self.client.get("/api/v1/interests/top")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(item["tag"] == "tech" for item in response.data))

    def test_top_interest_posts_endpoint_filters_by_tag(self):
        user = User.objects.create_user(username="interest_posts_user", password="Password123!")
        Profile.objects.create(user=user, display_name="InterestPostsUser")
        self.client.force_authenticate(user=user)
        Post.objects.create(author=user, content="tech one", interest_tags=["tech"])
        Post.objects.create(author=user, content="design one", interest_tags=["design"])

        response = self.client.get("/api/v1/interests/top-posts?tag=tech")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all("tech" in item["interest_tags"] for item in response.data))

    def test_interest_suggestions_exclude_selected_tags(self):
        user = User.objects.create_user(username="interest_suggest_user", password="Password123!")
        Profile.objects.create(user=user, display_name="InterestSuggestUser")
        self.client.force_authenticate(user=user)
        Post.objects.create(author=user, content="a", interest_tags=["tech", "ai", "security"])
        Post.objects.create(author=user, content="b", interest_tags=["design", "ai"])

        response = self.client.get("/api/v1/interests/suggest?selected=tech")
        self.assertEqual(response.status_code, 200)
        tags = [item["tag"] for item in response.data]
        self.assertNotIn("tech", tags)
        self.assertIn("ai", tags)

    def test_interest_suggestions_support_query_filter(self):
        user = User.objects.create_user(username="interest_query_user", password="Password123!")
        Profile.objects.create(user=user, display_name="InterestQueryUser")
        self.client.force_authenticate(user=user)
        Post.objects.create(author=user, content="a", interest_tags=["tech", "ai", "security"])
        Post.objects.create(author=user, content="b", interest_tags=["design", "product"])

        response = self.client.get("/api/v1/interests/suggest?query=sec")
        self.assertEqual(response.status_code, 200)
        tags = [item["tag"] for item in response.data]
        self.assertIn("security", tags)
        self.assertNotIn("design", tags)
