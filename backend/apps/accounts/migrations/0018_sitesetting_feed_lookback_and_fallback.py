from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0017_profile_banned_at_profile_banned_reason_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesetting",
            name="feed_date_lookback_hours",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="sitesetting",
            name="feed_fallback_date_lookback_hours",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="sitesetting",
            name="feed_fallback_post_count",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
