from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DMThread",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("last_message_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                (
                    "user_a",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dm_threads_as_a",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user_b",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dm_threads_as_b",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["user_a", "-last_message_at"], name="messaging_d_user_a__da48b1_idx"),
                    models.Index(fields=["user_b", "-last_message_at"], name="messaging_d_user_b__5ab907_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("user_a", "user_b"), name="unique_dm_thread_pair"),
                    models.CheckConstraint(condition=Q(user_a__lt=models.F("user_b")), name="dm_thread_canonical_user_order"),
                ],
            },
        ),
        migrations.CreateModel(
            name="DMMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("content", models.CharField(blank=True, max_length=4000)),
                ("attachments", models.JSONField(blank=True, default=list)),
                ("link_preview", models.JSONField(blank=True, default=dict)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "sender",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dm_messages",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "thread",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages",
                        to="messaging.dmthread",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["thread", "-created_at"], name="messaging_d_thread__6b4d4e_idx"),
                    models.Index(fields=["sender", "-created_at"], name="messaging_d_sender__ca3a76_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="DMThreadParticipant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("last_read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "last_read_message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="read_by_participants",
                        to="messaging.dmmessage",
                    ),
                ),
                (
                    "thread",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="participants",
                        to="messaging.dmthread",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dm_participations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["user", "-updated_at"], name="messaging_d_user_id_e7771d_idx"),
                    models.Index(fields=["thread", "user"], name="messaging_d_thread__55fa82_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("thread", "user"), name="unique_dm_thread_participant"),
                ],
            },
        ),
    ]
