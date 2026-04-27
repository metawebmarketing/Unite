import threading
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections, transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Profile
from apps.accounts.serializers import AuthResponseSerializer, build_auth_payload
from apps.install.models import InstallState
from apps.install.serializers import InstallRunSerializer, InstallStatusSerializer
from apps.install.tasks import seed_demo_data_task
from apps.posts.models import Post
from apps.feed.cache_utils import bump_user_feed_cache_version

User = get_user_model()


def _get_install_state() -> InstallState:
    state, _ = InstallState.objects.get_or_create(id=1)
    return state


def _dispatch_seed_task(*, install_state_id: int, total_users: int, total_posts: int) -> str:
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        task_id = f"local-{uuid.uuid4().hex[:12]}"

        def _run_seed_locally() -> None:
            close_old_connections()
            try:
                seed_demo_data_task(
                    install_state_id=install_state_id,
                    total_users=total_users,
                    total_posts=total_posts,
                )
            finally:
                close_old_connections()

        worker = threading.Thread(
            target=_run_seed_locally,
            name=f"seed-demo-{install_state_id}",
            daemon=True,
        )
        worker.start()
        return task_id

    result = seed_demo_data_task.delay(
        install_state_id=install_state_id,
        total_users=total_users,
        total_posts=total_posts,
    )
    return str(result.id)


class InstallStatusView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        state = _get_install_state()
        payload = {
            "installed": bool(state.installed),
            "installed_at": state.installed_at,
            "seed_requested": bool(state.seed_requested),
            "seed_status": state.seed_status,
            "seed_task_id": state.seed_task_id,
            "seed_total_users": state.seed_total_users,
            "seed_total_posts": state.seed_total_posts,
            "seed_created_users": state.seed_created_users,
            "seed_created_posts": state.seed_created_posts,
            "seed_last_message": state.seed_last_message,
        }
        response = Response(InstallStatusSerializer(payload).data)
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        return response


class InstallRunView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = InstallRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            state = _get_install_state()
            if state.installed:
                return Response(
                    {"detail": "Install has already completed."},
                    status=status.HTTP_409_CONFLICT,
                )

            user = User.objects.create_superuser(
                username=serializer.validated_data["username"],
                email=serializer.validated_data["email"],
                password=serializer.validated_data["password"],
            )
            Profile.objects.create(
                user=user,
                display_name=serializer.validated_data.get("display_name") or user.username,
                location=serializer.validated_data.get("location", "").strip(),
                interests=["tech", "design", "science", "travel", "music"],
            )

            state.installed = True
            state.installed_at = timezone.now()
            state.master_admin_user_id = user.id
            state.seed_requested = bool(serializer.validated_data.get("seed_demo_data", False))
            state.seed_status = "queued" if state.seed_requested else "not_requested"
            state.seed_task_id = ""
            state.seed_total_users = serializer.validated_data.get("seed_total_users", 0)
            state.seed_total_posts = serializer.validated_data.get("seed_total_posts", 0)
            state.seed_created_users = 0
            state.seed_created_posts = 0
            state.seed_last_message = "Seed queued." if state.seed_requested else ""
            state.save(
                update_fields=[
                    "installed",
                    "installed_at",
                    "master_admin_user_id",
                    "seed_requested",
                    "seed_status",
                    "seed_task_id",
                    "seed_total_users",
                    "seed_total_posts",
                    "seed_created_users",
                    "seed_created_posts",
                    "seed_last_message",
                    "updated_at",
                ]
            )

        if state.seed_requested:
            task_id = _dispatch_seed_task(
                install_state_id=state.id,
                total_users=state.seed_total_users,
                total_posts=state.seed_total_posts,
            )
            InstallState.objects.filter(id=state.id).update(
                seed_task_id=task_id,
                seed_status="queued",
                seed_last_message="Seed queued.",
            )
            state.seed_task_id = task_id

        auth_payload = build_auth_payload(user)
        response_payload = {
            "auth": AuthResponseSerializer(auth_payload).data,
            "seed_requested": state.seed_requested,
            "seed_status": state.seed_status,
            "seed_task_id": state.seed_task_id,
        }
        return Response(response_payload, status=status.HTTP_201_CREATED)


class DemoDataResetView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        if not getattr(settings, "UNITE_ALLOW_LOCAL_DEMO_RESET", False):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        requested_total_users = request.data.get("seed_total_users", None)
        requested_total_posts = request.data.get("seed_total_posts", None)
        demo_users = User.objects.filter(username__startswith="demo_user_")
        removed_users = demo_users.count()
        removed_posts = Post.objects.filter(author_id__in=demo_users.values_list("id", flat=True)).count()
        demo_users.delete()

        state = _get_install_state()
        seed_total_users = state.seed_total_users or 1000
        seed_total_posts = state.seed_total_posts or 10000
        try:
            if requested_total_users is not None:
                seed_total_users = max(1, min(10000, int(requested_total_users)))
            if requested_total_posts is not None:
                seed_total_posts = max(1, min(200000, int(requested_total_posts)))
        except (TypeError, ValueError):
            return Response(
                {"detail": "seed_total_users and seed_total_posts must be valid integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        state.seed_requested = True
        state.seed_status = "queued"
        state.seed_total_users = seed_total_users
        state.seed_total_posts = seed_total_posts
        state.seed_created_users = 0
        state.seed_created_posts = 0
        state.seed_last_message = "Seed regeneration queued."
        state.save(
            update_fields=[
                "seed_requested",
                "seed_status",
                "seed_total_users",
                "seed_total_posts",
                "seed_created_users",
                "seed_created_posts",
                "seed_last_message",
                "updated_at",
            ]
        )
        task_id = _dispatch_seed_task(
            install_state_id=state.id,
            total_users=state.seed_total_users,
            total_posts=state.seed_total_posts,
        )
        state.seed_task_id = task_id
        state.save(update_fields=["seed_task_id", "updated_at"])
        bump_user_feed_cache_version(request.user.id)
        return Response(
            {
                "removed_users": removed_users,
                "removed_posts": removed_posts,
                "seed_status": state.seed_status,
                "seed_task_id": state.seed_task_id,
            },
            status=status.HTTP_202_ACCEPTED,
        )
