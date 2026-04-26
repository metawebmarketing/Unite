from celery import shared_task
from django.contrib.auth import get_user_model

from apps.accounts.models import Profile
from apps.install.models import InstallState
from apps.posts.models import Post

User = get_user_model()


@shared_task
def seed_demo_data_task(
    *,
    install_state_id: int = 1,
    total_users: int = 1000,
    posts_per_user: int = 10,
) -> dict:
    created_users = 0
    created_posts = 0
    created_records = 0
    default_interests = ["tech", "design", "music", "travel", "science", "gaming"]
    total_posts = total_users * posts_per_user
    total_records = total_users + total_posts
    InstallState.objects.filter(id=install_state_id).update(
        seed_status="running",
        seed_total_users=total_users,
        seed_total_posts=total_posts,
        seed_created_users=0,
        seed_created_posts=0,
        seed_last_message=f"Seeding demo data... (0/{total_records} records)",
    )
    try:
        for index in range(total_users):
            username = f"demo_user_{index + 1:04d}"
            email = f"{username}@example.local"
            user, user_created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "is_active": True,
                },
            )
            if user_created:
                user.set_password("Password123!")
                user.save()
                Profile.objects.create(
                    user=user,
                    display_name=f"Demo User {index + 1}",
                    interests=default_interests[:5],
                )
                created_users += 1
                created_records += 1
                InstallState.objects.filter(id=install_state_id).update(
                    seed_created_users=created_users,
                    seed_created_posts=created_posts,
                    seed_last_message=(
                        f"Record {created_records}/{total_records}: "
                        f"created account Demo User {index + 1} ({username})."
                    ),
                )

            for post_index in range(posts_per_user):
                interest_tag = default_interests[(index + post_index) % len(default_interests)]
                post_content = (
                    f"{username} sharing update #{post_index + 1}: "
                    f"exploring {interest_tag}, building positive community dialogue."
                )
                Post.objects.create(
                    author=user,
                    content=post_content,
                    interest_tags=[interest_tag],
                )
                InstallState.objects.filter(id=install_state_id).update(
                    seed_created_users=created_users,
                    seed_created_posts=created_posts + 1,
                    seed_last_message=(
                        f"Record {created_records + 1}/{total_records}: "
                        f"created post for {username} - \"{post_content[:72]}\""
                    ),
                )
                created_posts += 1
                created_records += 1
        InstallState.objects.filter(id=install_state_id).update(
            seed_status="completed",
            seed_created_users=created_users,
            seed_created_posts=created_posts,
            seed_last_message=f"Demo data creation complete ({created_records}/{total_records} records).",
        )
        return {
            "status": "ok",
            "created_users": created_users,
            "created_posts": created_posts,
        }
    except Exception as exc:
        InstallState.objects.filter(id=install_state_id).update(
            seed_status="failed",
            seed_last_message=f"Seed failed: {exc}",
            seed_created_users=created_users,
            seed_created_posts=created_posts,
        )
        raise
