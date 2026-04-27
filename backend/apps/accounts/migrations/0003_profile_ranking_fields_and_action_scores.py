import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0010_post_sentiment_fields"),
        ("accounts", "0002_profile_profile_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="rank_action_scores",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="profile",
            name="rank_last_500_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="profile",
            name="rank_overall_score",
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name="profile",
            name="rank_provider",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.CreateModel(
            name="ProfileActionScore",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "action_type",
                    models.CharField(
                        choices=[
                            ("post", "Post"),
                            ("reply", "Reply"),
                            ("repost", "Repost"),
                            ("like", "Like"),
                            ("quote", "Quote"),
                            ("bookmark", "Bookmark"),
                            ("report", "Report"),
                        ],
                        max_length=24,
                    ),
                ),
                ("sentiment_label", models.CharField(default="neutral", max_length=16)),
                ("sentiment_score", models.FloatField(default=0.0)),
                ("contribution_score", models.FloatField(default=0.0)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "interaction",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="posts.postinteraction",
                    ),
                ),
                (
                    "post",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="posts.post",
                    ),
                ),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="action_scores",
                        to="accounts.profile",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="profileactionscore",
            index=models.Index(fields=["profile", "-created_at"], name="accounts_pr_profile_a34fd8_idx"),
        ),
        migrations.AddIndex(
            model_name="profileactionscore",
            index=models.Index(fields=["profile", "action_type", "-created_at"], name="accounts_pr_profile_14f77b_idx"),
        ),
    ]
