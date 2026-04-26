from celery import shared_task
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import Profile
from apps.connections.models import Connection
from apps.install.models import InstallState
from apps.posts.models import Post, PostInteraction

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
    created_connections = 0
    created_interactions = 0
    created_records = 0
    now = timezone.now()
    rng = random.Random(20260425)
    interest_pool = [
        "tech",
        "design",
        "music",
        "travel",
        "science",
        "gaming",
        "finance",
        "health",
        "books",
        "movies",
        "sports",
        "photography",
        "fitness",
        "education",
        "ai",
        "startups",
    ]
    content_templates = [
        "{username} update #{post_number}: shipping a small improvement around {interest}.",
        "{username} experimenting with {interest} and sharing early notes.",
        "{username} thread #{post_number}: what worked this week in {interest}.",
        "{username} quick take on {interest} trends and practical wins.",
        "{username} reflecting on community feedback in {interest}.",
    ]
    demo_users: list = []
    user_posts: dict[int, list[dict]] = {}
    all_post_refs: list[dict] = []
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
                selected_interests = rng.sample(interest_pool, k=5)
                Profile.objects.create(
                    user=user,
                    display_name=f"Demo User {index + 1}",
                    interests=selected_interests,
                )
                profile_created_at = now - timedelta(days=rng.randint(2, 360), hours=rng.randint(0, 23))
                Profile.objects.filter(user=user).update(created_at=profile_created_at, updated_at=profile_created_at)
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
            demo_users.append(user)
            profile = getattr(user, "profile", None)
            profile_interests = list(getattr(profile, "interests", []) or interest_pool[:5])
            user_posts[user.id] = []

            for post_index in range(posts_per_user):
                primary_interest = profile_interests[(post_index + index) % len(profile_interests)]
                extra_interest = rng.choice(interest_pool)
                post_interests = [primary_interest] if extra_interest == primary_interest else [primary_interest, extra_interest]
                post_content = rng.choice(content_templates).format(
                    username=username,
                    post_number=post_index + 1,
                    interest=primary_interest,
                )
                created_at = now - timedelta(days=rng.randint(0, 365), hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
                post = Post.objects.create(
                    author=user,
                    content=post_content,
                    interest_tags=post_interests,
                )
                Post.objects.filter(id=post.id).update(created_at=created_at, updated_at=created_at)
                post.is_pinned = False
                user_posts[user.id].append(
                    {
                        "id": post.id,
                        "created_at": created_at,
                        "author_id": user.id,
                    }
                )
                all_post_refs.append(
                    {
                        "id": post.id,
                        "created_at": created_at,
                        "author_id": user.id,
                    }
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

        # Build accepted connections with a deterministic ring + skip links.
        total_demo_users = len(demo_users)
        for index, user in enumerate(demo_users):
            if total_demo_users <= 1:
                break
            for step in (1, 3):
                target = demo_users[(index + step) % total_demo_users]
                if target.id == user.id:
                    continue
                connection, was_created = Connection.objects.get_or_create(
                    requester=user,
                    recipient=target,
                    defaults={"status": Connection.Status.ACCEPTED},
                )
                if connection.status != Connection.Status.ACCEPTED:
                    connection.status = Connection.Status.ACCEPTED
                    connection.save(update_fields=["status", "updated_at"])
                if was_created:
                    created_connections += 1

        # Pin a subset of posts so pin surfaces are exercised.
        for user in demo_users:
            posts_for_user = user_posts.get(user.id, [])
            if not posts_for_user:
                continue
            pinned_ref = max(posts_for_user, key=lambda item: item["created_at"])
            Post.objects.filter(id=pinned_ref["id"]).update(is_pinned=True, updated_at=now)

        # Add likes/reposts/bookmarks/replies on other users' posts.
        for index, user in enumerate(demo_users):
            interaction_targets: list[dict] = []
            for step in range(1, 7):
                target_user = demo_users[(index + step * 7) % total_demo_users]
                if target_user.id == user.id:
                    continue
                candidates = user_posts.get(target_user.id, [])
                if candidates:
                    interaction_targets.append(candidates[step % len(candidates)])
            if not interaction_targets:
                continue
            for target in interaction_targets:
                for action in (
                    PostInteraction.ActionType.LIKE,
                    PostInteraction.ActionType.REPOST,
                    PostInteraction.ActionType.BOOKMARK,
                ):
                    interaction, was_created = PostInteraction.objects.get_or_create(
                        post_id=target["id"],
                        user=user,
                        action_type=action,
                        defaults={"content": ""},
                    )
                    if was_created:
                        created_interactions += 1
                        if action in {PostInteraction.ActionType.REPOST, PostInteraction.ActionType.BOOKMARK}:
                            stamp = target["created_at"] + timedelta(hours=rng.randint(1, 120))
                            PostInteraction.objects.filter(id=interaction.id).update(created_at=stamp)
                if rng.random() < 0.55:
                    reply = PostInteraction.objects.create(
                        post_id=target["id"],
                        user=user,
                        action_type=PostInteraction.ActionType.REPLY,
                        content=f"Reply from {user.username} on post {target['id']} with constructive context.",
                    )
                    created_interactions += 1
                    reply_stamp = target["created_at"] + timedelta(hours=rng.randint(2, 160))
                    PostInteraction.objects.filter(id=reply.id).update(created_at=reply_stamp)

        InstallState.objects.filter(id=install_state_id).update(
            seed_status="completed",
            seed_created_users=created_users,
            seed_created_posts=created_posts,
            seed_last_message=(
                "Demo data creation complete "
                f"({created_records}/{total_records} base records, "
                f"{created_connections} connections, {created_interactions} interactions)."
            ),
        )
        return {
            "status": "ok",
            "created_users": created_users,
            "created_posts": created_posts,
            "created_connections": created_connections,
            "created_interactions": created_interactions,
        }
    except Exception as exc:
        InstallState.objects.filter(id=install_state_id).update(
            seed_status="failed",
            seed_last_message=f"Seed failed: {exc}",
            seed_created_users=created_users,
            seed_created_posts=created_posts,
        )
        raise
