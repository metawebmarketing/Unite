from celery import shared_task
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.ranking import record_profile_action_score, recompute_profile_rank_rollups, score_post_sentiment
from apps.accounts.models import Profile
from apps.connections.models import Connection
from apps.feed.sentiment_providers import score_sentiment_text
from apps.feed.cache_utils import bump_user_feed_cache_version
from apps.install.demo_corpus import load_demo_post_corpus
from apps.install.models import InstallState
from apps.install.realtime import broadcast_install_state
from apps.messaging.models import DMMessage, DMThread, DMThreadParticipant
from apps.notifications.services import create_notification
from apps.posts.models import Post, PostInteraction

User = get_user_model()


@shared_task
def seed_demo_data_task(
    *,
    install_state_id: int = 1,
    total_users: int = 1000,
    total_posts: int = 10000,
) -> dict:
    total_users = max(1, int(total_users))
    total_posts = max(1, int(total_posts))
    created_users = 0
    created_posts = 0
    created_connections = 0
    created_interactions = 0
    created_reply_posts = 0
    created_dm_messages = 0
    created_mention_notifications = 0
    created_records = 0
    now = timezone.now()
    rng = random.Random()
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
    demo_post_corpus = load_demo_post_corpus()
    if not demo_post_corpus:
        raise ValueError("Demo post corpus is missing or empty. Generate backend/apps/install/data/demo_posts_10000.json.")
    demo_users: list = []
    user_posts: dict[int, list[dict]] = {}
    user_joined_at_by_id: dict[int, object] = {}
    post_rank_context: dict[int, dict] = {}
    touched_profile_ids: set[int] = set()
    posts_per_user_floor = total_posts // total_users
    extra_posts = total_posts % total_users
    total_records = total_users + total_posts
    install_state_snapshot = InstallState.objects.filter(id=install_state_id).values(
        "master_admin_user_id",
        "seed_requested_by_user_id",
    ).first()
    seed_requester_user_id = int((install_state_snapshot or {}).get("seed_requested_by_user_id") or 0)
    if seed_requester_user_id <= 0:
        seed_requester_user_id = int((install_state_snapshot or {}).get("master_admin_user_id") or 0)

    def random_between(start_at, end_at):
        if start_at >= end_at:
            return start_at
        total_seconds = int((end_at - start_at).total_seconds())
        return start_at + timedelta(seconds=rng.randint(0, max(1, total_seconds)))

    def ensure_dm_thread_for_users(user_one_id: int, user_two_id: int) -> DMThread:
        left_id, right_id = (user_one_id, user_two_id) if user_one_id < user_two_id else (user_two_id, user_one_id)
        thread, _ = DMThread.objects.get_or_create(user_a_id=left_id, user_b_id=right_id)
        DMThreadParticipant.objects.get_or_create(thread=thread, user_id=left_id)
        DMThreadParticipant.objects.get_or_create(thread=thread, user_id=right_id)
        return thread

    InstallState.objects.filter(id=install_state_id).update(
        seed_status="running",
        seed_total_users=total_users,
        seed_total_posts=total_posts,
        seed_created_users=0,
        seed_created_posts=0,
        seed_last_message=f"Seeding demo data... (0/{total_records} records)",
    )
    broadcast_install_state(install_state_id)
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
                selected_interests = rng.sample(interest_pool, k=rng.randint(5, 8))
                user_joined_at = now - timedelta(days=rng.randint(20, 740), hours=rng.randint(0, 23))
                User.objects.filter(id=user.id).update(
                    date_joined=user_joined_at,
                    last_login=user_joined_at + timedelta(days=rng.randint(1, 15)),
                )
                Profile.objects.create(
                    user=user,
                    display_name=f"Demo User {index + 1}",
                    bio=f"Building around {selected_interests[0]} and tracking community outcomes.",
                    interests=selected_interests,
                )
                profile_created_at = user_joined_at + timedelta(days=rng.randint(0, 12), hours=rng.randint(0, 23))
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
                broadcast_install_state(install_state_id)
                account_created_at = user_joined_at
            else:
                account_created_at = getattr(user, "date_joined", now - timedelta(days=30))
            user_joined_at_by_id[user.id] = account_created_at
            demo_users.append(user)
            profile = getattr(user, "profile", None)
            profile_interests = list(getattr(profile, "interests", []) or interest_pool[:5])
            user_posts[user.id] = []
            post_count_for_user = posts_per_user_floor + (1 if index < extra_posts else 0)

            for post_index in range(post_count_for_user):
                corpus_index = (index * max(1, posts_per_user_floor) + post_index + rng.randint(0, 97)) % len(demo_post_corpus)
                corpus_entry = demo_post_corpus[corpus_index]
                post_content = str(corpus_entry.get("content", "")).strip()
                if not post_content:
                    continue
                corpus_tags = [
                    tag
                    for tag in corpus_entry.get("interest_tags", [])
                    if isinstance(tag, str) and tag.strip()
                ]
                primary_interest = (
                    corpus_tags[0]
                    if corpus_tags
                    else profile_interests[(post_index + index) % len(profile_interests)]
                )
                post_interests = corpus_tags[:3] if corpus_tags else [primary_interest]
                if len(post_interests) < 2:
                    fallback_interest = rng.choice(profile_interests or interest_pool)
                    if fallback_interest not in post_interests:
                        post_interests.append(fallback_interest)
                created_at = random_between(account_created_at, now)
                link_url = str(corpus_entry.get("link_url", "")).strip()
                link_preview = corpus_entry.get("link_preview", {}) if isinstance(corpus_entry.get("link_preview"), dict) else {}
                post = Post.objects.create(
                    author=user,
                    content=post_content,
                    interest_tags=post_interests,
                    visibility=Post.Visibility.CONNECTIONS if rng.random() < 0.2 else Post.Visibility.PUBLIC,
                    link_url=link_url,
                    link_preview=link_preview,
                    tagged_user_ids=(
                        [seed_requester_user_id]
                        if seed_requester_user_id > 0
                        and seed_requester_user_id != user.id
                        and rng.random() < 0.03
                        else []
                    ),
                )
                if (
                    seed_requester_user_id > 0
                    and isinstance(post.tagged_user_ids, list)
                    and seed_requester_user_id in post.tagged_user_ids
                    and created_mention_notifications < 50
                ):
                    created_mention_notifications += 1
                    create_notification(
                        recipient_user_id=seed_requester_user_id,
                        actor_user_id=user.id,
                        event_type="post.mention",
                        title="You were tagged in demo data",
                        message=f"@{user.username} mentioned you in seeded content.",
                        payload={"post_id": int(post.id), "source": "seed_demo"},
                    )
                Post.objects.filter(id=post.id).update(created_at=created_at, updated_at=created_at)
                post.is_pinned = False
                post_sentiment_label, post_sentiment_score = score_post_sentiment(post)
                post_rank_context[post.id] = {
                    "sentiment_label": post_sentiment_label,
                    "sentiment_score": post_sentiment_score,
                    "is_toxic": False,
                }
                user_posts[user.id].append(
                    {
                        "id": post.id,
                        "created_at": created_at,
                        "author_id": user.id,
                        "interest": primary_interest,
                    }
                )
                if profile:
                    record_profile_action_score(
                        profile=profile,
                        action_type="post",
                        sentiment_label=post_sentiment_label,
                        sentiment_score=post_sentiment_score,
                        post=post,
                        metadata={"source": "seed_demo"},
                        recompute_rollup=False,
                    )
                    touched_profile_ids.add(profile.id)
                InstallState.objects.filter(id=install_state_id).update(
                    seed_created_users=created_users,
                    seed_created_posts=created_posts + 1,
                    seed_last_message=(
                        f"Record {created_records + 1}/{total_records}: "
                        f"created post for {username} - \"{post_content[:72]}\""
                    ),
                )
                broadcast_install_state(install_state_id)
                created_posts += 1
                created_records += 1

        # Build accepted/pending/blocked connections for richer graph coverage.
        total_demo_users = len(demo_users)
        for index, user in enumerate(demo_users):
            if total_demo_users <= 1:
                break
            for step in (1, 3, 5):
                target = demo_users[(index + step) % total_demo_users]
                if target.id == user.id:
                    continue
                connection, was_created = Connection.objects.get_or_create(
                    requester=user,
                    recipient=target,
                    defaults={
                        "status": (
                            Connection.Status.ACCEPTED
                            if step in (1, 3)
                            else (Connection.Status.BLOCKED if index % 20 == 0 else Connection.Status.PENDING)
                        )
                    },
                )
                desired_status = (
                    Connection.Status.ACCEPTED
                    if step in (1, 3)
                    else (Connection.Status.BLOCKED if index % 20 == 0 else Connection.Status.PENDING)
                )
                if connection.status != desired_status:
                    connection.status = desired_status
                    connection.save(update_fields=["status", "updated_at"])
                if was_created:
                    created_connections += 1
                connection_created_at = random_between(
                    user_joined_at_by_id.get(user.id, now - timedelta(days=120)),
                    now - timedelta(days=rng.randint(0, 2)),
                )
                Connection.objects.filter(id=connection.id).update(
                    created_at=connection_created_at,
                    updated_at=connection_created_at,
                )

        # Pin a subset of posts so pin surfaces are exercised.
        for user in demo_users:
            posts_for_user = user_posts.get(user.id, [])
            if not posts_for_user:
                continue
            if rng.random() < 0.8:
                pinned_ref = max(posts_for_user, key=lambda item: item["created_at"])
                pin_stamp = pinned_ref["created_at"] + timedelta(hours=rng.randint(1, 72))
                Post.objects.filter(id=pinned_ref["id"]).update(is_pinned=True, updated_at=min(now, pin_stamp))

        # Add likes/reposts/bookmarks/replies/quotes/reports on other users' posts.
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
                action_candidates = []
                if rng.random() < 0.9:
                    action_candidates.append(PostInteraction.ActionType.LIKE)
                if rng.random() < 0.65:
                    action_candidates.append(PostInteraction.ActionType.REPOST)
                if rng.random() < 0.55:
                    action_candidates.append(PostInteraction.ActionType.BOOKMARK)
                if rng.random() < 0.3:
                    action_candidates.append(PostInteraction.ActionType.QUOTE)
                if rng.random() < 0.08:
                    action_candidates.append(PostInteraction.ActionType.REPORT)
                for action in action_candidates:
                    interaction_content = ""
                    if action == PostInteraction.ActionType.QUOTE:
                        quote_entry = demo_post_corpus[rng.randint(0, len(demo_post_corpus) - 1)]
                        interaction_content = (
                            str(quote_entry.get("quote_commentary", "")).strip()
                            or str(quote_entry.get("content", ""))[:220]
                        )
                    interaction, was_created = PostInteraction.objects.get_or_create(
                        post_id=target["id"],
                        user=user,
                        action_type=action,
                        defaults={"content": interaction_content},
                    )
                    if was_created:
                        created_interactions += 1
                        stamp = min(now, target["created_at"] + timedelta(hours=rng.randint(1, 120)))
                        PostInteraction.objects.filter(id=interaction.id).update(created_at=stamp)
                        actor_profile = getattr(user, "profile", None)
                        target_context = post_rank_context.get(target["id"], {"sentiment_label": "neutral", "sentiment_score": 0.0, "is_toxic": False})
                        if actor_profile:
                            target_label = str(target_context["sentiment_label"] or "neutral")
                            target_score = float(target_context["sentiment_score"] or 0.0)
                            event_label = target_label
                            event_score = target_score
                            if action == PostInteraction.ActionType.QUOTE and interaction_content:
                                quote_sentiment = score_sentiment_text(interaction_content)
                                event_label = quote_sentiment.label
                                event_score = float(quote_sentiment.score)
                            is_false_report = (
                                action == PostInteraction.ActionType.REPORT
                                and target_label != "negative"
                                and not bool(target_context.get("is_toxic"))
                            )
                            record_profile_action_score(
                                profile=actor_profile,
                                action_type=action,
                                sentiment_label=event_label,
                                sentiment_score=event_score,
                                post=Post(id=target["id"]),
                                interaction=interaction,
                                metadata={"source": "seed_demo"},
                                is_false_report=is_false_report,
                                is_toxic_report=action == PostInteraction.ActionType.REPORT and bool(target_context.get("is_toxic")),
                                target_sentiment_score=target_score,
                                recompute_rollup=False,
                            )
                            touched_profile_ids.add(actor_profile.id)
                if rng.random() < 0.55:
                    reply_entry = demo_post_corpus[rng.randint(0, len(demo_post_corpus) - 1)]
                    is_positive_reply = rng.random() < 0.58
                    reply_content = (
                        str(reply_entry.get("reply_positive", "")).strip()
                        if is_positive_reply
                        else str(reply_entry.get("reply_negative", "")).strip()
                    )
                    if not reply_content:
                        reply_content = str(reply_entry.get("content", ""))[:220]
                    reply = PostInteraction.objects.create(
                        post_id=target["id"],
                        user=user,
                        action_type=PostInteraction.ActionType.REPLY,
                        content=reply_content,
                    )
                    created_interactions += 1
                    reply_stamp = min(now, target["created_at"] + timedelta(hours=rng.randint(2, 160)))
                    PostInteraction.objects.filter(id=reply.id).update(created_at=reply_stamp)
                    reply_post = Post.objects.create(
                        author=user,
                        parent_post_id=target["id"],
                        content=reply_content,
                        visibility=Post.Visibility.PUBLIC,
                        interest_tags=[target["interest"]],
                    )
                    Post.objects.filter(id=reply_post.id).update(created_at=reply_stamp, updated_at=reply_stamp)
                    reply_label, reply_score = score_post_sentiment(reply_post)
                    post_rank_context[reply_post.id] = {
                        "sentiment_label": reply_label,
                        "sentiment_score": reply_score,
                        "is_toxic": False,
                    }
                    created_reply_posts += 1
                    actor_profile = getattr(user, "profile", None)
                    if actor_profile:
                        record_profile_action_score(
                            profile=actor_profile,
                            action_type=PostInteraction.ActionType.REPLY,
                            sentiment_label=reply_label,
                            sentiment_score=reply_score,
                            post=reply_post,
                            interaction=reply,
                            metadata={"source": "seed_demo"},
                            target_sentiment_score=float(
                                post_rank_context.get(target["id"], {}).get("sentiment_score", 0.0) or 0.0
                            ),
                            recompute_rollup=False,
                        )
                        touched_profile_ids.add(actor_profile.id)
                    if rng.random() < 0.4:
                        bookmark_reply, bookmark_created = PostInteraction.objects.get_or_create(
                            post_id=reply_post.id,
                            user=user,
                            action_type=PostInteraction.ActionType.BOOKMARK,
                            defaults={"content": ""},
                        )
                        if bookmark_created:
                            created_interactions += 1
                            PostInteraction.objects.filter(id=bookmark_reply.id).update(
                                created_at=min(now, reply_stamp + timedelta(hours=rng.randint(1, 24)))
                            )
                            actor_profile = getattr(user, "profile", None)
                            if actor_profile:
                                bookmark_label = str(reply_post.sentiment_label or "neutral")
                                bookmark_score = float(reply_post.sentiment_score or 0.0)
                                record_profile_action_score(
                                    profile=actor_profile,
                                    action_type=PostInteraction.ActionType.BOOKMARK,
                                    sentiment_label=bookmark_label,
                                    sentiment_score=bookmark_score,
                                    post=reply_post,
                                    interaction=bookmark_reply,
                                    metadata={"source": "seed_demo"},
                                    recompute_rollup=False,
                                )
                                touched_profile_ids.add(actor_profile.id)

        # Seed demo direct messages between the seed initiator and each demo account.
        install_state = InstallState.objects.filter(id=install_state_id).values(
            "master_admin_user_id",
            "seed_requested_by_user_id",
        ).first()
        seed_requester_user_id = int((install_state or {}).get("seed_requested_by_user_id") or 0)
        if seed_requester_user_id <= 0:
            seed_requester_user_id = int((install_state or {}).get("master_admin_user_id") or 0)
        seed_requester = User.objects.filter(id=seed_requester_user_id).first() if seed_requester_user_id > 0 else None
        if seed_requester:
            for index, demo_user in enumerate(demo_users):
                if demo_user.id == seed_requester.id:
                    continue
                thread = ensure_dm_thread_for_users(seed_requester.id, demo_user.id)
                corpus_entry = demo_post_corpus[(index * 13 + 5) % len(demo_post_corpus)]
                inbound_content = (
                    str(corpus_entry.get("reply_positive", "")).strip()
                    or str(corpus_entry.get("content", "")).strip()[:280]
                    or "Hello from your demo network."
                )
                outbound_content = (
                    f"Welcome {demo_user.username}. Thanks for helping seed this demo conversation."
                )
                inbound_created_at = random_between(
                    user_joined_at_by_id.get(demo_user.id, now - timedelta(days=120)),
                    now,
                )
                outbound_created_at = min(
                    now,
                    inbound_created_at + timedelta(minutes=rng.randint(3, 240)),
                )
                inbound_message = DMMessage.objects.create(
                    thread=thread,
                    sender=demo_user,
                    content=inbound_content,
                    attachments=[],
                    link_preview={},
                    ip_address="127.0.0.1",
                )
                outbound_message = DMMessage.objects.create(
                    thread=thread,
                    sender=seed_requester,
                    content=outbound_content,
                    attachments=[],
                    link_preview={},
                    ip_address="127.0.0.1",
                )
                DMMessage.objects.filter(id=inbound_message.id).update(created_at=inbound_created_at)
                DMMessage.objects.filter(id=outbound_message.id).update(created_at=outbound_created_at)
                latest_message_time = max(inbound_created_at, outbound_created_at)
                thread.last_message_at = latest_message_time
                thread.save(update_fields=["last_message_at", "updated_at"])
                DMThreadParticipant.objects.update_or_create(
                    thread=thread,
                    user=seed_requester,
                    defaults={
                        "last_read_at": outbound_created_at,
                        "last_read_message": outbound_message,
                    },
                )
                DMThreadParticipant.objects.update_or_create(
                    thread=thread,
                    user=demo_user,
                    defaults={
                        "last_read_at": inbound_created_at,
                        "last_read_message": inbound_message,
                    },
                )
                created_dm_messages += 2

        if touched_profile_ids:
            for seeded_profile in Profile.objects.filter(id__in=touched_profile_ids).only("id", "user_id"):
                recompute_profile_rank_rollups(seeded_profile)

        InstallState.objects.filter(id=install_state_id).update(
            seed_status="completed",
            seed_created_users=created_users,
            seed_created_posts=created_posts,
            seed_last_message=(
                "Demo data creation complete "
                f"({created_records}/{total_records} base records, "
                f"{created_connections} connections, {created_interactions} interactions, "
                f"{created_reply_posts} reply posts, {created_dm_messages} dm messages, "
                f"{created_mention_notifications} mention notifications)."
            ),
        )
        broadcast_install_state(install_state_id)
        install_state = InstallState.objects.filter(id=install_state_id).values(
            "master_admin_user_id",
            "seed_requested_by_user_id",
        ).first()
        master_admin_user_id = int((install_state or {}).get("master_admin_user_id") or 0)
        seed_requested_by_user_id = int((install_state or {}).get("seed_requested_by_user_id") or 0)
        if master_admin_user_id > 0:
            bump_user_feed_cache_version(master_admin_user_id)
        if seed_requested_by_user_id > 0 and seed_requested_by_user_id != master_admin_user_id:
            bump_user_feed_cache_version(seed_requested_by_user_id)
        if seed_requested_by_user_id > 0:
            create_notification(
                recipient_user_id=seed_requested_by_user_id,
                event_type="install.seed_completed",
                title="Demo data ready",
                message=(
                    f"Created {created_users} users, {created_posts} posts, "
                    f"{created_interactions} interactions, and {created_dm_messages} DM messages."
                ),
                payload={
                    "seed_status": "completed",
                    "created_users": created_users,
                    "created_posts": created_posts,
                    "created_interactions": created_interactions,
                    "created_dm_messages": created_dm_messages,
                    "created_mention_notifications": created_mention_notifications,
                },
            )
        return {
            "status": "ok",
            "created_users": created_users,
            "created_posts": created_posts,
            "created_connections": created_connections,
            "created_interactions": created_interactions,
            "created_reply_posts": created_reply_posts,
            "created_dm_messages": created_dm_messages,
            "created_mention_notifications": created_mention_notifications,
        }
    except Exception as exc:
        InstallState.objects.filter(id=install_state_id).update(
            seed_status="failed",
            seed_last_message=f"Seed failed: {exc}",
            seed_created_users=created_users,
            seed_created_posts=created_posts,
        )
        broadcast_install_state(install_state_id)
        install_state = InstallState.objects.filter(id=install_state_id).values(
            "master_admin_user_id",
            "seed_requested_by_user_id",
        ).first()
        master_admin_user_id = int((install_state or {}).get("master_admin_user_id") or 0)
        seed_requested_by_user_id = int((install_state or {}).get("seed_requested_by_user_id") or 0)
        if master_admin_user_id > 0:
            bump_user_feed_cache_version(master_admin_user_id)
        if seed_requested_by_user_id > 0 and seed_requested_by_user_id != master_admin_user_id:
            bump_user_feed_cache_version(seed_requested_by_user_id)
        raise
