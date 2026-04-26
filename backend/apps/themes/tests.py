from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.accounts.models import Profile

User = get_user_model()


class ThemesApiTests(APITestCase):
    def test_upload_theme(self):
        user = User.objects.create_user(username="theme_user", password="Password123!", is_staff=True)
        Profile.objects.create(user=user, display_name="ThemeUser")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/themes/upload",
            {
                "name": "dark_plus",
                "version": "v1",
                "tokens": {
                    "colors": {
                        "background": "#000",
                        "surface": "#111",
                        "textPrimary": "#ffffff",
                        "border": "#222222",
                    },
                    "spacing": {"sm": 4, "md": 8},
                    "radius": {"md": 8},
                    "typography": {"base": 16},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["is_active"])

    def test_upload_theme_forbidden_for_non_staff(self):
        user = User.objects.create_user(username="theme_member", password="Password123!")
        Profile.objects.create(user=user, display_name="ThemeMember")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/themes/upload",
            {
                "name": "dark_plus",
                "version": "v1",
                "tokens": {
                    "colors": {"background": "#000"},
                    "spacing": {"sm": 4},
                    "radius": {"md": 8},
                    "typography": {"base": 16},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_upload_theme_rejects_invalid_color_token(self):
        user = User.objects.create_user(username="theme_bad_color", password="Password123!", is_staff=True)
        Profile.objects.create(user=user, display_name="ThemeBadColor")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/themes/upload",
            {
                "name": "bad_theme",
                "version": "v1",
                "tokens": {
                    "colors": {
                        "background": "not-a-hex",
                        "surface": "#111",
                        "textPrimary": "#ffffff",
                        "border": "#222222",
                    },
                    "spacing": {"sm": 4, "md": 8},
                    "radius": {"md": 8},
                    "typography": {"base": 16},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_upload_theme_rejects_out_of_range_numeric_tokens(self):
        user = User.objects.create_user(username="theme_bad_numeric", password="Password123!", is_staff=True)
        Profile.objects.create(user=user, display_name="ThemeBadNumeric")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/themes/upload",
            {
                "name": "bad_theme_numeric",
                "version": "v1",
                "tokens": {
                    "colors": {
                        "background": "#000",
                        "surface": "#111",
                        "textPrimary": "#fff",
                        "border": "#222",
                    },
                    "spacing": {"sm": -2, "md": 8},
                    "radius": {"md": 8},
                    "typography": {"base": 16},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
