from io import BytesIO
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from datetime import timedelta
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from PIL import Image
from rest_framework.test import APITestCase
from unittest.mock import patch

from apps.accounts.models import Profile, ProfileActionScore, SignupInvite, SiteSetting
from apps.accounts.ranking import record_profile_action_score
from apps.accounts.tasks import generate_algorithm_profile, refresh_active_profile_scores
from apps.ai_accounts.models import AiAccountProfile
from apps.connections.models import Connection
from apps.feed.sentiment_providers import get_sentiment_provider, score_sentiment_text
from apps.posts.models import Post
from apps.posts.models import PostInteraction

User = get_user_model()


class AccountsApiTests(APITestCase):
    def tearDown(self):
        get_sentiment_provider.cache_clear()
        super().tearDown()

    def test_signup_and_login(self):
        signup_payload = {
            "username": "alpha",
            "email": "alpha@example.com",
            "password": "Password123!",
            "date_of_birth": "2000-01-01",
            "gender": "prefer_not_to_say",
            "gender_self_describe": "",
            "zip_code": "10001",
            "country": "United States",
        }
        signup_response = self.client.post("/api/v1/auth/signup", signup_payload, format="json")
        self.assertEqual(signup_response.status_code, 201)
        self.assertIn("access", signup_response.data)

        login_response = self.client.post(
            "/api/v1/auth/login",
            {"username": "alpha", "password": "Password123!"},
            format="json",
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertIn("access", login_response.data)

    def test_signup_rejects_underage_user(self):
        payload = {
            "username": "too_young",
            "email": "young@example.com",
            "password": "Password123!",
            "date_of_birth": "2020-01-01",
            "gender": "female",
            "gender_self_describe": "",
            "zip_code": "75001",
            "country": "United States",
        }
        response = self.client.post("/api/v1/auth/signup", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("date_of_birth", response.data)

    def test_signup_requires_self_describe_text_when_selected(self):
        payload = {
            "username": "self_describe_missing",
            "email": "self-describe-missing@example.com",
            "password": "Password123!",
            "date_of_birth": "1998-06-10",
            "gender": "self_describe",
            "gender_self_describe": "",
            "zip_code": "02110",
            "country": "United States",
        }
        response = self.client.post("/api/v1/auth/signup", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("gender_self_describe", response.data)

    def test_signup_blocked_when_invite_only_without_valid_invite(self):
        settings_obj = SiteSetting.get_solo()
        settings_obj.register_via_invite_only = True
        settings_obj.save(update_fields=["register_via_invite_only", "updated_at"])
        payload = {
            "username": "blocked_signup_user",
            "email": "blocked@example.com",
            "password": "Password123!",
            "date_of_birth": "1998-01-01",
            "gender": "prefer_not_to_say",
            "gender_self_describe": "",
            "zip_code": "11111",
            "country": "United States",
        }
        response = self.client.post("/api/v1/auth/signup", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            str(response.data.get("non_field_errors", [""])[0]),
            "We are currenlty only allowing new accounts via invites only. If you have received an invite link, "
            "please follow that url to register.",
        )

    def test_signup_allows_valid_invite_and_marks_invite_used(self):
        settings_obj = SiteSetting.get_solo()
        settings_obj.register_via_invite_only = True
        settings_obj.save(update_fields=["register_via_invite_only", "updated_at"])
        invite = SignupInvite.objects.create(
            email="invited@example.com",
            token="invite_token_valid_123",
            expires_at=timezone.now() + timedelta(days=7),
        )
        payload = {
            "username": "invite_allowed_user",
            "email": "invited@example.com",
            "password": "Password123!",
            "date_of_birth": "1994-02-02",
            "gender": "prefer_not_to_say",
            "gender_self_describe": "",
            "zip_code": "22222",
            "country": "United States",
            "invite_token": invite.token,
        }
        response = self.client.post("/api/v1/auth/signup", payload, format="json")
        self.assertEqual(response.status_code, 201)
        invite.refresh_from_db()
        self.assertIsNotNone(invite.used_at)

    def test_signup_allows_qp_artifact_invite_token_after_normalization(self):
        settings_obj = SiteSetting.get_solo()
        settings_obj.register_via_invite_only = True
        settings_obj.save(update_fields=["register_via_invite_only", "updated_at"])
        invite = SignupInvite.objects.create(
            email="invited-normalized@example.com",
            token="C5ddwIfB796cYM9ynlJvF8wqHk-T0Lb4F7fHmyz0AvE",
            expires_at=timezone.now() + timedelta(days=7),
        )
        qp_like_token = f"3D{invite.token[:20]}={invite.token[20:]}"
        payload = {
            "username": "invite_normalized_user",
            "email": "invited-normalized@example.com",
            "password": "Password123!",
            "date_of_birth": "1994-02-02",
            "gender": "prefer_not_to_say",
            "gender_self_describe": "",
            "zip_code": "22222",
            "country": "United States",
            "invite_token": qp_like_token,
        }
        response = self.client.post("/api/v1/auth/signup", payload, format="json")
        self.assertEqual(response.status_code, 201)

    def test_signup_rejects_expired_invite_token(self):
        settings_obj = SiteSetting.get_solo()
        settings_obj.register_via_invite_only = True
        settings_obj.save(update_fields=["register_via_invite_only", "updated_at"])
        invite = SignupInvite.objects.create(
            email="expired@example.com",
            token="invite_token_expired_123",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        payload = {
            "username": "invite_expired_user",
            "email": "expired@example.com",
            "password": "Password123!",
            "date_of_birth": "1994-02-02",
            "gender": "prefer_not_to_say",
            "gender_self_describe": "",
            "zip_code": "22222",
            "country": "United States",
            "invite_token": invite.token,
        }
        response = self.client.post("/api/v1/auth/signup", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("non_field_errors", response.data)

    def test_signup_invite_validate_endpoint_returns_true_for_valid_token(self):
        invite = SignupInvite.objects.create(
            email="valid-check@example.com",
            token="invite_token_check_valid_123",
            expires_at=timezone.now() + timedelta(days=7),
        )
        response = self.client.get("/api/v1/auth/signup-invite/validate", {"token": invite.token}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(bool(response.data.get("is_valid")))
        self.assertEqual(str(response.data.get("invited_email")), "valid-check@example.com")

    def test_signup_invite_validate_endpoint_returns_false_for_missing_or_expired_token(self):
        expired = SignupInvite.objects.create(
            email="expired-check@example.com",
            token="invite_token_check_expired_123",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        missing_response = self.client.get("/api/v1/auth/signup-invite/validate", format="json")
        self.assertEqual(missing_response.status_code, 200)
        self.assertFalse(bool(missing_response.data.get("is_valid")))
        self.assertEqual(str(missing_response.data.get("invited_email")), "")
        expired_response = self.client.get("/api/v1/auth/signup-invite/validate", {"token": expired.token}, format="json")
        self.assertEqual(expired_response.status_code, 200)
        self.assertFalse(bool(expired_response.data.get("is_valid")))
        self.assertEqual(str(expired_response.data.get("invited_email")), "")

    def test_signup_invite_validate_endpoint_normalizes_qp_artifact_token(self):
        invite = SignupInvite.objects.create(
            email="qp-normalized@example.com",
            token="C5ddwIfB796cYM9ynlJvF8wqHk-T0Lb4F7fHmyz0AvE",
            expires_at=timezone.now() + timedelta(days=7),
        )
        qp_like_token = f"3D{invite.token[:24]}={invite.token[24:]}"
        response = self.client.get("/api/v1/auth/signup-invite/validate", {"token": qp_like_token}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(bool(response.data.get("is_valid")))
        self.assertEqual(str(response.data.get("invited_email")), "qp-normalized@example.com")

    def test_staff_site_settings_get_and_patch(self):
        admin_user = User.objects.create_user(
            username="site_settings_admin",
            email="site-settings-admin@example.com",
            password="Password123!",
            is_staff=True,
        )
        Profile.objects.create(user=admin_user, display_name="SiteSettingsAdmin")
        self.client.force_authenticate(user=admin_user)

        get_response = self.client.get("/api/v1/auth/site-settings")
        self.assertEqual(get_response.status_code, 200)
        self.assertIn("register_via_invite_only", get_response.data)
        self.assertIn("allowed_signup_countries", get_response.data)
        self.assertIn("frontend_base_url", get_response.data)
        self.assertIn("email_backend", get_response.data)
        self.assertIn("has_email_host_password", get_response.data)

        patch_response = self.client.patch(
            "/api/v1/auth/site-settings",
            {
                "register_via_invite_only": True,
                "allowed_signup_countries": ["United States", "Canada"],
                "site_name": "Unite Live",
                "support_email": "support@unite.example",
                "frontend_base_url": "https://unite.example",
                "default_from_email": "noreply@unite.example",
                "email_backend": "django.core.mail.backends.smtp.EmailBackend",
                "email_host": "smtp.unite.example",
                "email_port": 587,
                "email_host_user": "smtp-user",
                "email_host_password": "secret123",
                "email_use_tls": True,
                "email_use_ssl": False,
                "email_timeout_seconds": 12,
                "enforce_signup_ip_country_match": True,
                "allow_signup_on_ip_country_lookup_failure": False,
                "ip_country_lookup_timeout_seconds": 2.5,
                "ip_country_lookup_url_template": "https://geo.example/{ip}",
            },
            format="json",
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertTrue(patch_response.data["register_via_invite_only"])
        self.assertEqual(patch_response.data["allowed_signup_countries"], ["United States", "Canada"])
        self.assertEqual(patch_response.data["site_name"], "Unite Live")
        self.assertEqual(patch_response.data["frontend_base_url"], "https://unite.example")
        self.assertEqual(patch_response.data["email_host"], "smtp.unite.example")
        self.assertEqual(int(patch_response.data["email_port"]), 587)
        self.assertEqual(patch_response.data["email_host_user"], "smtp-user")
        self.assertNotIn("email_host_password", patch_response.data)
        self.assertTrue(bool(patch_response.data["has_email_host_password"]))

    def test_staff_site_settings_rejects_smtp_credentials_matching_admin_account(self):
        admin_user = User.objects.create_user(
            username="smtp_admin_user",
            email="smtp-admin@example.com",
            password="AdminPassword123!",
            is_staff=True,
        )
        Profile.objects.create(user=admin_user, display_name="SmtpAdmin")
        self.client.force_authenticate(user=admin_user)

        response_same_username = self.client.patch(
            "/api/v1/auth/site-settings",
            {"email_host_user": "smtp_admin_user"},
            format="json",
        )
        self.assertEqual(response_same_username.status_code, 400)
        self.assertIn("email_host_user", response_same_username.data)

        response_same_email = self.client.patch(
            "/api/v1/auth/site-settings",
            {"email_host_user": "smtp-admin@example.com"},
            format="json",
        )
        self.assertEqual(response_same_email.status_code, 400)
        self.assertIn("email_host_user", response_same_email.data)

        response_same_password = self.client.patch(
            "/api/v1/auth/site-settings",
            {"email_host_password": "AdminPassword123!"},
            format="json",
        )
        self.assertEqual(response_same_password.status_code, 400)
        self.assertIn("email_host_password", response_same_password.data)

    def test_signup_rejects_country_when_restriction_enabled(self):
        settings_obj = SiteSetting.get_solo()
        settings_obj.allowed_signup_countries = ["United States", "Canada"]
        settings_obj.save(update_fields=["allowed_signup_countries", "updated_at"])
        payload = {
            "username": "country_blocked_user",
            "email": "country-blocked@example.com",
            "password": "Password123!",
            "date_of_birth": "1998-01-01",
            "gender": "prefer_not_to_say",
            "gender_self_describe": "",
            "zip_code": "11111",
            "country": "France",
        }
        response = self.client.post("/api/v1/auth/signup", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(str(response.data.get("country", [""])[0]), "Signup is currently unavailable for your country.")

    @patch("apps.accounts.serializers.is_signup_country_valid_for_ip", return_value=False)
    def test_signup_rejects_when_ip_country_mismatch(self, mocked_ip_validation):
        payload = {
            "username": "ip_country_blocked_user",
            "email": "ip-country-blocked@example.com",
            "password": "Password123!",
            "date_of_birth": "1998-01-01",
            "gender": "prefer_not_to_say",
            "gender_self_describe": "",
            "zip_code": "11111",
            "country": "United States",
        }
        response = self.client.post("/api/v1/auth/signup", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            str(response.data.get("country", [""])[0]),
            "Selected country does not match your current network location.",
        )
        self.assertTrue(mocked_ip_validation.called)

    @patch("apps.accounts.serializers.is_signup_country_valid_for_ip", return_value=True)
    def test_signup_allows_when_ip_country_matches(self, mocked_ip_validation):
        payload = {
            "username": "ip_country_allowed_user",
            "email": "ip-country-allowed@example.com",
            "password": "Password123!",
            "date_of_birth": "1997-07-07",
            "gender": "prefer_not_to_say",
            "gender_self_describe": "",
            "zip_code": "12345",
            "country": "United States",
        }
        response = self.client.post("/api/v1/auth/signup", payload, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(mocked_ip_validation.called)

    def test_staff_can_send_signup_invite(self):
        admin_user = User.objects.create_user(
            username="invite_sender_admin",
            email="invite-sender-admin@example.com",
            password="Password123!",
            is_staff=True,
        )
        Profile.objects.create(user=admin_user, display_name="InviteSenderAdmin")
        self.client.force_authenticate(user=admin_user)

        response = self.client.post(
            "/api/v1/auth/site-settings/send-invite",
            {"email": "new-invitee@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        created_invite = SignupInvite.objects.get(email="new-invitee@example.com")
        self.assertTrue(created_invite.is_valid())
        self.assertEqual(created_invite.invited_by_id, admin_user.id)
        self.assertLessEqual(created_invite.expires_at, timezone.now() + timedelta(days=7, minutes=1))

    @patch("apps.accounts.views.send_signup_invite_email", side_effect=OSError("smtp unavailable"))
    def test_staff_send_signup_invite_returns_503_when_email_send_fails(self, _mocked_send):
        admin_user = User.objects.create_user(
            username="invite_sender_failure_admin",
            email="invite-sender-failure-admin@example.com",
            password="Password123!",
            is_staff=True,
        )
        Profile.objects.create(user=admin_user, display_name="InviteSenderFailureAdmin")
        self.client.force_authenticate(user=admin_user)
        response = self.client.post(
            "/api/v1/auth/site-settings/send-invite",
            {"email": "will-fail@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(SignupInvite.objects.filter(email="will-fail@example.com").count(), 0)

    def test_profile_get_and_patch(self):
        user = User.objects.create_user(
            username="beta",
            email="beta@example.com",
            password="Password123!",
        )
        Profile.objects.create(user=user, display_name="Beta")
        self.client.force_authenticate(user=user)

        get_response = self.client.get("/api/v1/profile/")
        self.assertEqual(get_response.status_code, 200)

        patch_response = self.client.patch(
            "/api/v1/profile/",
            {
                "bio": "Constructive conversation only.",
                "interests": ["tech", "design"],
                "profile_link_url": "https://example.com/profile",
            },
            format="json",
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.data["bio"], "Constructive conversation only.")
        self.assertEqual(patch_response.data["profile_link_url"], "https://example.com/profile")

    def test_date_of_birth_cannot_be_changed_after_signup(self):
        user = User.objects.create_user(
            username="immutable_dob_user",
            email="immutable-dob@example.com",
            password="Password123!",
        )
        Profile.objects.create(
            user=user,
            display_name="ImmutableDob",
            date_of_birth="1995-05-10",
            gender="male",
            gender_self_describe="",
            zip_code="94105",
            country="United States",
        )
        self.client.force_authenticate(user=user)
        response = self.client.patch(
            "/api/v1/profile/",
            {
                "date_of_birth": "1990-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("date_of_birth", response.data)

    def test_demographics_hidden_for_non_staff_profile_response(self):
        user = User.objects.create_user(
            username="non_staff_private_data",
            email="non-staff-private@example.com",
            password="Password123!",
        )
        Profile.objects.create(
            user=user,
            display_name="NonStaffData",
            date_of_birth="1992-09-14",
            gender="female",
            gender_self_describe="",
            zip_code="30301",
            country="United States",
        )
        self.client.force_authenticate(user=user)
        response = self.client.get("/api/v1/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("date_of_birth", response.data)
        self.assertNotIn("gender", response.data)
        self.assertNotIn("zip_code", response.data)
        self.assertNotIn("country", response.data)
        self.assertNotIn("gender_self_describe", response.data)

    def test_demographics_visible_for_staff_profile_and_public_profile(self):
        staff_user = User.objects.create_user(
            username="staff_demographics",
            email="staff-demographics@example.com",
            password="Password123!",
            is_staff=True,
        )
        target_user = User.objects.create_user(
            username="target_demographics",
            email="target-demographics@example.com",
            password="Password123!",
        )
        Profile.objects.create(
            user=staff_user,
            display_name="Staff Demographics",
            date_of_birth="1988-01-20",
            gender="male",
            gender_self_describe="",
            zip_code="10011",
            country="United States",
        )
        Profile.objects.create(
            user=target_user,
            display_name="Target Demographics",
            date_of_birth="1993-11-02",
            gender="self_describe",
            gender_self_describe="Agender",
            zip_code="M5V 2T6",
            country="Canada",
        )
        self.client.force_authenticate(user=staff_user)
        profile_response = self.client.get("/api/v1/profile/")
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(profile_response.data.get("date_of_birth"), "1988-01-20")
        self.assertEqual(profile_response.data.get("gender"), "male")
        self.assertEqual(profile_response.data.get("zip_code"), "10011")
        self.assertEqual(profile_response.data.get("country"), "United States")
        self.assertEqual(profile_response.data.get("gender_self_describe"), "")

        public_response = self.client.get(f"/api/v1/profile/users/{target_user.id}")
        self.assertEqual(public_response.status_code, 200)
        self.assertEqual(public_response.data.get("date_of_birth"), "1993-11-02")
        self.assertEqual(public_response.data.get("gender"), "self_describe")
        self.assertEqual(public_response.data.get("gender_self_describe"), "Agender")
        self.assertEqual(public_response.data.get("zip_code"), "M5V 2T6")
        self.assertEqual(public_response.data.get("country"), "Canada")

    def test_profile_settings_defaults_and_notification_dependency(self):
        user = User.objects.create_user(
            username="settings_user",
            email="settings@example.com",
            password="Password123!",
        )
        Profile.objects.create(user=user, display_name="Settings User")
        self.client.force_authenticate(user=user)
        get_response = self.client.get("/api/v1/profile/")
        self.assertEqual(get_response.status_code, 200)
        self.assertTrue(get_response.data["receive_notifications"])
        self.assertTrue(get_response.data["receive_email_notifications"])
        self.assertTrue(get_response.data["receive_push_notifications"])
        self.assertFalse(get_response.data["is_private_profile"])
        self.assertFalse(get_response.data["require_connection_approval"])

        patch_response = self.client.patch(
            "/api/v1/profile/",
            {
                "receive_notifications": False,
                "receive_email_notifications": True,
                "receive_push_notifications": True,
            },
            format="json",
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertFalse(patch_response.data["receive_notifications"])
        self.assertFalse(patch_response.data["receive_email_notifications"])
        self.assertFalse(patch_response.data["receive_push_notifications"])

    def test_profile_link_url_keeps_first_valid_url_when_multiple_provided(self):
        user = User.objects.create_user(
            username="profile_link_user",
            email="profile-link@example.com",
            password="Password123!",
        )
        Profile.objects.create(user=user, display_name="Profile Link User")
        self.client.force_authenticate(user=user)
        response = self.client.patch(
            "/api/v1/profile/",
            {
                "profile_link_url": "https://first.example.com/path and https://second.example.com/other",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["profile_link_url"], "https://first.example.com/path")

    def test_onboarding_interests_requires_five(self):
        user = User.objects.create_user(
            username="gamma",
            email="gamma@example.com",
            password="Password123!",
        )
        Profile.objects.create(user=user, display_name="Gamma")
        self.client.force_authenticate(user=user)
        bad_response = self.client.post(
            "/api/v1/onboarding/interests",
            {"interests": ["a", "b", "c", "d"]},
            format="json",
        )
        self.assertEqual(bad_response.status_code, 400)

        good_response = self.client.post(
            "/api/v1/onboarding/interests",
            {"interests": ["a", "b", "c", "d", "e"], "location": "us"},
            format="json",
        )
        self.assertEqual(good_response.status_code, 202)

    def test_password_reset_request_and_confirm_flow(self):
        user = User.objects.create_user(
            username="delta",
            email="delta@example.com",
            password="Password123!",
        )
        Profile.objects.create(user=user, display_name="Delta")

        request_response = self.client.post(
            "/api/v1/auth/password-reset/request",
            {"email": "delta@example.com"},
            format="json",
        )
        self.assertEqual(request_response.status_code, 202)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Reset your password", mail.outbox[0].alternatives[0][0])
        self.assertIn("http://localhost:5173/reset-password?uid=", mail.outbox[0].alternatives[0][0])
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        confirm_response = self.client.post(
            "/api/v1/auth/password-reset/confirm",
            {
                "uid": uid,
                "token": token,
                "new_password": "UpdatedPassword123!",
            },
            format="json",
        )
        self.assertEqual(confirm_response.status_code, 200)

        login_response = self.client.post(
            "/api/v1/auth/login",
            {"username": "delta", "password": "UpdatedPassword123!"},
            format="json",
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertIn("access", login_response.data)

    def test_password_reset_request_returns_generic_response_for_unknown_email(self):
        response = self.client.post(
            "/api/v1/auth/password-reset/request",
            {"email": "missing@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        self.assertNotIn("debug_reset", response.data)

    def test_password_reset_confirm_rejects_invalid_token(self):
        response = self.client.post(
            "/api/v1/auth/password-reset/confirm",
            {"uid": "bad-uid", "token": "bad-token", "new_password": "UpdatedPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_profile_includes_ai_badge_fields(self):
        user = User.objects.create_user(
            username="ai_profile_user",
            email="ai_profile@example.com",
            password="Password123!",
        )
        Profile.objects.create(user=user, display_name="AI Profile User")
        AiAccountProfile.objects.create(user=user, provider_name="local", model_name="gemma-2b")
        self.client.force_authenticate(user=user)

        response = self.client.get("/api/v1/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_ai_account"])
        self.assertTrue(response.data["ai_badge_enabled"])

    def test_profile_includes_is_staff(self):
        user = User.objects.create_user(
            username="staff_profile_user",
            email="staff_profile@example.com",
            password="Password123!",
            is_staff=True,
        )
        Profile.objects.create(user=user, display_name="Staff Profile")
        self.client.force_authenticate(user=user)
        response = self.client.get("/api/v1/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_staff"])

    def test_public_profile_is_redacted_for_private_non_connection_or_blocked(self):
        owner = User.objects.create_user(
            username="private_owner",
            email="private-owner@example.com",
            password="Password123!",
        )
        viewer = User.objects.create_user(
            username="private_viewer",
            email="private-viewer@example.com",
            password="Password123!",
        )
        Profile.objects.create(
            user=owner,
            display_name="Private Owner",
            bio="Visible bio",
            location="US",
            profile_link_url="https://owner.example.com",
            interests=["music"],
            is_private_profile=True,
        )
        Profile.objects.create(user=viewer, display_name="Private Viewer")
        self.client.force_authenticate(user=viewer)
        hidden_response = self.client.get(f"/api/v1/profile/users/{owner.id}")
        self.assertEqual(hidden_response.status_code, 200)
        self.assertTrue(hidden_response.data["is_limited_view"])
        self.assertFalse(hidden_response.data["can_view_feed"])
        self.assertNotIn("interests", hidden_response.data)
        self.assertEqual(hidden_response.data.get("profile_link_url"), "https://owner.example.com")

        Connection.objects.create(requester=viewer, recipient=owner, status=Connection.Status.ACCEPTED)
        visible_response = self.client.get(f"/api/v1/profile/users/{owner.id}")
        self.assertEqual(visible_response.status_code, 200)
        self.assertFalse(visible_response.data["is_limited_view"])
        self.assertTrue(visible_response.data["can_view_feed"])
        self.assertIn("interests", visible_response.data)

        Connection.objects.update_or_create(
            requester=owner,
            recipient=viewer,
            defaults={"status": Connection.Status.BLOCKED},
        )
        blocked_response = self.client.get(f"/api/v1/profile/users/{owner.id}")
        self.assertEqual(blocked_response.status_code, 200)
        self.assertTrue(blocked_response.data["is_limited_view"])
        self.assertTrue(blocked_response.data["is_blocked_view"])

    def test_profile_image_upload_optimizes_to_square(self):
        user = User.objects.create_user(
            username="profile_image_user",
            email="profile_image@example.com",
            password="Password123!",
        )
        Profile.objects.create(user=user, display_name="ProfileImageUser")
        self.client.force_authenticate(user=user)
        image = Image.new("RGB", (400, 240), color=(120, 150, 200))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        upload = SimpleUploadedFile("input.png", buffer.getvalue(), content_type="image/png")

        response = self.client.post(
            "/api/v1/profile/image",
            {"image": upload, "crop_x": 20, "crop_y": 10, "crop_size": 180},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["profile_image_url"])

    def test_generate_algorithm_profile_builds_weighted_interest_signals(self):
        user = User.objects.create_user(
            username="algo_vector_user",
            email="algo-vector@example.com",
            password="Password123!",
        )
        profile = Profile.objects.create(
            user=user,
            display_name="Algo Vector User",
            interests=["Tech", "Science", "Design", "Music", "Travel"],
        )
        target_post = Post.objects.create(author=user, content="AI systems", interest_tags=["tech", "ai"])
        other_post = Post.objects.create(author=user, content="Art systems", interest_tags=["design"])
        PostInteraction.objects.create(
            post=target_post,
            user=user,
            action_type=PostInteraction.ActionType.REPLY,
            content="Constructive take",
        )
        PostInteraction.objects.create(
            post=other_post,
            user=user,
            action_type=PostInteraction.ActionType.LIKE,
        )

        result = generate_algorithm_profile(profile.id, "global")
        self.assertEqual(result["status"], "ok")
        profile.refresh_from_db()
        self.assertEqual(profile.algorithm_profile_status, Profile.AlgorithmProfileStatus.READY)
        self.assertIn("interest_weights", profile.algorithm_vector)
        self.assertGreater(profile.algorithm_vector["interest_weights"].get("tech", 0), 0)
        self.assertGreater(
            profile.algorithm_vector["interest_weights"].get("tech", 0),
            profile.algorithm_vector["interest_weights"].get("design", 0),
        )
        self.assertGreaterEqual(profile.algorithm_vector.get("positive_dialogue_bias", 0), 0.55)
        self.assertIn("signal_totals", profile.algorithm_vector)

    @override_settings(
        UNITE_PROFILE_REFRESH_COOLDOWN_SECONDS=60,
        UNITE_PROFILE_REFRESH_MIN_POSTS=1,
        UNITE_PROFILE_REFRESH_MIN_INTERACTIONS=1,
    )
    @patch("apps.accounts.tasks.generate_algorithm_profile.delay")
    def test_refresh_active_profile_scores_respects_activity_and_cooldown(self, mocked_delay):
        active_user = User.objects.create_user(
            username="refresh_active_user",
            email="refresh-active@example.com",
            password="Password123!",
        )
        active_profile = Profile.objects.create(
            user=active_user,
            display_name="RefreshActive",
            interests=["tech", "ai", "design", "science", "travel"],
        )
        stale_user = User.objects.create_user(
            username="refresh_inactive_user",
            email="refresh-inactive@example.com",
            password="Password123!",
        )
        stale_profile = Profile.objects.create(
            user=stale_user,
            display_name="RefreshInactive",
            interests=["music", "books", "movies", "food", "sports"],
        )
        recent_user = User.objects.create_user(
            username="refresh_recent_user",
            email="refresh-recent@example.com",
            password="Password123!",
        )
        recent_profile = Profile.objects.create(
            user=recent_user,
            display_name="RefreshRecent",
            interests=["gaming", "coding", "photography", "nature", "travel"],
        )
        Post.objects.create(author=active_user, content="active post", interest_tags=["tech"])
        PostInteraction.objects.create(
            post=Post.objects.create(author=active_user, content="active target", interest_tags=["tech"]),
            user=active_user,
            action_type=PostInteraction.ActionType.LIKE,
        )
        Post.objects.create(author=stale_user, content="inactive post", interest_tags=["music"])
        Profile.objects.filter(id=active_profile.id).update(updated_at=timezone.now() - timedelta(seconds=120))
        Profile.objects.filter(id=stale_profile.id).update(updated_at=timezone.now() - timedelta(seconds=120))
        # Recent profile should be excluded by cooldown.
        Post.objects.create(author=recent_user, content="recent post", interest_tags=["coding"])
        PostInteraction.objects.create(
            post=Post.objects.create(author=recent_user, content="recent target", interest_tags=["coding"]),
            user=recent_user,
            action_type=PostInteraction.ActionType.LIKE,
        )
        recent_profile.save(update_fields=["updated_at"])

        result = refresh_active_profile_scores(limit=10)
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["count"], 1)
        mocked_delay.assert_called_once_with(active_profile.id, active_profile.location or "global")

    def test_profile_rollup_uses_latest_500_actions(self):
        user = User.objects.create_user(
            username="rolling_user",
            email="rolling@example.com",
            password="Password123!",
        )
        profile = Profile.objects.create(user=user, display_name="Rolling User")
        for _ in range(520):
            record_profile_action_score(
                profile=profile,
                action_type=ProfileActionScore.ActionType.LIKE,
                sentiment_label="positive",
                sentiment_score=0.5,
                metadata={"test": "rolling"},
            )
        profile.refresh_from_db()
        self.assertEqual(profile.rank_last_500_count, 500)
        self.assertIn("like", profile.rank_action_scores)

    @override_settings(UNITE_SENTIMENT_RANKING_PROVIDER="unsupported-provider")
    def test_sentiment_provider_marks_neutral_for_rescore_when_provider_invalid(self):
        get_sentiment_provider.cache_clear()
        result = score_sentiment_text("This is a great and helpful day.")
        self.assertEqual(result.label, "neutral")
        self.assertEqual(float(result.score), 0.0)
        self.assertTrue(result.needs_rescore)
